from datetime import date

from freezegun import freeze_time

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.regie_fonciere.tools import format_structured_communication, is_valid_structured_communication

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestLease(RegieTestCommon):

    def test_structured_communication_format(self):
        # Reference example from the Belgian banking standard: 000/0000/654 72
        self.assertEqual(format_structured_communication(654), '+++000/0000/65472+++')
        self.assertTrue(is_valid_structured_communication('+++000/0000/65472+++'))
        self.assertFalse(is_valid_structured_communication('+++000/0000/65473+++'))
        self.assertFalse(is_valid_structured_communication('000/0000/65472'))
        # A base multiple of 97 gets 97 as check digits
        self.assertEqual(format_structured_communication(97), '+++000/0000/09797+++')

    def test_structured_communication_unique_per_lease(self):
        lease_1 = self._create_lease()
        lease_2 = self._create_lease(unit=self.unit_b)
        for lease in lease_1 | lease_2:
            self.assertTrue(is_valid_structured_communication(lease.structured_communication))
        self.assertNotEqual(lease_1.structured_communication, lease_2.structured_communication)
        self.assertTrue(lease_1.structured_communication.startswith('+++9'))

    def test_rent_history(self):
        lease = self._create_lease()
        self.assertEqual(len(lease.rent_line_ids), 1)
        self.assertEqual(lease.rent_line_ids.reason, 'initial')
        self.env['regie.lease.rent.line'].create({
            'lease_id': lease.id, 'date_start': '2025-07-01', 'rent': 820.0, 'charge_provision': 110.0,
        })
        self.assertEqual(lease._get_rent_at(date(2024, 12, 31)), (0.0, 0.0))
        self.assertEqual(lease._get_rent_at(date(2025, 6, 30)), (800.0, 100.0))
        self.assertEqual(lease._get_rent_at(date(2025, 7, 1)), (820.0, 110.0))

    def test_units_tenants_and_main_unit(self):
        lease = self._create_lease(unit_ids=[(4, self.unit_b.id)], tenant_ids=[(4, self.tenant_2.id)])
        self.assertEqual(lease.unit_ids, self.unit_a | self.unit_b)
        self.assertEqual(lease.tenant_ids, self.tenant | self.tenant_2)
        self.assertEqual(lease.building_id, self.building)
        with self.assertRaises(ValidationError):
            lease.unit_ids = [(3, self.unit_a.id)]

    def test_lifecycle_and_unit_status(self):
        lease = self._create_lease(reference_rent=0.0)
        with self.assertRaises(UserError):
            lease.action_sign()
        lease.reference_rent = 850.0
        with freeze_time('2024-12-20'):
            lease.action_sign()
        self.assertEqual(lease.state, 'signed')
        self.assertEqual(self.unit_a.state, 'free')
        lease._update_state_from_dates(date(2025, 1, 1))
        self.assertEqual(lease.state, 'active')
        self.assertEqual(self.unit_a.state, 'rented')
        self.assertEqual(self.unit_a.current_lease_id, lease)
        lease.action_give_notice()
        lease.exit_date = '2025-06-15'
        lease._update_state_from_dates(date(2025, 6, 15))
        self.assertEqual(lease.state, 'notice')
        lease._update_state_from_dates(date(2025, 6, 16))
        self.assertEqual(lease.state, 'terminated')
        self.assertEqual(self.unit_a.state, 'free')

    def test_short_term_max_duration(self):
        with self.assertRaises(ValidationError):
            self._create_lease(lease_type='short_term', end_date='2028-01-01')
        lease = self._create_lease(lease_type='short_term', end_date='2027-12-31')
        self.assertEqual(lease.duration_months, 36)

    def test_anniversary(self):
        lease = self._create_lease(start_date='2020-03-15', end_date='2029-03-14')
        self.assertEqual(lease._get_anniversary_on_or_after(date(2026, 3, 15)), date(2026, 3, 15))
        self.assertEqual(lease._get_anniversary_on_or_after(date(2026, 3, 16)), date(2027, 3, 15))
        self.assertEqual(lease._get_anniversary_on_or_after(date(2020, 3, 15)), date(2021, 3, 15))
