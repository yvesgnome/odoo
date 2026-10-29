from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import month_end

INDEXATION_STATES = [
    ('to_validate', 'To Validate'),
    ('validated', 'Validated'),
    ('sent', 'Sent'),
    ('applied', 'Applied'),
    ('refused', 'Refused'),
]


class RegieIndexation(models.Model):
    """ Indexation proposal of a lease at an anniversary:
    new rent = base rent × new index / initial index (× EPC correction factor). """
    _name = 'regie.indexation'
    _description = "Rent Indexation"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'anniversary_date desc, id desc'
    _check_company_auto = True

    _lease_anniversary_unique = models.Constraint(
        'unique(lease_id, anniversary_date)',
        "There is already an indexation for this lease and anniversary.",
    )

    name = fields.Char(compute='_compute_name', store=True)
    lease_id = fields.Many2one('regie.lease', required=True, index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='lease_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='lease_id.currency_id')
    partner_id = fields.Many2one(related='lease_id.partner_id', store=True)
    building_id = fields.Many2one(related='lease_id.building_id', store=True)
    main_unit_id = fields.Many2one(related='lease_id.main_unit_id')
    state = fields.Selection(INDEXATION_STATES, string="Status", default='to_validate', required=True, tracking=True)
    anniversary_date = fields.Date(required=True, tracking=True)
    request_date = fields.Date(
        tracking=True, copy=False,
        help="Date of the written request to the tenant (date the letter is sent).",
    )
    effective_date = fields.Date(
        compute='_compute_effective_date', store=True, readonly=False, tracking=True,
        help="Anniversary date, limited to the retroactivity allowed before the request date.",
    )

    base_rent = fields.Monetary(readonly=True)
    initial_index = fields.Float(digits=(10, 2), readonly=True)
    new_index_month = fields.Date(readonly=True, help="Month of the new index (month preceding the anniversary).")
    new_index = fields.Float(digits=(10, 2), readonly=True)
    index_is_provisional = fields.Boolean(
        readonly=True,
        help="The index of the month preceding the anniversary is not published yet: the last "
             "published index is used. Recompute the proposal once it is available.",
    )
    peb_class = fields.Selection(related='lease_id.main_unit_id.peb_class', string="EPC Class")
    correction_factor = fields.Float(digits=(12, 9), readonly=True, default=1.0)
    computed_rent = fields.Monetary(readonly=True, help="Result of the indexation formula.")
    current_rent = fields.Monetary(readonly=True, help="Rent in force before the anniversary.")
    new_rent = fields.Monetary(tracking=True, help="Indexed rent proposed (can be lowered).")
    rent_increase = fields.Monetary(compute='_compute_rent_increase')
    rent_line_id = fields.Many2one('regie.lease.rent.line', readonly=True, copy=False)
    arrears_invoice_id = fields.Many2one('account.move', string="Arrears Invoice", readonly=True, copy=False)
    letter_attachment_id = fields.Many2one('ir.attachment', readonly=True, copy=False)
    refusal_reason = fields.Text(tracking=True)
    notes = fields.Text()

    @api.depends('lease_id.name', 'anniversary_date')
    def _compute_name(self):
        for indexation in self:
            indexation.name = "%s – %s" % (
                indexation.lease_id.name or '', indexation.anniversary_date and indexation.anniversary_date.strftime('%d/%m/%Y'))

    @api.depends('anniversary_date', 'request_date')
    def _compute_effective_date(self):
        for indexation in self:
            indexation.effective_date = indexation._get_effective_date()

    @api.depends('new_rent', 'current_rent')
    def _compute_rent_increase(self):
        for indexation in self:
            indexation.rent_increase = indexation.new_rent - indexation.current_rent

    def _get_effective_date(self, request_date=None):
        """ The indexation applies from the anniversary, but at most `retroactivity` months before
        the written request. """
        self.ensure_one()
        request_date = request_date or self.request_date
        if not self.anniversary_date:
            return False
        if not request_date:
            return self.anniversary_date
        months = self.lease_id.company_id.regie_indexation_retroactivity_months
        return max(self.anniversary_date, request_date - relativedelta(months=months))

    # ------------------------------------------------------------
    # COMPUTATION
    # ------------------------------------------------------------

    def _compute_indexation(self):
        """ (Re)compute the indexation formula from the lease and the index tables. """
        for indexation in self:
            lease = indexation.lease_id
            company = lease.company_id
            new_index_month = indexation.anniversary_date.replace(day=1) - relativedelta(months=1)
            index, is_exact = self.env['regie.health.index']._get_index(new_index_month, company.regie_index_base_year)
            if not index:
                raise UserError(self.env._("No health index found for %s.", new_index_month.strftime('%m/%Y')))
            factor = lease._get_peb_correction_factor(indexation.anniversary_date)
            computed = lease.base_rent * index.value / lease.initial_index * factor
            computed = lease.currency_id.round(computed)
            current_rent = lease._get_rent_at(indexation.anniversary_date - relativedelta(days=1))[0]
            indexation.write({
                'base_rent': lease.base_rent,
                'initial_index': lease.initial_index,
                'new_index_month': index.month,
                'new_index': index.value,
                'index_is_provisional': not is_exact,
                'correction_factor': factor,
                'computed_rent': computed,
                'current_rent': current_rent,
                'new_rent': computed,
            })

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def _check_supervisor(self):
        if not self.env.user.has_group('regie_fonciere.group_regie_supervisor'):
            raise UserError(self.env._("Only a supervisor can validate or apply an indexation."))

    def action_recompute(self):
        self.filtered(lambda i: i.state in ('to_validate', 'validated'))._compute_indexation()

    def action_validate(self):
        self._check_supervisor()
        for indexation in self:
            if indexation.state != 'to_validate':
                continue
            blocking = indexation.lease_id._get_indexation_blocking_reasons(fields.Date.context_today(self))
            if blocking:
                raise UserError(self.env._("The indexation of %(lease)s is not allowed:\n%(reasons)s",
                                           lease=indexation.lease_id.name, reasons="\n".join(blocking)))
            indexation.state = 'validated'

    def _get_letter_date(self):
        self.ensure_one()
        return self.request_date or fields.Date.context_today(self)

    def _get_letter_lang(self):
        self.ensure_one()
        return self.company_id._regie_get_letter_lang(self.partner_id)

    def action_send(self):
        """ Written request: PDF letter sent by email to the tenants from the lease chatter and
        attached to the lease. """
        for indexation in self.filtered(lambda i: i.state == 'validated'):
            request_date = indexation.request_date or fields.Date.context_today(self)
            indexation.write({'request_date': request_date, 'effective_date': indexation._get_effective_date(request_date)})
            lease = indexation.lease_id
            lang = indexation._get_letter_lang()
            attachment = self.env['ir.attachment']
            # While demo data is loaded (no HTTP server), wkhtmltopdf cannot fetch the report assets:
            # the letter is then printed later from the proposal (Print > Indexation Letter).
            if not self.env.context.get('install_demo'):
                pdf, _report_type = self.env['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf(
                    'regie_fonciere.action_report_indexation_letter', indexation.ids)
                attachment = attachment.create({
                    'name': "%s.pdf" % self.env._("Indexation %s", indexation.name).replace('/', '-'),
                    'raw': pdf,
                    'mimetype': 'application/pdf',
                    'res_model': 'regie.lease',
                    'res_id': lease.id,
                })
            body = self.with_context(lang=lang).env._(
                "Indexation of the rent at %(date)s: new rent %(rent)s.",
                date=indexation.effective_date.strftime('%d/%m/%Y'),
                rent="%.2f %s" % (indexation.new_rent, lease.currency_id.symbol),
            )
            lease.message_post(
                body=body,
                subject=self.with_context(lang=lang).env._("Indexation of your rent – %s", lease.name),
                partner_ids=lease.tenant_ids.ids,
                attachment_ids=attachment.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            indexation.write({'state': 'sent', 'letter_attachment_id': attachment.id})

    def action_apply(self):
        """ Add the new rent to the rent history (taken over by the invoicing schedule) and invoice
        the difference on the months already invoiced since the effective date. """
        self._check_supervisor()
        for indexation in self.filtered(lambda i: i.state == 'sent'):
            lease = indexation.lease_id
            effective_date = indexation.effective_date
            provision = lease._get_rent_at(effective_date)[1]
            RentLine = self.env['regie.lease.rent.line']
            rent_line = RentLine.search([('lease_id', '=', lease.id), ('date_start', '=', effective_date)], limit=1)
            vals = {
                'lease_id': lease.id,
                'date_start': effective_date,
                'rent': indexation.new_rent,
                'charge_provision': provision,
                'reason': 'indexation',
                'note': indexation.name,
            }
            if rent_line:
                rent_line.write(vals)
            else:
                rent_line = RentLine.create(vals)
            indexation.write({
                'state': 'applied',
                'rent_line_id': rent_line.id,
                'arrears_invoice_id': indexation._create_arrears_invoice().id,
            })

    def _get_arrears_amount(self):
        """ Difference between the new rent and the invoiced rent, for the days already invoiced
        from the effective date, prorated per day. """
        self.ensure_one()
        lease = self.lease_id
        amount = 0.0
        for line in lease.schedule_line_ids.filtered(lambda l: l.state == 'invoiced' and l.date_to >= self.effective_date):
            date_from = max(line.date_from, self.effective_date)
            days = (line.date_to - date_from).days + 1
            invoiced_daily = line.rent_amount / ((line.date_to - line.date_from).days + 1)
            new_daily = self.new_rent / month_end(line.period_date).day
            amount += (new_daily - invoiced_daily) * days
        return lease.currency_id.round(amount)

    def _create_arrears_invoice(self):
        self.ensure_one()
        lease = self.lease_id
        amount = self._get_arrears_amount()
        if lease.currency_id.compare_amounts(amount, 0.0) <= 0:
            return self.env['account.move']
        company = lease.company_id
        lang = lease.partner_id.lang or self.env.lang
        label = self.with_context(lang=lang).env._(
            "Rent indexation arrears since %s", self.effective_date.strftime('%d/%m/%Y'))
        today = fields.Date.context_today(self)
        invoice = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice',
            'company_id': company.id,
            'journal_id': company._regie_get_rent_journal().id,
            'partner_id': lease.partner_id.id,
            'invoice_date': today,
            'invoice_date_due': today + relativedelta(days=30),
            'invoice_payment_term_id': False,
            'payment_reference': lease.structured_communication,
            'ref': self.name,
            'regie_lease_id': lease.id,
            'invoice_line_ids': [(0, 0, lease._prepare_invoice_line_vals(
                self.env.ref('regie_fonciere.product_rent'), company.regie_rent_account_id, label, amount))],
        })
        invoice.action_post()
        return invoice

    def action_refuse(self):
        self.filtered(lambda i: i.state in ('to_validate', 'validated', 'sent')).state = 'refused'

    def action_reset_to_validate(self):
        self.filtered(lambda i: i.state in ('validated', 'refused')).state = 'to_validate'

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_create_indexations(self):
        """ Demo: one proposal per state (EPC F and E with correction factor to validate, validated,
        sent, applied with arrears invoice, refused). French is activated for the letters. """
        company = self.env.ref('regie_fonciere.demo_company', raise_if_not_found=False)
        if not company:
            return
        self = self.with_company(company).with_context(allowed_company_ids=company.ids, lang='fr_BE')  # noqa: PLW0642
        if self.search_count([('company_id', '=', company.id)]):
            return
        ref = self.env.ref
        date = fields.Date.to_date
        # To validate: EPC F and EPC E, leases in force before 14/10/2022 (correction factor)
        ref('regie_fonciere.demo_lease_01')._create_indexation(date('2026-12-01'))
        ref('regie_fonciere.demo_lease_02')._create_indexation(date('2026-11-01'))
        # Validated
        ref('regie_fonciere.demo_lease_07')._create_indexation(date('2026-11-01')).action_validate()
        # Sent (letter sent before the anniversary)
        sent = ref('regie_fonciere.demo_lease_06')._create_indexation(date('2026-09-15'))
        sent.action_validate()
        sent.request_date = date('2026-08-25')
        sent.action_send()
        # Applied: new rent in the history and arrears invoice for the months already invoiced
        applied = ref('regie_fonciere.demo_lease_03')._create_indexation(date('2026-09-01'))
        applied.action_validate()
        applied.request_date = date('2026-08-05')
        applied.action_send()
        applied.action_apply()
        # Refused
        refused = ref('regie_fonciere.demo_lease_09')._create_indexation(date('2026-08-01'))
        refused.refusal_reason = "Loyer du parking maintenu (décision du conseil d'administration du 14/07/2026)."
        refused.action_refuse()

    def action_open_lease(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'regie.lease',
            'res_id': self.lease_id.id,
            'view_mode': 'form',
        }
