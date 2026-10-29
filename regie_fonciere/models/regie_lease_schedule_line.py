from odoo import api, fields, models


class RegieLeaseScheduleLine(models.Model):
    """ One line per lease and invoiced month. The unique (lease, period) constraint guarantees that
    a month is never invoiced twice. """
    _name = 'regie.lease.schedule.line'
    _description = "Lease Invoicing Schedule"
    _order = 'lease_id, period_date desc'

    _lease_period_unique = models.Constraint(
        'unique(lease_id, period_date)',
        "This period is already scheduled for this lease.",
    )

    lease_id = fields.Many2one('regie.lease', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='lease_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='lease_id.currency_id')
    partner_id = fields.Many2one(related='lease_id.partner_id')
    building_id = fields.Many2one(related='lease_id.building_id', store=True)
    period_date = fields.Date(string="Period", required=True, help="First day of the invoiced month.")
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    prorata = fields.Float(digits=(6, 4), default=1.0, help="Share of the month invoiced (occupied days / days of the month).")
    rent_amount = fields.Monetary(string="Rent")
    charge_amount = fields.Monetary(string="Charges")
    amount_total = fields.Monetary(string="Total", compute='_compute_amount_total', store=True)
    invoice_id = fields.Many2one('account.move', string="Invoice", copy=False, index='btree_not_null')
    payment_state = fields.Selection(related='invoice_id.payment_state', string="Payment Status")
    state = fields.Selection(
        [('to_invoice', 'To Invoice'), ('invoiced', 'Invoiced'), ('cancelled', 'Cancelled')],
        string="Status", compute='_compute_state', store=True, readonly=False, default='to_invoice',
    )

    @api.depends('rent_amount', 'charge_amount')
    def _compute_amount_total(self):
        for line in self:
            line.amount_total = line.rent_amount + line.charge_amount

    @api.depends('invoice_id.state')
    def _compute_state(self):
        for line in self:
            if line.invoice_id and line.invoice_id.state != 'cancel':
                line.state = 'invoiced'
            elif line.invoice_id:
                line.state = 'cancelled'
            elif line.state != 'cancelled':
                line.state = 'to_invoice'

    @api.depends('lease_id', 'period_date')
    def _compute_display_name(self):
        for line in self:
            line.display_name = "%s – %s" % (line.lease_id.name, line.period_date and line.period_date.strftime('%m/%Y'))
