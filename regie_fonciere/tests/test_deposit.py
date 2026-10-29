from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestDeposit(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'regie_rent_account_id': cls.company_data['default_account_revenue'].id,
            'regie_charge_account_id': cls.copy_account(cls.company_data['default_account_revenue']).id,
        })
        cls.lease = cls._create_lease()  # rent 800, charges 100
        cls.lease.state = 'active'

    def _create_deposit(self, lease=None, **vals):
        return self.env['regie.deposit'].create({
            'lease_id': (lease or self.lease).id,
            'date': '2024-12-15',
            'amount': 1600.0,
            **vals,
        })

    def test_cap_warning_housing_lease(self):
        deposit = self._create_deposit()
        self.assertEqual(deposit.partner_id, self.tenant)
        self.assertEqual(deposit.cap_amount, 1600.0)  # 2 months of rent excluding charges
        self.assertFalse(deposit.exceeds_cap)
        deposit.amount = 1600.01
        self.assertTrue(deposit.exceeds_cap)
        # Only a warning: the deposit can be constituted
        deposit.action_mark_constituted()
        self.assertEqual(deposit.state, 'constituted')
        self.assertEqual(deposit.constituted_amount, 1600.01)
        # The cap is a company setting
        self.company.regie_deposit_cap_months = 3
        deposit.invalidate_recordset(['cap_amount', 'exceeds_cap'])
        self.assertFalse(deposit.exceeds_cap)

    def test_no_cap_for_commercial_lease(self):
        shop = self.env['regie.unit'].create({'building_id': self.building.id, 'name': 'SHOP', 'unit_type': 'retail'})
        lease = self._create_lease(unit=shop, lease_type='commercial')
        deposit = self._create_deposit(lease=lease, amount=10000.0)
        self.assertFalse(deposit.cap_amount)
        self.assertFalse(deposit.exceeds_cap)

    def test_partial_constitution(self):
        deposit = self._create_deposit(constituted_amount=600.0)
        deposit.action_mark_constituted()
        self.assertEqual(deposit.state, 'partial')

    def test_release_with_retentions_and_reminders(self):
        self.lease._generate_invoices(date(2025, 2, 25))  # January to March invoiced, unpaid
        deposit = self._create_deposit(constituted_amount=1600.0)
        deposit.action_mark_constituted()
        with self.assertRaises(UserError):
            deposit.action_request_release()  # no move-out date yet
        self.lease.write({'exit_date': date(2025, 3, 31), 'state': 'terminated'})
        deposit.action_compute_retentions()
        self.assertEqual(deposit.unpaid_rent_amount, 2400.0)
        self.assertEqual(deposit.unpaid_charges_amount, 300.0)
        deposit.damage_amount = 50.0
        self.assertEqual(deposit.retained_amount, 1600.0)  # capped at the constituted amount
        self.assertEqual(deposit.released_amount, 0.0)

        deposit.write({'unpaid_rent_amount': 0.0, 'unpaid_charges_amount': 100.0})
        self.assertEqual(deposit.retained_amount, 150.0)
        self.assertEqual(deposit.released_amount, 1450.0)
        deposit.action_request_release()
        self.assertEqual(deposit.state, 'release_requested')
        self.assertEqual(sorted(deposit.activity_ids.mapped('date_deadline')),
                         [date(2025, 4, 30), date(2025, 5, 20)])  # move-out + 30 and + 50 days
        deposit.action_release()
        self.assertEqual(deposit.state, 'released')
        self.assertFalse(deposit.activity_ids)
