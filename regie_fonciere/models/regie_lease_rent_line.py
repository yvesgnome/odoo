from odoo import api, fields, models

from ..tools import fmt_amount, fmt_number

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
    explanation = fields.Text(compute='_compute_explanation', help="How this rent was obtained.")

    @api.depends('date_start', 'rent', 'charge_provision', 'reason', 'note')
    @api.depends_context('lang')
    def _compute_explanation(self):
        for line in self:
            line.explanation = line._get_explanation() if line.date_start else False

    def _get_explanation(self):
        """ Text explaining the amount of the line; extended by the indexation and charges zones. """
        self.ensure_one()
        env = self.env
        lease = self.lease_id
        if self.reason == 'initial':
            return env._(
                "Base rent at the signature of the lease: %(rent)s (initial index %(index)s). "
                "Monthly charge provision: %(provision)s.",
                rent=fmt_amount(env, self.rent, self.currency_id),
                index=fmt_number(env, lease.initial_index), provision=fmt_amount(env, self.charge_provision, self.currency_id))
        reasons = dict(self._fields['reason']._description_selection(env))
        text = env._("%(reason)s encoded by hand.", reason=reasons.get(self.reason))
        return "%s %s" % (text, self.note) if self.note else text
