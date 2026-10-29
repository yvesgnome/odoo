from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import fmt_amount, month_start
from .regie_charge import ALLOCATION_METHODS


class RegieChargeStatement(models.Model):
    """ Yearly statement of the recoverable charges of a building (calendar year). """
    _name = 'regie.charge.statement'
    _description = "Charge Statement"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, building_id'
    _check_company_auto = True

    _building_year_unique = models.Constraint(
        'unique(building_id, year)',
        "There is already a charge statement for this building and year.",
    )

    name = fields.Char(compute='_compute_name', store=True)
    building_id = fields.Many2one('regie.building', required=True, index=True, check_company=True, tracking=True)
    company_id = fields.Many2one(related='building_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    year = fields.Integer(
        required=True, default=lambda self: fields.Date.context_today(self).year - 1, tracking=True,
        help="Calendar year of the statement: costs booked and occupation from 1 January to 31 December.",
    )
    date_from = fields.Date(compute='_compute_dates', store=True)
    date_to = fields.Date(compute='_compute_dates', store=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('computed', 'Computed'), ('invoiced', 'Invoiced')],
        string="Status", default='draft', required=True, tracking=True,
        help="Draft → Computed (costs split, can be recomputed) → Invoiced (regularisations posted).",
    )
    cost_line_ids = fields.One2many('regie.charge.statement.cost', 'statement_id', string="Costs")
    lease_line_ids = fields.One2many('regie.charge.statement.lease', 'statement_id', string="Leases")
    detail_ids = fields.One2many('regie.charge.statement.detail', 'statement_id', string="Details")
    total_cost = fields.Monetary(compute='_compute_totals')
    total_tenants = fields.Monetary(string="Charged to Tenants", compute='_compute_totals')
    total_agency = fields.Monetary(
        string="Borne by the Agency", compute='_compute_totals',
        help="Part of the costs not recoverable: vacant units, categories not provided by the leases, "
             "flat-rate leases.",
    )
    notes = fields.Text()

    @api.depends('building_id.name', 'year')
    def _compute_name(self):
        for statement in self:
            statement.name = "%s – %s" % (statement.building_id.name or '', statement.year)

    @api.depends('year')
    def _compute_dates(self):
        for statement in self:
            statement.date_from = date(statement.year, 1, 1) if statement.year else False
            statement.date_to = date(statement.year, 12, 31) if statement.year else False

    @api.depends('cost_line_ids.amount', 'cost_line_ids.agency_amount')
    def _compute_totals(self):
        for statement in self:
            statement.total_cost = sum(statement.cost_line_ids.mapped('amount'))
            statement.total_agency = sum(statement.cost_line_ids.mapped('agency_amount'))
            statement.total_tenants = statement.total_cost - statement.total_agency

    # ------------------------------------------------------------
    # COMPUTATION
    # ------------------------------------------------------------

    def _get_cost_lines(self):
        """ Posted vendor bill lines of the year with a charge category, analytically on the
        building: {category: amount} (share of the building in the analytic distribution). """
        self.ensure_one()
        analytic = self.building_id.analytic_account_id
        lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('regie_charge_category_id', '!=', False),
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund', 'in_receipt')),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        costs = defaultdict(float)
        for line in lines:
            percentage = sum(
                value for key, value in (line.analytic_distribution or {}).items()
                if str(analytic.id) in key.split(',')
            )
            if percentage:
                costs[line.regie_charge_category_id] += line.balance * percentage / 100.0
        return costs

    def _get_occupancies(self, unit):
        """ [(lease, date_from, date_to)] of the leases occupying `unit` during the year. """
        self.ensure_one()
        occupancies = []
        for lease in unit.lease_ids.filtered(lambda l: l.state not in ('draft', 'signed')):
            end = lease._get_occupancy_end_date() or self.date_to
            date_from, date_to = max(lease.start_date, self.date_from), min(end, self.date_to)
            if date_from <= date_to:
                occupancies.append((lease, date_from, date_to))
        return occupancies

    def action_compute(self):
        for statement in self:
            if statement.state == 'invoiced':
                raise UserError(self.env._("The statement %s is already invoiced.", statement.name))
            statement._compute_statement()
            statement.state = 'computed'

    def _compute_statement(self):
        """ Split the costs of each category between the units (allocation key), then between the
        leases by day of occupation. Vacant days, categories not provided by the lease and leases
        with flat-rate charges are borne by the agency. """
        self.ensure_one()
        self.cost_line_ids.unlink()
        self.detail_ids.unlink()
        self.lease_line_ids.filtered(lambda l: not l.invoice_id).unlink()
        units = self.building_id.unit_ids
        year_days = (self.date_to - self.date_from).days + 1
        round_ = self.currency_id.round
        Key = self.env['regie.allocation.key']
        cost_vals, detail_vals = [], []
        for category, amount in sorted(self._get_cost_lines().items(), key=lambda c: c[0].sequence):
            key = Key.search([('building_id', '=', self.building_id.id), ('category_id', '=', category.id)], limit=1) \
                or Key.new({'building_id': self.building_id.id, 'category_id': category.id, 'method': 'surface'})
            weights = key._get_unit_weights(units, self.date_from, self.date_to)
            total_weight = sum(weights.values())
            charged = 0.0
            if total_weight:
                for unit, weight in weights.items():
                    if not weight:
                        continue
                    unit_amount = amount * weight / total_weight
                    for lease, date_from, date_to in self._get_occupancies(unit):
                        if category not in lease.charge_category_ids or lease.charge_mode != 'provisions':
                            continue
                        days = (date_to - date_from).days + 1
                        lease_amount = round_(unit_amount * days / year_days)
                        charged += lease_amount
                        detail_vals.append({
                            'statement_id': self.id,
                            'lease_id': lease.id,
                            'unit_id': unit.id,
                            'category_id': category.id,
                            'method': key.method,
                            'weight': weight,
                            'total_weight': total_weight,
                            'category_amount': amount,
                            'days': days,
                            'date_from': date_from,
                            'date_to': date_to,
                            'amount': lease_amount,
                        })
            cost_vals.append({
                'statement_id': self.id,
                'category_id': category.id,
                'method': key.method,
                'amount': round_(amount),
                'agency_amount': round_(amount - charged),
            })
        self.env['regie.charge.statement.cost'].create(cost_vals)
        details = self.env['regie.charge.statement.detail'].create(detail_vals)

        # One result line per lease charged or having paid provisions during the year
        leases = details.lease_id | self._get_leases_with_provisions()
        existing = {line.lease_id: line for line in self.lease_line_ids}
        lease_vals = []
        for lease in leases:
            values = {
                'actual_amount': sum(details.filtered(lambda d: d.lease_id == lease).mapped('amount')),
                'provisions_amount': self._get_provisions_called(lease),
            }
            if lease in existing:
                existing[lease].write(values)
            else:
                lease_vals.append({'statement_id': self.id, 'lease_id': lease.id, **values})
        self.env['regie.charge.statement.lease'].create(lease_vals)

    def _get_leases_with_provisions(self):
        self.ensure_one()
        return self.env['regie.lease.schedule.line'].search([
            ('lease_id.building_id', '=', self.building_id.id),
            ('lease_id.charge_mode', '=', 'provisions'),
            ('state', '=', 'invoiced'),
            ('period_date', '>=', self.date_from),
            ('period_date', '<=', self.date_to),
            ('charge_amount', '!=', 0),
        ]).lease_id

    def _get_provisions_called(self, lease):
        """ Charge provisions invoiced to the lease for the months of the year. """
        self.ensure_one()
        lines = lease.schedule_line_ids.filtered(
            lambda l: l.state == 'invoiced' and self.date_from <= l.period_date <= self.date_to)
        return sum(lines.mapped('charge_amount'))

    def action_generate_invoices(self):
        for statement in self:
            if statement.state != 'computed':
                raise UserError(self.env._("Compute the statement %s first.", statement.name))
            statement.lease_line_ids._create_regularisation_moves()
            statement.state = 'invoiced'

    def action_reset_to_draft(self):
        for statement in self:
            if statement.lease_line_ids.invoice_id.filtered(lambda m: m.state == 'posted'):
                raise UserError(self.env._("Cancel the regularisation invoices of %s first.", statement.name))
            statement.lease_line_ids.invoice_id = False
            statement.state = 'draft'

    def action_print_statements(self):
        return self.env.ref('regie_fonciere.action_report_charge_statement').report_action(self.lease_line_ids)

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_charge_statement(self):
        """ Demo: 2025 charge costs (vendor bills) of the 8-apartment building, allocation keys,
        consumption readings and the 2025 statement computed and invoiced. """
        company = self.env.ref('regie_fonciere.demo_company', raise_if_not_found=False)
        if not company:
            return
        self = self.with_company(company).with_context(allowed_company_ids=company.ids, lang='fr_BE')  # noqa: PLW0642
        building = self.env.ref('regie_fonciere.demo_building_heron')
        if self.search_count([('building_id', '=', building.id)]):
            return
        ref = self.env.ref
        analytic = {str(building.analytic_account_id.id): 100.0}
        Account = self.env['account.account']

        def account(code):
            return Account.search([*Account._check_company_domain(company), ('code', '=', code)], limit=1) \
                or company.expense_account_id

        bills = [
            # (supplier, date, [(category, account code, label, amount excl. VAT)])
            ('demo_supplier_heating', '2025-03-31', [
                ('charge_category_heating', '6125', "Gaz – T1 2025", 1650.0),
                ('charge_category_maintenance', '6110', "Contrat d'entretien chaudière 2025", 380.0)]),
            ('demo_supplier_heating', '2025-12-31', [
                ('charge_category_heating', '6125', "Gaz – T2 à T4 2025", 2150.0)]),
            ('demo_supplier_water', '2025-12-15', [
                ('charge_category_water', '61251', "Consommation d'eau 2025 (compteur commun)", 1640.0)]),
            ('demo_supplier_energy', '2025-12-20', [
                ('charge_category_common_electricity', '6125', "Électricité des communs 2025", 690.0)]),
            ('demo_supplier_cleaning', '2025-06-30', [
                ('charge_category_cleaning', '6110', "Nettoyage des communs – 1er semestre 2025", 780.0)]),
            ('demo_supplier_cleaning', '2025-12-31', [
                ('charge_category_cleaning', '6110', "Nettoyage des communs – 2e semestre 2025", 780.0)]),
            ('demo_supplier_elevator', '2025-01-31', [
                ('charge_category_elevator', '6110', "Contrat d'entretien ascenseur 2025", 1150.0)]),
        ]
        for supplier, bill_date, lines in bills:
            bill = self.env['account.move'].create({
                'move_type': 'in_invoice',
                'company_id': company.id,
                'partner_id': ref('regie_fonciere.%s' % supplier).id,
                'invoice_date': bill_date,
                'date': bill_date,
                'ref': "%s %s" % (ref('regie_fonciere.%s' % supplier).name[:12], bill_date),
                'invoice_line_ids': [(0, 0, {
                    'name': label,
                    'account_id': account(code).id,
                    'quantity': 1.0,
                    'price_unit': amount,
                    'tax_ids': [(6, 0, [])],
                    'analytic_distribution': analytic,
                    'regie_charge_category_id': ref('regie_fonciere.%s' % category).id,
                }) for category, code, label, amount in lines],
            })
            bill.action_post()

        # Allocation keys: heating by consumption, water and elevator by shares, cleaning in equal
        # parts, common electricity and maintenance contracts by surface (default, no key).
        Key = self.env['regie.allocation.key']
        units = {unit.name: unit for unit in building.unit_ids}
        Key.create({'building_id': building.id, 'category_id': ref('regie_fonciere.charge_category_heating').id,
                    'method': 'consumption'})
        Key.create({'building_id': building.id, 'category_id': ref('regie_fonciere.charge_category_cleaning').id,
                    'method': 'equal'})
        water_shares = {'HER-RDC': 60, 'HER-1.1': 110, 'HER-1.2': 95, 'HER-2.1': 115, 'HER-2.2': 55,
                        'HER-3.1': 125, 'HER-3.2': 90, 'HER-4.1': 105, 'HER-4.2': 100}
        Key.create({'building_id': building.id, 'category_id': ref('regie_fonciere.charge_category_water').id,
                    'method': 'shares',
                    'line_ids': [(0, 0, {'unit_id': units[name].id, 'shares': shares}) for name, shares in water_shares.items()]})
        # The shop on the ground floor does not use the elevator
        elevator_shares = {name: (0 if name == 'HER-RDC' else int(name[4]) * 10 + 10) for name in units}
        Key.create({'building_id': building.id, 'category_id': ref('regie_fonciere.charge_category_elevator').id,
                    'method': 'shares',
                    'line_ids': [(0, 0, {'unit_id': units[name].id, 'shares': shares}) for name, shares in elevator_shares.items()]})
        # Heat cost allocator readings 2025 (as imported from the CSV of the reading company)
        readings = {'HER-1.1': 1480, 'HER-1.2': 1210, 'HER-2.1': 1395, 'HER-2.2': 560, 'HER-3.1': 240,
                    'HER-3.2': 1130, 'HER-4.1': 1310, 'HER-4.2': 180, 'HER-RDC': 950}
        self.env['regie.consumption.reading'].create([{
            'unit_id': units[name].id,
            'category_id': ref('regie_fonciere.charge_category_heating').id,
            'date_from': '2025-01-01',
            'date_to': '2025-12-31',
            'quantity': quantity,
            'uom': "unités répartiteurs",
        } for name, quantity in readings.items()])

        statement = self.create({'building_id': building.id, 'year': 2025})
        statement.action_compute()
        statement.action_generate_invoices()


