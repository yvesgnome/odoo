import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RegieMeter(models.Model):
    _name = 'regie.meter'
    _description = "Utility Meter"
    _order = 'unit_id, meter_type'

    unit_id = fields.Many2one('regie.unit', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='unit_id.company_id', store=True, index=True)
    meter_type = fields.Selection(
        [('water', 'Water'), ('gas', 'Gas'), ('electricity', 'Electricity')],
        string="Type", required=True,
    )
    name = fields.Char(string="Meter Number", required=True)
    ean_code = fields.Char(string="EAN Code", help="18-digit EAN code of the delivery point (gas and electricity).")
    notes = fields.Char()

    @api.constrains('ean_code')
    def _check_ean_code(self):
        for meter in self.filtered('ean_code'):
            if not re.fullmatch(r'\d{18}', meter.ean_code.replace(' ', '')):
                raise ValidationError(self.env._("The EAN code %s must contain 18 digits.", meter.ean_code))
