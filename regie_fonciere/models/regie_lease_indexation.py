from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class RegieLease(models.Model):
    _inherit = 'regie.lease'

    indexation_ids = fields.One2many('regie.indexation', 'lease_id', string="Indexations")
    indexation_count = fields.Integer(compute='_compute_indexation_count')
    indexation_blocking_reason = fields.Text(
        compute='_compute_indexation_blocking_reason',
        help="Why the rent cannot be indexed today (Brussels conditions).",
    )

    def _compute_indexation_count(self):
        for lease in self:
            lease.indexation_count = len(lease.indexation_ids)

    def _compute_indexation_blocking_reason(self):
        today = fields.Date.context_today(self)
        for lease in self:
            lease.indexation_blocking_reason = "\n".join(lease._get_indexation_blocking_reasons(today))

    @api.onchange('signature_date')
    def _onchange_signature_date_initial_index(self):
        """ Initial index: index of the month preceding the signature. """
        if self.signature_date and not self.initial_index:
            index, _is_exact = self.env['regie.health.index']._get_index(
                self.signature_date.replace(day=1) - relativedelta(months=1),
                self.company_id.regie_index_base_year)
            self.initial_index = index.value

    def _is_peb_relevant(self):
        """ EPC rules apply to housing leases of dwellings. """
        self.ensure_one()
        return self.is_housing and self.main_unit_id.is_dwelling

    def _get_indexation_blocking_reasons(self, request_date):
        """ Brussels conditions to index the rent at `request_date`; empty list when allowed. """
        self.ensure_one()
        reasons = []
        if not self.is_written:
            reasons.append(self.env._("The lease is not a written lease."))
        if not self.is_registered:
            reasons.append(self.env._("The lease is not registered."))
        if self.indexation_excluded:
            reasons.append(self.env._("The lease contains a clause excluding the indexation."))
        if not self.is_indexable:
            reasons.append(self.env._("The indexation is disabled on this lease."))
        if not self.initial_index:
            reasons.append(self.env._("The initial index of the lease is missing."))
        if self._is_peb_relevant():
            if not self.main_unit_id._is_peb_valid_at(request_date):
                reasons.append(self.env._("The EPC certificate of %s is missing or expired.", self.main_unit_id.name))
            if not self.peb_communicated:
                reasons.append(self.env._("The EPC certificate was not communicated to the tenant."))
        return reasons

    def _get_peb_correction_factor(self, anniversary_date):
        """ Correction factor for housing leases that took effect before the cut-off date
        (14/10/2022) on dwellings of EPC class E, F or G; 1.0 otherwise. """
        self.ensure_one()
        cutoff = self.company_id.regie_peb_correction_cutoff_date
        if not self._is_peb_relevant() or not cutoff or self.start_date >= cutoff:
            return 1.0
        return self.env['regie.peb.correction.factor']._get_factor(self.main_unit_id.peb_class, anniversary_date)

    def _create_indexation(self, anniversary_date):
        """ Create (and compute) the indexation proposal of the anniversary, unless it exists. """
        self.ensure_one()
        indexation = self.indexation_ids.filtered(lambda i: i.anniversary_date == anniversary_date)
        if indexation:
            return indexation
        indexation = self.env['regie.indexation'].create({'lease_id': self.id, 'anniversary_date': anniversary_date})
        indexation._compute_indexation()
        return indexation

    def action_create_indexation(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        reasons = self._get_indexation_blocking_reasons(today)
        if reasons:
            raise UserError(self.env._("The rent of %(lease)s cannot be indexed:\n%(reasons)s",
                                       lease=self.name, reasons="\n".join(reasons)))
        # The last anniversary if it was not indexed yet (late request, limited retroactivity),
        # otherwise the next one.
        next_anniversary = self._get_anniversary_on_or_after(today)
        last_anniversary = next_anniversary - relativedelta(years=1)
        anniversaries = self.indexation_ids.mapped('anniversary_date')
        if last_anniversary >= self.start_date + relativedelta(years=1) and last_anniversary not in anniversaries:
            anniversary = last_anniversary
        else:
            anniversary = next_anniversary
        indexation = self._create_indexation(anniversary)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'regie.indexation',
            'res_id': indexation.id,
            'view_mode': 'form',
        }

    def action_open_indexations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('regie_fonciere.regie_indexation_action')
        action['domain'] = [('lease_id', '=', self.id)]
        action['context'] = {'default_lease_id': self.id}
        return action

    @api.model
    def _cron_create_indexation_proposals(self, today=None):
        """ Create the proposals `regie_indexation_notice_days` days before the anniversary, for the
        leases that meet the indexation conditions. """
        today = today or fields.Date.context_today(self)
        leases = self.search([('state', 'in', self._get_occupied_states()), ('is_indexable', '=', True)])
        for lease in leases:
            anniversary = lease._get_anniversary_on_or_after(today)
            if (anniversary - today).days > lease.company_id.regie_indexation_notice_days:
                continue
            if lease._get_indexation_blocking_reasons(today):
                continue
            lease._create_indexation(anniversary)