class RegieChargeStatementCost(models.Model):
    _name = 'regie.charge.statement.cost'
    _description = "Charge Statement Cost"
    _order = 'statement_id, id'

    statement_id = fields.Many2one('regie.charge.statement', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='statement_id.company_id', store=True)
    currency_id = fields.Many2one(related='statement_id.currency_id')
    category_id = fields.Many2one('regie.charge.category', string="Charge Category", required=True)
    method = fields.Selection(ALLOCATION_METHODS, string="Allocation")
    amount = fields.Monetary(string="Cost")
    agency_amount = fields.Monetary(string="Borne by the Agency",
                                    help="Vacant units, categories not provided by the leases, flat-rate leases.")
    tenant_amount = fields.Monetary(string="Charged to Tenants", compute='_compute_tenant_amount')

    @api.depends('amount', 'agency_amount')
    def _compute_tenant_amount(self):
        for line in self:
            line.tenant_amount = line.amount - line.agency_amount


class RegieChargeStatementDetail(models.Model):
    _name = 'regie.charge.statement.detail'
    _description = "Charge Statement Detail"
    _order = 'statement_id, lease_id, category_id'

    statement_id = fields.Many2one('regie.charge.statement', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='statement_id.company_id', store=True)
    currency_id = fields.Many2one(related='statement_id.currency_id')
    lease_id = fields.Many2one('regie.lease', required=True, index=True)
    unit_id = fields.Many2one('regie.unit', required=True)
    category_id = fields.Many2one('regie.charge.category', string="Charge Category", required=True)
    method = fields.Selection(ALLOCATION_METHODS, string="Allocation")
    weight = fields.Float(
        digits=(12, 4),
        help="Weight of the unit for the allocation key (surface, shares, 1 or consumption).",
    )
    total_weight = fields.Float(digits=(12, 4), help="Sum of the weights of all the units of the building.")
    category_amount = fields.Monetary(
        string="Building Cost",
        help="Cost of the category for the whole building.",
    )
    date_from = fields.Date()
    date_to = fields.Date()
    days = fields.Integer(help="Days of occupation of the unit by the lease during the year.")
    amount = fields.Monetary(string="Share")


