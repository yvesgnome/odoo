from odoo import api, fields, models

ALLOCATION_METHODS = [
    ('surface', 'Surface'),
    ('shares', 'Shares'),
    ('equal', 'Equal Parts'),
    ('consumption', 'Consumption'),
]


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    regie_charge_category_id = fields.Many2one(
        'regie.charge.category', string="Charge Category", index='btree_not_null',
        help="Recoverable charge category of this cost, used by the yearly charge statements of the "
             "building set in the analytic distribution.",
    )


class RegieAllocationKey(models.Model):
    """ How the costs of a charge category are split between the units of a building. Without a
    key, the costs are split by surface. """
    _name = 'regie.allocation.key'
    _description = "Charge Allocation Key"
    _order = 'building_id, category_id'
    _check_company_auto = True

    _building_category_unique = models.Constraint(
        'unique(building_id, category_id)',
        "There is already an allocation key for this building and charge category.",
    )

    name = fields.Char(compute='_compute_name', store=True)
    building_id = fields.Many2one('regie.building', required=True, index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='building_id.company_id', store=True, index=True)
    category_id = fields.Many2one('regie.charge.category', string="Charge Category", required=True)
    method = fields.Selection(ALLOCATION_METHODS, required=True, default='surface')
    line_ids = fields.One2many('regie.allocation.key.line', 'key_id', string="Shares")
    notes = fields.Text()

    @api.depends('building_id.name', 'category_id.name', 'method')
    def _compute_name(self):
        methods = dict(self._fields['method']._description_selection(self.env))
        for key in self:
            key.name = "%s – %s (%s)" % (key.building_id.name or '', key.category_id.name or '', methods.get(key.method))

    def action_fill_units(self):
        """ Add a share line for every unit of the building (100 shares each by default). """
        for key in self:
            existing = key.line_ids.unit_id
            key.line_ids = [(0, 0, {'unit_id': unit.id, 'shares': 100.0})
                            for unit in key.building_id.unit_ids - existing]

    def _get_unit_weights(self, units, date_from, date_to):
        """ {unit: weight} of the units for the period, according to the method. """
        self.ensure_one()
        if self.method == 'surface':
            return {unit: unit.surface for unit in units}
        if self.method == 'equal':
            return {unit: 1.0 for unit in units}
        if self.method == 'shares':
            shares = {line.unit_id: line.shares for line in self.line_ids}
            return {unit: shares.get(unit, 0.0) for unit in units}
        readings = self.env['regie.consumption.reading'].search([
            ('unit_id', 'in', units.ids),
            ('category_id', '=', self.category_id.id),
            ('date_to', '>=', date_from),
            ('date_to', '<=', date_to),
        ])
        weights = dict.fromkeys(units, 0.0)
        for reading in readings:
            weights[reading.unit_id] += reading.quantity
        return weights


class RegieAllocationKeyLine(models.Model):
    _name = 'regie.allocation.key.line'
    _description = "Charge Allocation Share"
    _order = 'key_id, unit_id'

    key_id = fields.Many2one('regie.allocation.key', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='key_id.company_id', store=True)
    building_id = fields.Many2one(related='key_id.building_id')
    unit_id = fields.Many2one('regie.unit', required=True, domain="[('building_id', '=', building_id)]")
    shares = fields.Float(digits=(12, 4))


class RegieConsumptionReading(models.Model):
    """ Consumption of a unit for a period (imported from the meter readings, CSV). Readings are
    taken into account by the statement of the year in which their period ends. """
    _name = 'regie.consumption.reading'
    _description = "Consumption Reading"
    _order = 'date_to desc, unit_id'

    unit_id = fields.Many2one('regie.unit', required=True, index=True, ondelete='cascade')
    building_id = fields.Many2one(related='unit_id.building_id', store=True)
    company_id = fields.Many2one(related='unit_id.company_id', store=True, index=True)
    category_id = fields.Many2one('regie.charge.category', string="Charge Category", required=True)
    meter_id = fields.Many2one('regie.meter', domain="[('unit_id', '=', unit_id)]")
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    quantity = fields.Float(required=True, digits=(12, 3))
    uom = fields.Char(string="Unit of Measure", help="e.g. kWh, m³, heat cost allocator units")
