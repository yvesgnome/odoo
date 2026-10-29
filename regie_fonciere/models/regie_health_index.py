from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..tools import month_start


class RegieHealthIndex(models.Model):
    _name = 'regie.health.index'
    _description = "Health Index"
    _order = 'base_year desc, month desc'

    _month_base_unique = models.Constraint(
        'unique(month, base_year)',
        "There is already a health index for this month and base year.",
    )

    month = fields.Date(required=True, help="First day of the month of the index.")
    base_year = fields.Char(
        required=True, default='2013',
        help="Base year of the series (index 100 = average of that year).",
    )
    value = fields.Float(
        required=True, digits=(10, 2),
        help="Monthly value of the health index published by Statbel.",
    )

    @api.depends('month', 'base_year', 'value')
    def _compute_display_name(self):
        for index in self:
            index.display_name = "%s (%s): %.2f" % (
                index.month and index.month.strftime('%m/%Y'), index.base_year, index.value)

    @api.constrains('month')
    def _check_month(self):
        for index in self:
            if index.month.day != 1:
                raise ValidationError(self.env._("The month of a health index must be the first day of the month."))

    @api.model
    def _get_index(self, month, base_year):
        """ Health index of the month of `month`, or the most recent one before it if that month
        is not published yet. Returns (index record, is_exact). """
        month = month_start(month)
        index = self.search([('base_year', '=', base_year), ('month', '<=', month)], order='month desc', limit=1)
        return index, bool(index) and index.month == month


class RegiePebCorrectionFactor(models.Model):
    """ Brussels EPC correction factor (art. 224/2 of the Brussels Housing Code). """
    _name = 'regie.peb.correction.factor'
    _description = "EPC Correction Factor"
    _order = 'peb_group, month, day_from'

    peb_group = fields.Selection(
        [('e', 'EPC E'), ('fg', 'EPC F or G')], string="EPC Classes", required=True,
        help="EPC classes to which the factor applies.",
    )
    month = fields.Integer(
        string="Anniversary Month", required=True,
        help="Month of the anniversary date of the lease (1 to 12).",
    )
    day_from = fields.Integer(
        string="From Day", required=True, default=1,
        help="First day of the month covered (October is split on the 14th).",
    )
    day_to = fields.Integer(string="To Day", required=True, default=31, help="Last day of the month covered.")
    factor = fields.Float(
        required=True, digits=(12, 9),
        help="Coefficient applied to the indexed rent (art. 224/2 of the Brussels Housing Code).",
    )

    @api.model
    def _get_factor(self, peb_class, anniversary_date):
        """ Factor for a dwelling of `peb_class` and a lease anniversary at `anniversary_date`;
        1.0 for classes without correction. """
        group = {'e': 'e', 'f': 'fg', 'g': 'fg'}.get(peb_class)
        if not group:
            return 1.0
        factor = self.search([
            ('peb_group', '=', group),
            ('month', '=', anniversary_date.month),
            ('day_from', '<=', anniversary_date.day),
            ('day_to', '>=', anniversary_date.day),
        ], limit=1)
        return factor.factor if factor else 1.0