class RegieChargeStatementLease(models.Model):
    """ Result of the statement for a lease: share of the actual charges vs provisions called. """
    _name = 'regie.charge.statement.lease'
    _description = "Charge Statement per Lease"
    _order = 'statement_id, lease_id'

    statement_id = fields.Many2one('regie.charge.statement', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='statement_id.company_id', store=True)
    currency_id = fields.Many2one(related='statement_id.currency_id')
    year = fields.Integer(related='statement_id.year')
    lease_id = fields.Many2one('regie.lease', required=True, index=True)
    partner_id = fields.Many2one(related='lease_id.partner_id')
    detail_ids = fields.One2many('regie.charge.statement.detail', compute='_compute_detail_ids')
    provisions_amount = fields.Monetary(
        string="Provisions Called",
        help="Charge provisions invoiced to the lease for the months of the year.",
    )
    actual_amount = fields.Monetary(
        string="Actual Share",
        help="Share of the actual charges of the year: allocation key × days of occupation, only for the "
             "categories provided by the lease.",
    )
    balance = fields.Monetary(compute='_compute_balance', store=True,
                              help="Positive: the tenant owes the difference; negative: refund to the tenant.")
    invoice_id = fields.Many2one(
        'account.move', string="Regularisation", copy=False,
        help="Regularisation invoice (balance due) or credit note (refund).",
    )
    proposed_provision = fields.Monetary(
        compute='_compute_proposed_provision', store=True, readonly=False,
        help="Monthly provision suggested from the actual charges of the year.")
    provision_rent_line_id = fields.Many2one(
        'regie.lease.rent.line', string="Provision Adjustment", copy=False,
        help="Rent history line created by Apply Provision.",
    )

    @api.depends('statement_id', 'lease_id')
    def _compute_detail_ids(self):
        for line in self:
            line.detail_ids = line.statement_id.detail_ids.filtered(lambda d: d.lease_id == line.lease_id)

    @api.depends('provisions_amount', 'actual_amount')
    def _compute_balance(self):
        for line in self:
            line.balance = line.actual_amount - line.provisions_amount

    @api.depends('actual_amount', 'statement_id.detail_ids.days')
    def _compute_proposed_provision(self):
        for line in self:
            details = line.statement_id.detail_ids.filtered(lambda d: d.lease_id == line.lease_id)
            days = max(details.mapped('days') or [0])
            year_days = (line.statement_id.date_to - line.statement_id.date_from).days + 1 if line.statement_id.date_to else 365
            line.proposed_provision = line.currency_id.round(line.actual_amount * year_days / days / 12) if days else 0.0

    def _create_regularisation_moves(self):
        """ Invoice (tenant owes) or credit note (refund) of the balance, due in 30 days. """
        product = self.env.ref('regie_fonciere.product_charge_regularisation')
        for line in self.filtered(lambda l: not l.invoice_id and not l.currency_id.is_zero(l.balance)):
            lease = line.lease_id
            company = lease.company_id
            today = fields.Date.context_today(line)
            label = line.with_context(lang=lease.partner_id.lang or self.env.lang).env._(
                "Charge statement %(year)s – %(building)s", year=line.year, building=lease.building_id.name)
            move_type = 'out_invoice' if line.balance > 0 else 'out_refund'
            invoice = self.env['account.move'].with_company(company).create({
                'move_type': move_type,
                'company_id': company.id,
                'journal_id': company._regie_get_rent_journal().id,
                'partner_id': lease.partner_id.id,
                'invoice_date': today,
                'invoice_date_due': today + relativedelta(days=30),
                'invoice_payment_term_id': False,
                'payment_reference': lease.structured_communication if move_type == 'out_invoice' else False,
                'ref': line.statement_id.name,
                'regie_lease_id': lease.id,
                'invoice_line_ids': [(0, 0, lease._prepare_invoice_line_vals(
                    product, company.regie_charge_account_id, label, abs(line.balance)))],
            })
            invoice.action_post()
            line.invoice_id = invoice

    def action_apply_provision(self):
        """ New provision in the rent history from the next month (supervisor validation). """
        if not self.env.user.has_group('regie_fonciere.group_regie_supervisor'):
            raise UserError(self.env._("Only a supervisor can apply a provision adjustment."))
        for line in self.filtered(lambda l: not l.provision_rent_line_id and l.proposed_provision):
            lease = line.lease_id
            date_start = month_start(fields.Date.context_today(line)) + relativedelta(months=1)
            rent = lease._get_rent_at(date_start)[0]
            RentLine = self.env['regie.lease.rent.line']
            rent_line = RentLine.search([('lease_id', '=', lease.id), ('date_start', '=', date_start)], limit=1)
            vals = {'rent': rent, 'charge_provision': line.proposed_provision}
            if rent_line:
                rent_line.write(vals)
            else:
                rent_line = RentLine.create({
                    'lease_id': lease.id, 'date_start': date_start, 'reason': 'provision_adjustment',
                    'note': line.statement_id.name, **vals,
                })
            line.provision_rent_line_id = rent_line

    def action_print(self):
        return self.env.ref('regie_fonciere.action_report_charge_statement').report_action(self)


class RegieLeaseRentLine(models.Model):
    _inherit = 'regie.lease.rent.line'

    def _get_explanation(self):
        self.ensure_one()
        if self.reason != 'provision_adjustment':
            return super()._get_explanation()
        result = self.env['regie.charge.statement.lease'].search([('provision_rent_line_id', '=', self.id)], limit=1)
        if not result:
            return super()._get_explanation()
        env = self.env
        days = max(result.detail_ids.mapped('days') or [0])
        return env._(
            "Charge provision adjusted after the charge statement %(statement)s: actual share %(share)s for "
            "%(days)s days of occupation, i.e. %(provision)s per month. Rent unchanged.",
            statement=result.statement_id.name,
            share=fmt_amount(env, result.actual_amount, self.currency_id),
            days=days,
            provision=fmt_amount(env, self.charge_provision, self.currency_id),
        )
