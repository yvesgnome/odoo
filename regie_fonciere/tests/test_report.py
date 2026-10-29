import ast
from datetime import date

from freezegun import freeze_time

from odoo.tests import tagged

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestDashboard(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'regie_rent_account_id': cls.company_data['default_account_revenue'].id,
            'regie_charge_account_id': cls.copy_account(cls.company_data['default_account_revenue']).id,
        })

    @freeze_time('2025-02-25')
    def test_dashboard_figures(self):
        lease = self._create_lease(end_date='2025-07-31')
        lease.state = 'active'
        for generation_date in (date(2024, 12, 20), date(2025, 1, 20), date(2025, 2, 20)):
            lease._generate_invoices(generation_date)  # January to March, not paid
        dashboard = self.env['regie.dashboard'].create({})
        self.assertEqual(dashboard.unpaid_amount, 2700.0)
        self.assertEqual(dashboard.overdue_amount, 1800.0)  # January and February are due
        self.assertEqual(dashboard.overdue_tenant_count, 1)
        self.assertEqual(dashboard.unit_count, 3)
        self.assertEqual(dashboard.vacant_unit_count, 2)
        self.assertAlmostEqual(dashboard.occupancy_rate, 100 / 3, places=1)
        self.assertEqual(dashboard.ending_lease_count, 1)
        action = dashboard.action_open_unpaid_tenants()
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(self.env['account.move'].search_count(ast.literal_eval(action['domain'])), 3)
