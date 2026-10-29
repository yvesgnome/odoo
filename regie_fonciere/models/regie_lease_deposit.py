from odoo import fields, models


class RegieLease(models.Model):
    _inherit = 'regie.lease'

    deposit_ids = fields.One2many('regie.deposit', 'lease_id', string="Deposits")
    deposit_count = fields.Integer(compute='_compute_deposit_count')

    def _compute_deposit_count(self):
        for lease in self:
            lease.deposit_count = len(lease.deposit_ids)

    def action_open_deposits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('regie_fonciere.regie_deposit_action')
        action['domain'] = [('lease_id', '=', self.id)]
        action['context'] = {'default_lease_id': self.id}
        if len(self.deposit_ids) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': self.deposit_ids.id})
        return action
