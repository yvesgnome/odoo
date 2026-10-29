from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

DEPOSIT_TYPES = [
    ('blocked_account', 'Blocked Account'),
    ('bank_guarantee', 'Progressive Bank Guarantee'),
    ('cpas', 'CPAS Guarantee'),
    ('housing_fund', 'Housing Fund'),
    ('other', 'Other'),
]

DEPOSIT_STATES = [
    ('requested', 'Requested'),
    ('partial', 'Partially Constituted'),
    ('constituted', 'Constituted'),
    ('release_requested', 'Release Requested'),
    ('released', 'Released'),
    ('retained', 'Retained'),
]


class RegieDeposit(models.Model):
    """ Rental deposit, followed outside the accounting (the money is on an account in the name of
    the tenant or guaranteed by a third party). """
    _name = 'regie.deposit'
    _description = "Rental Deposit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    lease_id = fields.Many2one('regie.lease', required=True, index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='lease_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='lease_id.currency_id')
    partner_id = fields.Many2one(
        'res.partner', string="Tenant", required=True, check_company=True,
        compute='_compute_partner_id', store=True, readonly=False, precompute=True,
    )
    building_id = fields.Many2one(related='lease_id.building_id', store=True)
    lease_state = fields.Selection(related='lease_id.state', string="Lease Status")
    exit_date = fields.Date(related='lease_id.exit_date')
    deposit_type = fields.Selection(
        DEPOSIT_TYPES, string="Form", required=True, default='blocked_account', tracking=True,
        help="Blocked account in the name of the tenant, progressive bank guarantee (built up by monthly "
             "payments), guarantee of the CPAS, loan of the Brussels Housing Fund or other form.",
    )
    state = fields.Selection(
        DEPOSIT_STATES, string="Status", default='requested', required=True, tracking=True,
        help="Requested → (partially) constituted → release requested at the end of the lease → released "
             "(returned, minus the retentions) or retained (fully kept by the agency).",
    )
    date = fields.Date(
        string="Request Date", default=fields.Date.context_today, required=True,
        help="Date of the request; the legal cap is computed with the rent in force at that date.",
    )
    amount = fields.Monetary(required=True, tracking=True, help="Deposit required by the lease.")
    constituted_amount = fields.Monetary(
        tracking=True,
        help="Amount actually deposited or guaranteed so far.",
    )
    bank_name = fields.Char(
        string="Bank or Guarantor",
        help="Bank holding the blocked account or issuing the guarantee, or the guarantor (CPAS, Housing "
             "Fund).",
    )
    bank_bic = fields.Char(string="BIC")
    account_reference = fields.Char(
        string="IBAN or Reference", tracking=True,
        help="IBAN of the blocked account or reference of the guarantee.",
    )

    # Legal cap (housing leases)
    cap_amount = fields.Monetary(
        compute='_compute_cap', string="Legal Cap",
        help="Maximum deposit of a housing lease: number of months of rent (excluding charges) set "
             "in the company settings.",
    )
    exceeds_cap = fields.Boolean(compute='_compute_cap')

    # Release
    release_request_date = fields.Date(
        tracking=True, copy=False,
        help="Date on which the release was requested; reminders are scheduled after the move-out.",
    )
    release_date = fields.Date(tracking=True, copy=False)
    unpaid_rent_amount = fields.Monetary(
        string="Unpaid Rents", tracking=True,
        help="Filled by Compute Retentions from the open rent invoices of the lease; can be changed.",
    )
    unpaid_charges_amount = fields.Monetary(
        string="Unpaid Charges", tracking=True,
        help="Filled by Compute Retentions from the open charge invoices of the lease; can be changed.",
    )
    damage_amount = fields.Monetary(
        string="Damages", tracking=True,
        help="Damages noted in the exit inventory, encoded by hand.",
    )
    retained_amount = fields.Monetary(
        compute='_compute_release_amounts', store=True, tracking=True,
        help="Total of the retentions, limited to the constituted amount.",
    )
    released_amount = fields.Monetary(
        string="Amount Returned to the Tenant", compute='_compute_release_amounts', store=True,
        help="Constituted amount minus the retentions.",
    )
    retention_reason = fields.Text()
    notes = fields.Text()

    @api.depends('lease_id.name', 'deposit_type')
    def _compute_name(self):
        types = dict(self._fields['deposit_type']._description_selection(self.env))
        for deposit in self:
            deposit.name = "%s – %s" % (deposit.lease_id.name or '', types.get(deposit.deposit_type, ''))

    @api.depends('lease_id')
    def _compute_partner_id(self):
        for deposit in self:
            deposit.partner_id = deposit.partner_id or deposit.lease_id.partner_id

    @api.depends('amount', 'lease_id', 'date', 'lease_id.rent_line_ids.rent')
    def _compute_cap(self):
        for deposit in self:
            lease = deposit.lease_id
            months = lease.company_id.regie_deposit_cap_months
            if not lease or not lease.is_housing or not months:
                deposit.cap_amount = 0.0
                deposit.exceeds_cap = False
                continue
            rent = lease._get_rent_at(max(deposit.date or lease.start_date, lease.start_date))[0]
            deposit.cap_amount = rent * months
            deposit.exceeds_cap = lease.currency_id.compare_amounts(deposit.amount, deposit.cap_amount) > 0

    @api.depends('unpaid_rent_amount', 'unpaid_charges_amount', 'damage_amount', 'constituted_amount')
    def _compute_release_amounts(self):
        for deposit in self:
            retained = deposit.unpaid_rent_amount + deposit.unpaid_charges_amount + deposit.damage_amount
            deposit.retained_amount = min(retained, deposit.constituted_amount)
            deposit.released_amount = deposit.constituted_amount - deposit.retained_amount

    @api.onchange('constituted_amount')
    def _onchange_constituted_amount(self):
        if self.state in ('requested', 'partial', 'constituted') and self.constituted_amount:
            self.state = self._get_constitution_state()

    def _get_constitution_state(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.constituted_amount, self.amount) >= 0:
            return 'constituted'
        return 'partial' if self.constituted_amount else 'requested'

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_mark_constituted(self):
        for deposit in self.filtered(lambda d: d.state in ('requested', 'partial')):
            if not deposit.constituted_amount:
                deposit.constituted_amount = deposit.amount
            deposit.state = deposit._get_constitution_state()

    def action_compute_retentions(self):
        """ Unpaid rents and charges = open balance of the rent and charge invoices of the lease. """
        for deposit in self:
            invoices = deposit.lease_id.sudo().invoice_ids.filtered(
                lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund'))
            rent_product = self.env.ref('regie_fonciere.product_rent')
            unpaid_rent = unpaid_charges = 0.0
            for invoice in invoices.filtered(lambda m: not m.currency_id.is_zero(m.amount_residual)):
                ratio = invoice.amount_residual_signed / invoice.amount_total_signed if invoice.amount_total_signed else 0.0
                for line in invoice.invoice_line_ids:
                    if line.product_id == rent_product:
                        unpaid_rent += line.price_total * ratio * (1 if invoice.move_type == 'out_invoice' else -1)
                    else:
                        unpaid_charges += line.price_total * ratio * (1 if invoice.move_type == 'out_invoice' else -1)
            deposit.write({
                'unpaid_rent_amount': max(deposit.currency_id.round(unpaid_rent), 0.0),
                'unpaid_charges_amount': max(deposit.currency_id.round(unpaid_charges), 0.0),
            })

    def action_request_release(self):
        """ End of lease: release requested; reminders to follow the return of the deposit, which is
        expected within the legal delay after the move-out. """
        activity_type = self.env.ref('mail.mail_activity_data_todo')
        for deposit in self:
            if deposit.state not in ('constituted', 'partial'):
                raise UserError(self.env._("Only a constituted deposit can be released (%s).", deposit.name))
            if not deposit.lease_id.exit_date:
                raise UserError(self.env._("Set the move-out date of lease %s first.", deposit.lease_id.name))
            deposit.write({'state': 'release_requested', 'release_request_date': fields.Date.context_today(deposit)})
            company = deposit.company_id
            for days in (company.regie_deposit_reminder_days_1, company.regie_deposit_reminder_days_2):
                if not days:
                    continue
                deposit.activity_schedule(
                    activity_type_id=activity_type.id,
                    date_deadline=deposit.lease_id.exit_date + relativedelta(days=days),
                    summary=self.env._("Deposit release: follow up (%s days after move-out)", days),
                    note=self.env._("The deposit must be returned within %s months after the move-out.",
                                    company.regie_deposit_return_months),
                    user_id=self.env.user.id,
                )

    def action_release(self):
        for deposit in self.filtered(lambda d: d.state == 'release_requested'):
            fully_retained = deposit.currency_id.compare_amounts(deposit.retained_amount, deposit.constituted_amount) >= 0
            deposit.write({
                'state': 'retained' if fully_retained and deposit.constituted_amount else 'released',
                'release_date': fields.Date.context_today(deposit),
            })
            deposit.activity_ids.action_feedback(feedback=self.env._("Deposit released."))

    def action_reset(self):
        for deposit in self.filtered(lambda d: d.state in ('release_requested', 'released', 'retained')):
            deposit.write({'state': deposit._get_constitution_state(), 'release_date': False})

    def action_print_release_form(self):
        return self.env.ref('regie_fonciere.action_report_deposit_release').report_action(self)

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_process_deposits(self):
        """ Demo: retentions and release request of the deposit of the terminated lease (11), full
        retention of the deposit of the litigation lease (12). """
        self = self.with_context(lang='fr_BE')  # noqa: PLW0642 (demo texts in French)
        deposit = self.env.ref('regie_fonciere.demo_deposit_11', raise_if_not_found=False)
        if deposit and deposit.state == 'constituted':
            deposit.action_compute_retentions()
            deposit.write({'damage_amount': 150.0, 'retention_reason': "Loyer impayé d'août 2026 ; porte d'armoire de cuisine cassée."})
            deposit.action_request_release()
        deposit = self.env.ref('regie_fonciere.demo_deposit_12', raise_if_not_found=False)
        if deposit and deposit.state == 'constituted':
            deposit.action_compute_retentions()
            deposit.retention_reason = "Loyers impayés depuis mars 2026 (procédure devant la justice de paix)."
            deposit.state = 'release_requested'
            deposit.action_release()
