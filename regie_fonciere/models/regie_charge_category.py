from odoo import fields, models


class RegieChargeCategory(models.Model):
    _name = 'regie.charge.category'
    _description = "Recoverable Charge Category"
    _order = 'sequence, name'

    _code_unique = models.Constraint('unique(code)', "The charge category code must be unique.")

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
