from odoo import api, fields, models

# The 19 municipalities of the Brussels-Capital Region.
BRUSSELS_MUNICIPALITIES = [
    ('anderlecht', 'Anderlecht'),
    ('auderghem', 'Auderghem'),
    ('berchem_sainte_agathe', 'Berchem-Sainte-Agathe'),
    ('brussels', 'City of Brussels'),
    ('etterbeek', 'Etterbeek'),
    ('evere', 'Evere'),
    ('forest', 'Forest'),
    ('ganshoren', 'Ganshoren'),
    ('ixelles', 'Ixelles'),
    ('jette', 'Jette'),
    ('koekelberg', 'Koekelberg'),
    ('molenbeek', 'Molenbeek-Saint-Jean'),
    ('saint_gilles', 'Saint-Gilles'),
    ('saint_josse', 'Saint-Josse-ten-Noode'),
    ('schaerbeek', 'Schaerbeek'),
    ('uccle', 'Uccle'),
    ('watermael_boitsfort', 'Watermael-Boitsfort'),
    ('woluwe_saint_lambert', 'Woluwe-Saint-Lambert'),
    ('woluwe_saint_pierre', 'Woluwe-Saint-Pierre'),
]


class RegieBuilding(models.Model):
    _name = 'regie.building'
    _description = "Building"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True

    _code_company_unique = models.Constraint(
        'unique(code, company_id)',
        "The building code must be unique per company.",
    )

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(help="Short internal reference of the building.", tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char()
    city = fields.Char()
    municipality = fields.Selection(BRUSSELS_MUNICIPALITIES, tracking=True)
    country_id = fields.Many2one('res.country', default=lambda self: self.env.ref('base.be', raise_if_not_found=False))
    construction_year = fields.Integer()
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string="Analytic Account",
        check_company=True, copy=False, readonly=True,
        help="Created automatically; used on rent invoices and charge costs of this building.",
    )
    unit_ids = fields.One2many('regie.unit', 'building_id', string="Units")
    unit_count = fields.Integer(compute='_compute_unit_stats')
    free_unit_count = fields.Integer(compute='_compute_unit_stats')
    total_surface = fields.Float(compute='_compute_unit_stats', string="Total Surface (m²)")
    notes = fields.Html()

    @api.depends('unit_ids.surface', 'unit_ids.state')
    def _compute_unit_stats(self):
        for building in self:
            building.unit_count = len(building.unit_ids)
            building.free_unit_count = len(building.unit_ids.filtered(lambda u: u.state == 'free'))
            building.total_surface = sum(building.unit_ids.mapped('surface'))

    @api.model_create_multi
    def create(self, vals_list):
        buildings = super().create(vals_list)
        buildings._create_analytic_accounts()
        return buildings

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals or 'code' in vals:
            for building in self.filtered('analytic_account_id'):
                building.analytic_account_id.sudo().write({'name': building.name, 'code': building.code})
        return res

    def _create_analytic_accounts(self):
        plan = self.env.ref('regie_fonciere.analytic_plan_buildings')
        for building in self.filtered(lambda b: not b.analytic_account_id):
            building.analytic_account_id = self.env['account.analytic.account'].sudo().create({
                'name': building.name,
                'code': building.code,
                'plan_id': plan.id,
                'company_id': building.company_id.id,
            })

    def action_open_units(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('regie_fonciere.regie_unit_action')
        action['domain'] = [('building_id', '=', self.id)]
        action['context'] = {'default_building_id': self.id}
        return action
