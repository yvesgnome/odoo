from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    regie_communication_prefix = fields.Char(related='company_id.regie_communication_prefix', readonly=False)
    regie_invoice_day = fields.Integer(related='company_id.regie_invoice_day', readonly=False)
    regie_invoice_month_offset = fields.Selection(related='company_id.regie_invoice_month_offset', readonly=False)
    regie_due_day = fields.Integer(related='company_id.regie_due_day', readonly=False)
    regie_rent_journal_id = fields.Many2one(related='company_id.regie_rent_journal_id', readonly=False)
    regie_rent_account_id = fields.Many2one(related='company_id.regie_rent_account_id', readonly=False)
    regie_charge_account_id = fields.Many2one(related='company_id.regie_charge_account_id', readonly=False)
    regie_index_base_year = fields.Char(related='company_id.regie_index_base_year', readonly=False)
    regie_indexation_notice_days = fields.Integer(related='company_id.regie_indexation_notice_days', readonly=False)
    regie_indexation_retroactivity_months = fields.Integer(
        related='company_id.regie_indexation_retroactivity_months', readonly=False)
    regie_peb_correction_cutoff_date = fields.Date(related='company_id.regie_peb_correction_cutoff_date', readonly=False)
