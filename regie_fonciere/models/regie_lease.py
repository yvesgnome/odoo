from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools import format_structured_communication

LEASE_TYPES = [
    ('main_residence', 'Main Residence'),
    ('short_term', 'Short Term'),
    ('student', 'Student'),
    ('shared', 'Shared Housing'),
    ('commercial', 'Commercial'),
    ('parking', 'Parking'),
    ('precarious', 'Precarious Occupancy'),
    ('transit', 'Transit Housing'),
]
# Lease types that are not housing leases (housing rules do not apply).
NON_HOUSING_LEASE_TYPES = ('commercial', 'parking')
# Default duration (in months) proposed when encoding a lease; can be changed on each lease.
LEASE_TYPE_DEFAULT_DURATION = {
    'main_residence': 108,
    'short_term': 36,
    'student': 12,
    'shared': 108,
    'commercial': 108,
    'parking': 12,
    'precarious': 12,
    'transit': 18,
}
# Maximum duration (in months) of a short-term lease.
SHORT_TERM_MAX_DURATION = 36

LEASE_STATES = [
    ('draft', 'Draft'),
    ('signed', 'Signed'),
    ('active', 'Active'),
    ('notice', 'Notice Given'),
    ('terminated', 'Terminated'),
    ('rescinded', 'Rescinded'),
    ('litigation', 'Litigation'),
]
# States in which the tenant occupies the units and rent is invoiced.
OCCUPIED_LEASE_STATES = ('active', 'notice', 'litigation')


