from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------
    # DEMO
    # ------------------------------------------------------------

    @api.model
    def _regie_demo_setup_company(self):
        """ Demo: load the Belgian chart of accounts on the demo company and give
        the administrator access to it. Idempotent (called again on each update). """
        company = self.env.ref('regie_fonciere.demo_company', raise_if_not_found=False)
        if not company:
            return
        if not company.chart_template:
            # _load() rather than try_loading(): the latter warns when the registry is not fully
            # loaded unless the chart's own demo (sample invoices) is installed, which we don't want.
            self.env['account.chart.template']._load('be_comp', company, install_demo=False)
        for user in (self.env.ref('base.user_admin'), self.env.ref('base.user_root')):
            if company not in user.company_ids:
                user.company_ids = [(4, company.id)]
