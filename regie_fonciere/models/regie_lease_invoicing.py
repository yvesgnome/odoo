import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import month_end, month_start

_logger = logging.getLogger(__name__)


class RegieLease(models.Model):
    _inherit = 'regie.lease'

    schedule_line_ids = fields.One2many('regie.lease.schedule.line', 'lease_id', string="Invoicing Schedule", copy=False)
    sepa_mandate_id = fields.Many2one(
        'account.direct.debit.mandate', string="SEPA Mandate", check_company=True, tracking=True,
        domain="[('partner_id', '=', partner_id), ('state', '=', 'active')]",
        help="Direct debit mandate of the main tenant used to collect the rent invoices.",
    )

    # ------------------------------------------------------------
    # PERIODS
    # ------------------------------------------------------------

    @api.model
    def _get_generation_date(self, company, period):
        """ Date on which the invoice of `period` (first day of a month) is generated. """
        month = period - relativedelta(months=1) if company.regie_invoice_month_offset == 'previous' else period
        return month.replace(day=min(max(company.regie_invoice_day, 1), month_end(month).day))

    @api.model
    def _get_due_date(self, company, period):
        return period.replace(day=min(max(company.regie_due_day, 1), month_end(period).day))

    @api.model
    def _get_last_period_to_invoice(self, company, today):
        """ Most recent period whose generation date is reached at `today`. """
        period = month_start(today)
        if company.regie_invoice_month_offset == 'previous':
            period += relativedelta(months=1)
        if self._get_generation_date(company, period) > today:
            period -= relativedelta(months=1)
        return period

    def _get_billable_leases(self):
        """ Leases whose units are occupied, or ended leases with a move-out date (last month). """
        return self.filtered(lambda l: l.state in l._get_occupied_states()
                             or (l.state in ('terminated', 'rescinded') and l._get_occupancy_end_date()))

    def _prepare_schedule_line_vals(self, period):
        """ Values of the schedule line of `period`, prorated on the occupied days; None if the
        lease does not occupy the units during that month. """
        self.ensure_one()
        occupancy_end = self._get_occupancy_end_date()
        date_from = max(period, self.start_date, self.invoicing_start_date or self.start_date)
        date_to = min(month_end(period), occupancy_end) if occupancy_end else month_end(period)
        if date_from > date_to:
            return None
        days_in_month = month_end(period).day
        prorata = ((date_to - date_from).days + 1) / days_in_month
        rent, charge_provision = self._get_rent_at(date_from)
        round_ = self.currency_id.round
        vals = {
            'lease_id': self.id,
            'period_date': period,
            'date_from': date_from,
            'date_to': date_to,
            'prorata': prorata,
            'rent_amount': round_(rent * prorata),
            'charge_amount': round_(charge_provision * prorata),
        }
        if self.currency_id.is_zero(vals['rent_amount'] + vals['charge_amount']):
            return None
        return vals

    def _generate_schedule_lines(self, today):
        """ Create the missing schedule lines up to the last period to invoice at `today`, starting
        from the first invoiced month: missed periods are caught up. """
        vals_list = []
        for lease in self._get_billable_leases():
            if not lease.invoicing_start_date:
                continue
            last_period = self._get_last_period_to_invoice(lease.company_id, today)
            occupancy_end = lease._get_occupancy_end_date()
            if occupancy_end:
                last_period = min(last_period, month_start(occupancy_end))
            existing = set(lease.schedule_line_ids.mapped('period_date'))
            period = month_start(lease.invoicing_start_date)
            while period <= last_period:
                if period not in existing:
                    vals = lease._prepare_schedule_line_vals(period)
                    if vals:
                        vals_list.append(vals)
                period += relativedelta(months=1)
        return self.env['regie.lease.schedule.line'].create(vals_list)

    # ------------------------------------------------------------
    # INVOICES
    # ------------------------------------------------------------

    def _get_sdd_payment_method_line(self, invoice_date):
        """ SEPA direct debit payment method line to use if the lease has a usable mandate. """
        self.ensure_one()
        mandate = self.sepa_mandate_id
        if not mandate or mandate.state != 'active' or mandate.start_date > invoice_date \
                or (mandate.end_date and mandate.end_date < invoice_date):
            return self.env['account.payment.method.line']
        return self.env['account.payment.method.line'].search([
            ('journal_id.company_id', '=', self.company_id.id),
            ('journal_id.type', '=', 'bank'),
            ('payment_type', '=', 'inbound'),
            ('code', 'in', self.env['account.payment.method']._get_sdd_payment_method_code()),
        ], limit=1)

    def _prepare_invoice_line_vals(self, product, account, name, amount):
        self.ensure_one()
        analytic = self.building_id.analytic_account_id
        return {
            'product_id': product.id,
            'name': name,
            'account_id': account.id,
            'quantity': 1.0,
            'price_unit': amount,
            'tax_ids': [(6, 0, self.tax_ids.ids if self.vat_option else [])],
            'analytic_distribution': {str(analytic.id): 100.0} if analytic else False,
        }

    def _prepare_invoice_vals(self, schedule_line, invoice_date):
        self.ensure_one()
        company = self.company_id
        if not company.regie_rent_account_id or not company.regie_charge_account_id:
            raise UserError(self.env._(
                "Configure the rent and charge provision income accounts of %s (Land Agency settings).", company.name))
        journal = company._regie_get_rent_journal()
        if not journal:
            raise UserError(self.env._("No sales journal found for %s.", company.name))
        env_lang = self.with_context(lang=self.partner_id.lang or self.env.lang).env
        period_label = schedule_line.period_date.strftime('%m/%Y')
        units_label = ", ".join(self.unit_ids.mapped('name'))
        prorata_label = ""
        if schedule_line.prorata < 1.0:
            prorata_label = env_lang._(" (from %(date_from)s to %(date_to)s)",
                                       date_from=schedule_line.date_from.strftime('%d/%m/%Y'),
                                       date_to=schedule_line.date_to.strftime('%d/%m/%Y'))
        lines = []
        if schedule_line.rent_amount:
            lines.append(self._prepare_invoice_line_vals(
                self.env.ref('regie_fonciere.product_rent'), company.regie_rent_account_id,
                env_lang._("Rent %(period)s – %(units)s", period=period_label, units=units_label) + prorata_label,
                schedule_line.rent_amount))
        if schedule_line.charge_amount:
            label = (env_lang._("Charge provision %(period)s", period=period_label) if self.charge_mode == 'provisions'
                     else env_lang._("Flat-rate charges %(period)s", period=period_label))
            lines.append(self._prepare_invoice_line_vals(
                self.env.ref('regie_fonciere.product_charge_provision'), company.regie_charge_account_id,
                label + prorata_label, schedule_line.charge_amount))
        due_date = max(self._get_due_date(company, schedule_line.period_date), invoice_date)
        vals = {
            'move_type': 'out_invoice',
            'company_id': company.id,
            'journal_id': journal.id,
            'partner_id': self.partner_id.id,
            'invoice_date': invoice_date,
            'invoice_date_due': due_date,
            'invoice_payment_term_id': False,
            'payment_reference': self.structured_communication,
            'ref': "%s %s" % (self.name, period_label),
            'regie_lease_id': self.id,
            'invoice_line_ids': [(0, 0, line_vals) for line_vals in lines],
        }
        sdd_method_line = self._get_sdd_payment_method_line(invoice_date)
        if sdd_method_line:
            vals['preferred_payment_method_line_id'] = sdd_method_line.id
        return vals

    def _create_invoices_from_schedule(self, schedule_lines, invoice_date):
        """ One posted invoice per schedule line (month). """
        invoices = self.env['account.move']
        for line in schedule_lines.filtered(lambda l: l.state == 'to_invoice' and not l.invoice_id):
            lease = line.lease_id
            invoice = self.env['account.move'].with_company(lease.company_id).create(
                lease._prepare_invoice_vals(line, invoice_date))
            invoice.action_post()
            line.invoice_id = invoice
            invoices |= invoice
        return invoices

    def _generate_invoices(self, today=None):
        """ Generate the missing schedule lines and invoice every line not invoiced yet. The
        invoice date is `today` (the generation date), also for caught-up periods. """
        today = today or fields.Date.context_today(self)
        self._generate_schedule_lines(today)
        to_invoice = self.schedule_line_ids.filtered(lambda l: l.state == 'to_invoice' and not l.invoice_id)
        return self._create_invoices_from_schedule(to_invoice.sorted('period_date'), today)

    def action_generate_schedule(self):
        invoices = self._generate_invoices()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if invoices else 'info',
                'message': self.env._("%s rent invoice(s) generated.", len(invoices)),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_generate_invoices(self):
        """ Demo: SEPA mandate, 3 follow-up levels without fees and the rent invoices generated by
        the schedule from January 2025 to today, as the daily cron would have done, with payments.
        Does nothing if the demo leases already have a schedule. """
        company = self.env.ref('regie_fonciere.demo_company', raise_if_not_found=False)
        if not company:
            return
        self = self.with_company(company).with_context(allowed_company_ids=company.ids, lang='fr_BE')  # noqa: PLW0642
        leases = self.search([('company_id', '=', company.id)])
        if not leases or leases.schedule_line_ids:
            return
        ref = self.env.ref
        company.sdd_creditor_identifier = 'BE68ZZZ0123456789'

        # SEPA direct debit mandate of the tenant of lease 03
        lease_03 = ref('regie_fonciere.demo_lease_03')
        mandate = self.env['account.direct.debit.mandate'].create({
            'name': 'RF-DEMO-0001',
            'partner_id': lease_03.partner_id.id,
            'partner_bank_id': ref('regie_fonciere.demo_bank_youssef_benali').id,
            'company_id': company.id,
            'start_date': '2024-12-01',
        })
        mandate.state = 'active'
        lease_03.sepa_mandate_id = mandate

        # Follow-up levels: J+10, J+25, J+45, no fees
        FollowupLine = self.env['account_followup.followup.line']
        FollowupLine.search([('company_id', '=', company.id)]).unlink()
        FollowupLine.create([
            {'company_id': company.id, 'delay': 10, 'send_email': True,
             'mail_template_id': ref('account_followup.mail_template_partner_payment_kind_reminder').id},
            {'company_id': company.id, 'delay': 25, 'send_email': True,
             'mail_template_id': ref('account_followup.mail_template_partner_payment_second_reminder').id},
            {'company_id': company.id, 'delay': 45, 'send_email': True, 'create_activity': True,
             'activity_type_id': ref('mail.mail_activity_data_call').id,
             'activity_summary': "Dernier rappel : appeler le locataire",
             'mail_template_id': ref('account_followup.mail_template_partner_payment_last_reminder').id},
        ])

        # Invoices: run the schedule on each generation date since December 2024
        today = fields.Date.context_today(self)
        generation_date = self._get_generation_date(company, fields.Date.to_date('2025-01-01'))
        while generation_date <= today:
            leases._generate_invoices(generation_date)
            next_period = self._get_last_period_to_invoice(company, generation_date) + relativedelta(months=1)
            generation_date = self._get_generation_date(company, next_period)

        # Payments: most invoices are paid a few days after their due date, except
        # - the litigation lease (12) since March 2026, the unregistered lease (04) since September 2026
        #   and the last month of the terminated lease (11): overdue;
        # - lease 05 in October 2026: partially paid;
        # - invoices not due yet: open.
        bank_journal = self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(company), ('type', '=', 'bank')], limit=1)
        # Without outstanding account, Odoo only matches payments with invoices at bank reconciliation:
        # post the demo payments directly on the bank account so that the invoices are really paid.
        manual_method_line = bank_journal.inbound_payment_method_line_ids.filtered(lambda l: l.code == 'manual')[:1]
        manual_method_line.payment_account_id = bank_journal.default_account_id
        unpaid_from = {
            ref('regie_fonciere.demo_lease_12'): fields.Date.to_date('2026-03-01'),
            ref('regie_fonciere.demo_lease_04'): fields.Date.to_date('2026-09-01'),
            ref('regie_fonciere.demo_lease_11'): fields.Date.to_date('2026-08-01'),
        }
        lease_05 = ref('regie_fonciere.demo_lease_05')
        for line in leases.schedule_line_ids.filtered('invoice_id').sorted('period_date'):
            invoice = line.invoice_id
            if invoice.invoice_date_due >= today or line.period_date >= unpaid_from.get(line.lease_id, line.period_date + relativedelta(days=1)):
                continue
            amount = invoice.amount_residual
            if line.lease_id == lease_05 and line.period_date == fields.Date.to_date('2026-10-01'):
                amount = invoice.currency_id.round(amount / 2)
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({
                'payment_date': min(invoice.invoice_date_due + relativedelta(days=3), today),
                'journal_id': bank_journal.id,
                'payment_method_line_id': manual_method_line.id,
                'amount': amount,
                'payment_difference_handling': 'open',
            })._create_payments()

    @api.model
    def _cron_generate_invoices(self):
        leases = self.search([('state', 'in', ('active', 'notice', 'litigation', 'terminated', 'rescinded'))])
        for company in leases.company_id:
            company_leases = leases.filtered(lambda l: l.company_id == company).with_company(company)
            for lease in company_leases._get_billable_leases():
                try:
                    with self.env.cr.savepoint():
                        lease._generate_invoices()
                except UserError as e:
                    _logger.warning("Rent invoicing of lease %s failed: %s", lease.name, e)