class RegieLease(models.Model):
    _name = 'regie.lease'
    _description = "Lease"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'
    _check_company_auto = True

    _structured_communication_unique = models.Constraint(
        'unique(structured_communication)',
        "The structured communication must be unique.",
    )

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='/', index='trigram')
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)
    state = fields.Selection(
        LEASE_STATES, string="Status", default='draft', required=True, tracking=True, copy=False,
        help="Signed leases become active on their effective date and are terminated the day after the "
             "move-out date (daily scheduled action). Rent is invoiced while active, in notice or in "
             "litigation.",
    )
    lease_type = fields.Selection(
        LEASE_TYPES, string="Type", required=True, default='main_residence', tracking=True,
        help="Determines the default duration, the maximum duration of short-term leases and whether the "
             "housing rules apply (all types except commercial and parking).",
    )
    is_housing = fields.Boolean(
        compute='_compute_is_housing', store=True,
        help="Housing lease (all types except commercial and parking): reference rent, EPC rules and deposit "
             "cap apply.",
    )

    # Units
    unit_ids = fields.Many2many(
        'regie.unit', 'regie_lease_unit_rel', 'lease_id', 'unit_id', string="Units",
        check_company=True, tracking=True,
        help="All the units rented by this lease, e.g. an apartment and a parking.",
    )
    main_unit_id = fields.Many2one(
        'regie.unit', string="Main Unit", required=True, check_company=True, tracking=True,
        domain="[('id', 'in', unit_ids)]",
        help="Unit that determines the building, the EPC rules of the indexation and the deposit cap.",
    )
    building_id = fields.Many2one(related='main_unit_id.building_id', store=True, index=True)

    # Parties
    partner_id = fields.Many2one(
        'res.partner', string="Main Tenant", required=True, index=True, tracking=True, check_company=True,
        help="Tenant to whom the rent invoices are addressed.",
    )
    tenant_ids = fields.Many2many(
        'res.partner', 'regie_lease_tenant_rel', 'lease_id', 'partner_id', string="Tenants", check_company=True,
        help="All the tenants signing the lease; the main tenant receives the invoices and letters.",
    )
    joint_liability = fields.Boolean(
        string="Jointly and Severally Liable", default=True,
        help="The tenants are jointly and severally liable for the obligations of the lease.",
    )
    guarantor_ids = fields.Many2many(
        'res.partner', 'regie_lease_guarantor_rel', 'lease_id', 'partner_id', string="Guarantors",
        check_company=True,
        help="Persons standing surety for the tenants (copy of the letters on request).",
    )

    # Dates
    signature_date = fields.Date(
        tracking=True,
        help="Date of signature of the lease. The initial index is the health index of the month before.",
    )
    start_date = fields.Date(
        string="Effective Date", required=True, tracking=True,
        help="Start of the occupation and of the invoicing. Its anniversary is the date of the yearly "
             "indexation.",
    )
    end_date = fields.Date(
        tracking=True,
        help="Contractual end of the lease. Leases ending within 6 months are listed in the reports.",
    )
    duration_months = fields.Integer(
        string="Duration (months)", compute='_compute_duration_months', store=True, readonly=False,
        help="Computed from the effective and end dates; changing the lease type proposes the usual duration.",
    )
    notice_date = fields.Date(
        string="Notice Date", tracking=True,
        help="Date on which the notice was given (by the tenant or the agency).",
    )
    exit_date = fields.Date(
        string="Actual Move-out Date", tracking=True,
        help="Day the tenant actually leaves: the last month is invoiced prorata and the lease is terminated "
             "the next day. Needed to release the deposit.",
    )
    next_anniversary_date = fields.Date(
        compute='_compute_next_anniversary_date',
        help="Next anniversary of the effective date (today or later).",
    )

    # Rent
    base_rent = fields.Monetary(string="Base Rent", required=True, tracking=True,
                                help="Rent at signature, basis of the indexation formula.")
    initial_charge_provision = fields.Monetary(
        string="Initial Charge Provision",
        help="Monthly charge provision (or flat-rate charges) at the signature: first line of the rent "
             "history.",
    )
    initial_index = fields.Float(
        string="Initial Index", digits=(10, 2), tracking=True,
        help="Health index (base 2013) of the month preceding the signature of the lease.",
    )
    reference_rent = fields.Monetary(
        string="Reference Rent", tracking=True,
        help="Reference rent of the Brussels regional grid (mandatory mention in housing leases).",
    )
    rent_line_ids = fields.One2many('regie.lease.rent.line', 'lease_id', string="Rent History", copy=False)
    current_rent = fields.Monetary(
        compute='_compute_current_rent',
        help="Rent in force today according to the rent history.",
    )
    current_charge_provision = fields.Monetary(string="Current Charge Provision", compute='_compute_current_rent')
    current_rent_explanation = fields.Text(compute='_compute_current_rent', help="How the current rent was obtained.")
    charge_mode = fields.Selection(
        [('provisions', 'Provisions'), ('flat', 'Flat Rate')],
        default='provisions', required=True, tracking=True,
        help="Provisions are regularised by a yearly statement; a flat rate is not.",
    )
    charge_category_ids = fields.Many2many(
        'regie.charge.category', string="Recoverable Charges",
        help="Charge categories recoverable from the tenant as provided by the lease.",
    )

    # Registration and indexation conditions
    registration_date = fields.Date(
        tracking=True,
        help="Date of registration of the lease (SPF Finances). An unregistered lease cannot be indexed.",
    )
    registration_reference = fields.Char(tracking=True, help="Reference given by the registration office.")
    registration_document = fields.Binary(
        attachment=True, copy=False,
        help="Proof of registration (scan or PDF).",
    )
    registration_document_name = fields.Char()
    is_registered = fields.Boolean(
        compute='_compute_is_registered', store=True,
        help="The lease has a registration date.",
    )
    is_written = fields.Boolean(
        string="Written Lease", default=True,
        help="Only written leases can be indexed.",
    )
    indexation_excluded = fields.Boolean(
        string="Indexation Excluded by the Lease",
        help="The lease contains a clause excluding the indexation of the rent.",
    )
    is_indexable = fields.Boolean(
        string="Indexable", default=True, tracking=True,
        help="Uncheck to never index this lease (decision of the agency); no proposal is created.",
    )
    peb_communicated = fields.Boolean(
        string="EPC Communicated to the Tenant", tracking=True,
        help="The EPC certificate of the unit was handed over to the tenant.",
    )

    # Invoicing
    invoicing_start_date = fields.Date(
        compute='_compute_invoicing_start_date', store=True, readonly=False,
        help="First day invoiced by the schedule (defaults to the effective date). "
             "Use it to start invoicing later, e.g. for leases taken over from a previous system.",
    )
    vat_option = fields.Boolean(string="VAT Option", tracking=True,
                                help="Opt for VAT on this commercial lease.")
    tax_ids = fields.Many2many(
        'account.tax', string="Taxes", check_company=True,
        domain="[('type_tax_use', '=', 'sale')]",
        help="Sales taxes applied to the rent and charges of a commercial lease with the VAT option.",
    )
    structured_communication = fields.Char(
        copy=False, readonly=True, index=True,
        help="Belgian structured communication of the lease (+++xxx/xxxx/xxxxx+++), unique, printed on every "
             "rent invoice so that the payments can be matched automatically.",
    )
    invoice_ids = fields.One2many(
        'account.move', 'regie_lease_id', string="Invoices",
        help="Customer invoices and credit notes of the lease (rent, regularisations, one-off invoices).",
    )
    invoice_count = fields.Integer(compute='_compute_invoice_stats')
    open_balance = fields.Monetary(
        compute='_compute_invoice_stats', string="Open Balance",
        help="Amount still due on the posted invoices and credit notes of the lease.",
    )
    overdue_invoice_count = fields.Integer(
        compute='_compute_invoice_stats', string="Overdue Invoices",
        help="Posted invoices of the lease not fully paid after their due date.",
    )
    notes = fields.Html()

    # ------------------------------------------------------------
    # COMPUTE
    # ------------------------------------------------------------

    @api.depends('lease_type')
    def _compute_is_housing(self):
        for lease in self:
            lease.is_housing = lease.lease_type not in NON_HOUSING_LEASE_TYPES

    @api.depends('start_date', 'end_date')
    def _compute_duration_months(self):
        for lease in self:
            if lease.start_date and lease.end_date:
                delta = relativedelta(lease.end_date + relativedelta(days=1), lease.start_date)
                lease.duration_months = delta.years * 12 + delta.months
            else:
                lease.duration_months = 0

    @api.depends('start_date')
    def _compute_invoicing_start_date(self):
        for lease in self:
            if not lease.invoicing_start_date or (lease.start_date and lease.invoicing_start_date < lease.start_date):
                lease.invoicing_start_date = lease.start_date

    @api.depends('registration_date')
    def _compute_is_registered(self):
        for lease in self:
            lease.is_registered = bool(lease.registration_date)

    @api.depends('start_date')
    def _compute_next_anniversary_date(self):
        today = fields.Date.context_today(self)
        for lease in self:
            lease.next_anniversary_date = lease._get_anniversary_on_or_after(today) if lease.start_date else False

    @api.depends('rent_line_ids.date_start', 'rent_line_ids.rent', 'rent_line_ids.charge_provision')
    def _compute_current_rent(self):
        today = fields.Date.context_today(self)
        for lease in self:
            line = lease._get_rent_line_at(today) or lease.rent_line_ids.sorted('date_start')[:1]
            lease.current_rent = line.rent
            lease.current_charge_provision = line.charge_provision
            lease.current_rent_explanation = line.explanation

    @api.depends('invoice_ids.state', 'invoice_ids.amount_residual_signed', 'invoice_ids.invoice_date_due')
    def _compute_invoice_stats(self):
        today = fields.Date.context_today(self)
        for lease in self:
            invoices = lease.sudo().invoice_ids.filtered(
                lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund'))
            lease.invoice_count = len(lease.sudo().invoice_ids)
            lease.open_balance = sum(invoices.mapped('amount_residual_signed'))
            lease.overdue_invoice_count = len(invoices.filtered(
                lambda m: m.move_type == 'out_invoice'
                and m.payment_state in ('not_paid', 'partial')
                and m.invoice_date_due and m.invoice_date_due < today))

    # ------------------------------------------------------------
    # CONSTRAINTS AND ONCHANGES
    # ------------------------------------------------------------

    @api.constrains('main_unit_id', 'unit_ids')
    def _check_main_unit(self):
        for lease in self:
            if lease.main_unit_id not in lease.unit_ids:
                raise ValidationError(self.env._("The main unit must be one of the units of the lease."))

    @api.constrains('partner_id', 'tenant_ids')
    def _check_main_tenant(self):
        for lease in self:
            if lease.partner_id not in lease.tenant_ids:
                raise ValidationError(self.env._("The main tenant must be one of the tenants of the lease."))

    @api.constrains('start_date', 'end_date', 'exit_date', 'lease_type')
    def _check_dates(self):
        for lease in self:
            if lease.end_date and lease.end_date < lease.start_date:
                raise ValidationError(self.env._("The end date of lease %s is before its effective date.", lease.name))
            if lease.exit_date and lease.exit_date < lease.start_date:
                raise ValidationError(self.env._("The move-out date of lease %s is before its effective date.", lease.name))
            if lease.lease_type == 'short_term' and lease.end_date \
                    and lease.end_date >= lease.start_date + relativedelta(months=SHORT_TERM_MAX_DURATION):
                raise ValidationError(self.env._(
                    "A short-term lease cannot last more than %s months.", SHORT_TERM_MAX_DURATION))

    @api.onchange('unit_ids')
    def _onchange_unit_ids(self):
        if self.main_unit_id._origin not in self.unit_ids._origin:
            self.main_unit_id = self.unit_ids[:1]

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_id not in self.tenant_ids:
            self.tenant_ids = [(4, self.partner_id.id)]

    @api.onchange('lease_type', 'start_date')
    def _onchange_lease_type_duration(self):
        months = LEASE_TYPE_DEFAULT_DURATION.get(self.lease_type)
        if self.start_date and months and not self._origin.end_date:
            self.end_date = self.start_date + relativedelta(months=months, days=-1)
        if self.lease_type != 'commercial':
            self.vat_option = False

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('partner_id'):
                vals.setdefault('tenant_ids', [])
                vals['tenant_ids'] = list(vals['tenant_ids']) + [(4, vals['partner_id'])]
            if vals.get('main_unit_id'):
                vals.setdefault('unit_ids', [])
                vals['unit_ids'] = list(vals['unit_ids']) + [(4, vals['main_unit_id'])]
        leases = super().create(vals_list)
        for lease in leases:
            if lease.name == '/':
                lease.name = self.env['ir.sequence'].with_company(lease.company_id).next_by_code(
                    'regie.lease', sequence_date=lease.start_date) or '/'
            lease.structured_communication = lease._get_structured_communication()
            if not lease.rent_line_ids:
                self.env['regie.lease.rent.line'].create({
                    'lease_id': lease.id,
                    'date_start': lease.start_date,
                    'rent': lease.base_rent,
                    'charge_provision': lease.initial_charge_provision,
                    'reason': 'initial',
                })
        return leases

    def unlink(self):
        if any(lease.state != 'draft' for lease in self):
            raise UserError(self.env._("Only draft leases can be deleted."))
        return super().unlink()

    def _get_structured_communication(self):
        """ Unique per lease: company prefix followed by the lease id, on 10 digits. """
        self.ensure_one()
        prefix = self.company_id.regie_communication_prefix or ''
        return format_structured_communication(int(prefix + str(self.id).rjust(10 - len(prefix), '0')))

    # ------------------------------------------------------------
    # BUSINESS
    # ------------------------------------------------------------

    @api.model
    def _get_occupied_states(self):
        return OCCUPIED_LEASE_STATES

    def _get_rent_line_at(self, date):
        """ Rent history line in force at `date` (empty recordset before the first line). """
        self.ensure_one()
        lines = self.rent_line_ids.filtered(lambda l: l.date_start <= date)
        return lines.sorted(lambda l: (l.date_start, l.id), reverse=True)[:1]

    def _get_rent_at(self, date):
        """ (rent, charge provision) in force at `date`. """
        line = self._get_rent_line_at(date)
        return line.rent, line.charge_provision

    def _get_anniversary_on_or_after(self, date):
        """ First anniversary of the effective date falling on or after `date`. """
        self.ensure_one()
        years = max(date.year - self.start_date.year, 1)
        anniversary = self.start_date + relativedelta(years=years)
        if anniversary < date:
            anniversary = self.start_date + relativedelta(years=years + 1)
        return anniversary

    def _get_occupancy_end_date(self):
        """ Last day the tenant occupies the units (move-out, else contractual end), or False. """
        self.ensure_one()
        return self.exit_date or (self.state in ('terminated', 'rescinded') and self.end_date) or False

    def _check_can_sign(self):
        for lease in self:
            if lease.is_housing and not lease.reference_rent:
                raise UserError(self.env._(
                    "The reference rent is a mandatory mention of housing leases (lease %s).", lease.name))
            if lease.base_rent <= 0:
                raise UserError(self.env._("The base rent of lease %s must be positive.", lease.name))

    def action_sign(self):
        self._check_can_sign()
        for lease in self.filtered(lambda l: l.state == 'draft'):
            lease.write({
                'state': 'signed',
                'signature_date': lease.signature_date or fields.Date.context_today(lease),
            })
        self._update_state_from_dates()

    def action_activate(self):
        self.filtered(lambda l: l.state == 'signed').state = 'active'

    def action_give_notice(self):
        for lease in self.filtered(lambda l: l.state == 'active'):
            lease.write({
                'state': 'notice',
                'notice_date': lease.notice_date or fields.Date.context_today(lease),
            })

    def action_terminate(self):
        for lease in self:
            if not lease.exit_date:
                raise UserError(self.env._("Set the actual move-out date of lease %s first.", lease.name))
        self.state = 'terminated'

    def action_rescind(self):
        for lease in self:
            if not lease.exit_date:
                raise UserError(self.env._("Set the actual move-out date of lease %s first.", lease.name))
        self.state = 'rescinded'

    def action_set_litigation(self):
        self.filtered(lambda l: l.state in OCCUPIED_LEASE_STATES).state = 'litigation'

    def action_end_litigation(self):
        self.filtered(lambda l: l.state == 'litigation').state = 'active'

    def action_reset_to_draft(self):
        self.filtered(lambda l: l.state == 'signed').state = 'draft'

    def _update_state_from_dates(self, today=None):
        """ Signed leases become active on their effective date; occupied leases are terminated the
        day after the move-out date. """
        today = today or fields.Date.context_today(self)
        for lease in self:
            if lease.state == 'signed' and lease.start_date <= today:
                lease.state = 'active'
            if lease.state in ('active', 'notice') and lease.exit_date and lease.exit_date < today:
                lease.state = 'terminated'

    @api.model
    def _cron_update_states(self):
        self.search([('state', 'in', ('signed', 'active', 'notice'))])._update_state_from_dates()

    def action_open_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice')
        action['domain'] = [('regie_lease_id', '=', self.id)]
        action['context'] = {
            'default_move_type': 'out_invoice',
            'default_regie_lease_id': self.id,
            'default_partner_id': self.partner_id.id,
        }
        return action

    def _action_new_move(self, move_type):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'views': [(self.env.ref('account.view_move_form').id, 'form')],
            'context': {
                'default_move_type': move_type,
                'default_regie_lease_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
                'default_payment_reference': self.structured_communication if move_type == 'out_invoice' else False,
            },
        }

    def action_new_invoice(self):
        return self._action_new_move('out_invoice')

    def action_new_credit_note(self):
        return self._action_new_move('out_refund')

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_setup_leases(self):
        """ Demo: VAT (21% services) on the commercial lease with VAT option. Idempotent. """
        lease = self.env.ref('regie_fonciere.demo_lease_08', raise_if_not_found=False)
        if lease and not lease.tax_ids:
            tax = self.env['account.chart.template'].with_company(lease.company_id).ref(
                'attn_VAT-OUT-21-S', raise_if_not_found=False)
            if tax:
                lease.tax_ids = tax
