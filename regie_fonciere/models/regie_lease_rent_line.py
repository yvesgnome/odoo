from odoo import fields, models

RENT_CHANGE_REASONS = [
    ('initial', 'Initial Rent'),
    ('indexation', 'Indexation'),
    ('revision', 'Revision'),
    ('amendment', 'Amendment'),
    ('provision_adjustment', 'Charge Provision Adjustment'),
]


class RegieLeaseRentLine(models.Model):
    """ Rent history of a lease: the rent and charge provision in force at a date are those of
    the most recent line whose start date is on or before that date. """
    _name = 'regie.lease.rent.line'
    _description = "Lease Rent History"
    _order = 'lease_id, date_start desc, id desc'

    _lease_date_unique = models.Constraint(
        'unique(lease_id, date_start)',
        "There is already a rent change at this date for this lease.",
    )

    lease_id = fields.Many2one('regie.lease', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='lease_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='lease_id.currency_id')
    date_start = fields.Date(
        string="Effective Date", required=True,
        help="First day from which this rent and this provision apply; they apply until the next line.",
    )
    rent = fields.Monetary(required=True, help="Monthly rent excluding charges.")
    charge_provision = fields.Monetary(
        string="Charge Provision",
        help="Monthly charge provision, or flat-rate charges for leases with flat-rate charges.",
    )
    reason = fields.Selection(
        RENT_CHANGE_REASONS, required=True, default='revision',
        help="Why the rent changed: initial rent, indexation, revision, amendment or provision adjustment.",
    )
    note = fields.Char()
