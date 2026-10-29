from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class RegieDashboard(models.TransientModel):
    """ Key figures of the agency for the current company. """
    _name = 'regie.dashboard'
    _description = "Land Agency Dashboard"

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    unpaid_amount = fields.Monetary(string="Open Rent Balance", compute='_compute_figures')
    overdue_amount = fields.Monetary(string="Overdue", compute='_compute_figures')
    overdue_tenant_count = fields.Integer(string="Tenants with Overdue Invoices", compute='_compute_figures')
    unit_count = fields.Integer(string="Units", compute='_compute_figures')
    vacant_unit_count = fields.Integer(string="Vacant Units", compute='_compute_figures')
    occupancy_rate = fields.Float(string="Occupancy Rate (%)", compute='_compute_figures', digits=(5, 1))
    running_lease_count = fields.Integer(string="Running Leases", compute='_compute_figures')
    ending_lease_count = fields.Integer(string="Leases Ending within 6 Months", compute='_compute_figures')
    indexation_month_count = fields.Integer(string="Indexations This Month", compute='_compute_figures')
    indexation_to_validate_count = fields.Integer(string="Indexations to Validate", compute='_compute_figures')
    deposit_release_count = fields.Integer(string="Deposit Releases in Progress", compute='_compute_figures')
    litigation_lease_count = fields.Integer(string="Leases in Litigation", compute='_compute_figures')

    @api.depends_context('lang')
    def _compute_display_name(self):
        for dashboard in self:
            dashboard.display_name = self.env._("Dashboard")

    def _get_unpaid_domain(self, overdue=False):
        domain = [
            ('company_id', '=', self.company_id.id),
            ('regie_lease_id', '!=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ]
        if overdue:
            domain.append(('invoice_date_due', '<', fields.Date.context_today(self)))
        return domain

    @api.depends('company_id')
    def _compute_figures(self):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        Lease = self.env['regie.lease']
        for dashboard in self:
            company_domain = [('company_id', '=', dashboard.company_id.id)]
            Move = self.env['account.move'].sudo()
            unpaid = Move.search(dashboard._get_unpaid_domain())
            overdue = unpaid.filtered(lambda m: m.invoice_date_due and m.invoice_date_due < today)
            dashboard.unpaid_amount = sum(unpaid.mapped('amount_residual_signed'))
            dashboard.overdue_amount = sum(overdue.mapped('amount_residual_signed'))
            dashboard.overdue_tenant_count = len(overdue.partner_id)
            units = self.env['regie.unit'].search(company_domain)
            dashboard.unit_count = len(units)
            dashboard.vacant_unit_count = len(units.filtered(lambda u: u.state == 'free'))
            dashboard.occupancy_rate = 100.0 * len(units.filtered(lambda u: u.state == 'rented')) / len(units) if units else 0.0
            running = Lease.search(company_domain + [('state', 'in', Lease._get_occupied_states())])
            dashboard.running_lease_count = len(running)
            dashboard.ending_lease_count = len(running.filtered(
                lambda l: l.end_date and l.end_date <= today + relativedelta(months=6)))
            dashboard.litigation_lease_count = len(running.filtered(lambda l: l.state == 'litigation'))
            Indexation = self.env['regie.indexation']
            dashboard.indexation_month_count = Indexation.search_count(company_domain + [
                ('state', 'in', ('to_validate', 'validated', 'sent')),
                ('anniversary_date', '<', month_start + relativedelta(months=2)),
            ])
            dashboard.indexation_to_validate_count = Indexation.search_count(company_domain + [('state', '=', 'to_validate')])
            dashboard.deposit_release_count = self.env['regie.deposit'].search_count(
                company_domain + [('state', '=', 'release_requested')])

    @api.model
    def action_open_dashboard(self):
        dashboard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Dashboard"),
            'res_model': self._name,
            'res_id': dashboard.id,
            'view_mode': 'form',
            'views': [(self.env.ref('regie_fonciere.regie_dashboard_view_form').id, 'form')],
            'target': 'current',
        }

    def _open_action(self, xmlid, domain=None, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        if domain is not None:
            action['domain'] = domain
        if context is not None:
            action['context'] = context
        return action

    def action_open_unpaid_tenants(self):
        return self._open_action('regie_fonciere.regie_unpaid_by_tenant_action')

    def action_open_unpaid_buildings(self):
        return self._open_action('regie_fonciere.regie_unpaid_by_building_action')

    def action_open_vacant_units(self):
        return self._open_action('regie_fonciere.regie_unit_vacant_action')

    def action_open_ending_leases(self):
        return self._open_action('regie_fonciere.regie_lease_ending_action')

    def action_open_litigation_leases(self):
        return self._open_action('regie_fonciere.regie_lease_action', context={'search_default_litigation': 1})

    def action_open_indexations_month(self):
        return self._open_action('regie_fonciere.regie_indexation_this_month_action')

    def action_open_indexations_to_validate(self):
        return self._open_action('regie_fonciere.regie_indexation_to_process_action',
                                 context={'search_default_to_validate': 1, 'search_default_group_month': 1})

    def action_open_deposit_releases(self):
        return self._open_action('regie_fonciere.regie_deposit_action', context={'search_default_release': 1})
