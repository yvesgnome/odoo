from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    regie_lease_id = fields.Many2one(
        'regie.lease', string="Lease", index='btree_not_null', copy=False, check_company=True,
        help="Lease invoiced by this document. Rent invoices are linked automatically; set it on one-off "
             "invoices so that they count in the balance of the lease.",
    )
    regie_building_id = fields.Many2one(
        related='regie_lease_id.building_id', string="Building", store=True, index='btree_not_null',
    )
