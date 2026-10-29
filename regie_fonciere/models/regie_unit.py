from odoo import api, fields, models
from odoo.fields import Domain

UNIT_TYPES = [
    ('apartment', 'Apartment'),
    ('house', 'House'),
    ('studio', 'Studio'),
    ('retail', 'Retail'),
    ('office', 'Office'),
    ('parking', 'Parking'),
    ('cellar', 'Cellar'),
]
# Unit types that are dwellings (housing rules apply: EPC, reference rent, deposit cap...).
DWELLING_UNIT_TYPES = ('apartment', 'house', 'studio')

# Brussels EPC (PEB) energy classes.
PEB_CLASSES = [
    ('a++', 'A++'),
    ('a+', 'A+'),
    ('a', 'A'),
    ('b', 'B'),
    ('c', 'C'),
    ('d', 'D'),
    ('e', 'E'),
    ('f', 'F'),
    ('g', 'G'),
]

# Kept for future developments (allocation, income-based rents); informative only for now.
HOUSING_CATEGORIES = [
    ('free', 'Free-market rent'),
    ('moderate', 'Moderate rent'),
    ('medium', 'Medium rent'),
    ('transit', 'Transit housing'),
    ('student', 'Student housing'),
]


class RegieUnit(models.Model):
    _name = 'regie.unit'
    _description = "Rental Unit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'building_id, name'
    _check_company_auto = True

    _name_building_unique = models.Constraint(
        'unique(building_id, name)',
        "The unit reference must be unique within a building.",
    )

    name = fields.Char(string="Reference", required=True, tracking=True)
    building_id = fields.Many2one(
        'regie.building', required=True, index=True, ondelete='restrict',
        check_company=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', related='building_id.company_id', store=True, index=True, precompute=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)
    unit_type = fields.Selection(
        UNIT_TYPES, string="Type", required=True, default='apartment', tracking=True,
        help="Apartments, houses and studios are dwellings: the housing rules apply to them (EPC conditions, "
             "reference rent, deposit cap).",
    )
    is_dwelling = fields.Boolean(
        compute='_compute_is_dwelling', store=True,
        help="Apartment, house or studio: the housing rules apply to the leases of this unit.",
    )
    housing_category = fields.Selection(
        HOUSING_CATEGORIES, tracking=True,
        help="Category of the dwelling in the housing policy of the agency. Informative for now; prepared for "
             "the income-based rents and the allocation of the dwellings.",
    )
    floor = fields.Integer(help="0 for the ground floor, negative for basements.")
    surface = fields.Float(
        string="Surface (m²)", digits=(10, 2), tracking=True,
        help="Surface used by the charge allocation keys of type Surface.",
    )
    bedroom_count = fields.Integer(string="Bedrooms")
    peb_class = fields.Selection(
        PEB_CLASSES, string="EPC Class", tracking=True,
        help="Energy class of the EPC certificate. For leases in force before 14/10/2022, classes E, F and G "
             "reduce the indexed rent with the EPC correction factor.",
    )
    peb_certificate_number = fields.Char(
        string="EPC Certificate Number",
        help="Number of the EPC certificate; without certificate the rent of a dwelling cannot be indexed.",
    )
    peb_valid_until = fields.Date(
        string="EPC Valid Until", tracking=True,
        help="End of validity of the EPC certificate. An expired certificate blocks the indexation of the "
             "rent.",
    )
    peb_is_valid = fields.Boolean(
        string="Valid EPC", compute='_compute_peb_is_valid', search='_search_peb_is_valid',
        help="The EPC certificate exists and is valid today.",
    )
    cadastral_income = fields.Monetary(tracking=True, help="Non-indexed cadastral income of the unit.")
    meter_ids = fields.One2many('regie.meter', 'unit_id', string="Meters")
    lease_ids = fields.Many2many(
        'regie.lease', 'regie_lease_unit_rel', 'unit_id', 'lease_id', string="Leases",
        help="All the leases of the unit, past and present.",
    )
    current_lease_id = fields.Many2one(
        'regie.lease', compute='_compute_current_lease_id', string="Current Lease",
        help="Lease currently occupying the unit (active, in notice or in litigation).",
    )
    under_works = fields.Boolean(
        string="Under Works", tracking=True,
        help="The unit cannot be rented because of works. Its status is Under Works as long as no lease "
             "occupies it.",
    )
    state = fields.Selection(
        [('free', 'Free'), ('rented', 'Rented'), ('works', 'Under Works')],
        string="Status", compute='_compute_state', store=True, tracking=True,
        help="Computed: Rented while a lease of the unit is active, in notice or in litigation; otherwise "
             "Under Works or Free.",
    )
    notes = fields.Html()

    @api.depends('unit_type')
    def _compute_is_dwelling(self):
        for unit in self:
            unit.is_dwelling = unit.unit_type in DWELLING_UNIT_TYPES

    def _is_peb_valid_at(self, date):
        self.ensure_one()
        return bool(self.peb_class and self.peb_certificate_number
                    and self.peb_valid_until and self.peb_valid_until >= date)

    @api.depends('peb_class', 'peb_certificate_number', 'peb_valid_until')
    def _compute_peb_is_valid(self):
        today = fields.Date.context_today(self)
        for unit in self:
            unit.peb_is_valid = unit._is_peb_valid_at(today)

    def _search_peb_is_valid(self, operator, value):
        if operator != 'in':
            return NotImplemented
        today = fields.Date.context_today(self)
        valid_domain = Domain([
            ('peb_class', '!=', False),
            ('peb_certificate_number', '!=', False),
            ('peb_valid_until', '>=', today),
        ])
        return valid_domain if True in value else ~valid_domain

    @api.depends('under_works', 'lease_ids.state')
    def _compute_state(self):
        # The lease states are kept up to date by a daily cron, so the unit status can be stored.
        for unit in self:
            if unit._get_current_lease():
                unit.state = 'rented'
            else:
                unit.state = 'works' if unit.under_works else 'free'

    @api.depends('lease_ids.state')
    def _compute_current_lease_id(self):
        for unit in self:
            unit.current_lease_id = unit._get_current_lease()

    def _get_current_lease(self):
        self.ensure_one()
        occupied_states = self.env['regie.lease']._get_occupied_states()
        return self.lease_ids.filtered(lambda l: l.state in occupied_states)[:1]
