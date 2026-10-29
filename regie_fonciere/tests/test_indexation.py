from datetime import date

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RegieTestCommon

# Health index base 2013 (Statbel), loaded as module data.
INDEX_2020_08 = 110.20
INDEX_2023_07 = 128.22
INDEX_2025_08 = 135.64
INDEX_2025_09 = 135.26
FACTOR_E_OCT_1_13 = 0.989805521
FACTOR_FG_OCT_14_31 = 0.898895293


@tagged('post_install', '-at_install')
class TestIndexation(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'regie_rent_account_id': cls.company_data['default_account_revenue'].id,
            'regie_charge_account_id': cls.company_data['default_account_revenue'].id,
        })

    def _old_lease(self, unit, start_date, **vals):
        """ Lease signed in September 2020 (initial index: August 2020), before 14/10/2022. """
        lease = self._create_lease(unit=unit, signature_date='2020-09-20', start_date=start_date,
                                   end_date='2029-12-31', base_rent=700.0, initial_index=INDEX_2020_08, **vals)
        lease.state = 'active'
        return lease

    def test_health_index_data(self):
        index, is_exact = self.env['regie.health.index']._get_index(date(2025, 8, 17), '2013')
        self.assertTrue(is_exact)
        self.assertEqual(index.value, INDEX_2025_08)

    def test_normal_indexation(self):
        lease = self._create_lease(signature_date='2023-08-10', start_date='2023-09-01', base_rent=850.0,
                                   initial_index=INDEX_2023_07)
        lease.state = 'active'
        indexation = lease._create_indexation(date(2025, 9, 1))
        self.assertEqual(indexation.new_index_month, date(2025, 8, 1))
        self.assertEqual(indexation.new_index, INDEX_2025_08)
        self.assertEqual(indexation.correction_factor, 1.0)
        self.assertFalse(indexation.index_is_provisional)
        self.assertEqual(indexation.new_rent, round(850.0 * INDEX_2025_08 / INDEX_2023_07, 2))
        self.assertEqual(indexation.new_rent, 899.19)

    def test_correction_factor_epc_e_before_october_14(self):
        lease = self._old_lease(self.unit_c, '2020-10-05')  # EPC E
        indexation = lease._create_indexation(date(2025, 10, 5))
        self.assertEqual(indexation.correction_factor, FACTOR_E_OCT_1_13)
        self.assertEqual(indexation.new_index, INDEX_2025_09)
        self.assertEqual(indexation.new_rent, round(700.0 * INDEX_2025_09 / INDEX_2020_08 * FACTOR_E_OCT_1_13, 2))

    def test_correction_factor_epc_f_after_october_14(self):
        lease = self._old_lease(self.unit_b, '2020-10-20')  # EPC F
        indexation = lease._create_indexation(date(2025, 10, 20))
        self.assertEqual(indexation.correction_factor, FACTOR_FG_OCT_14_31)
        self.assertEqual(indexation.new_rent, round(700.0 * INDEX_2025_09 / INDEX_2020_08 * FACTOR_FG_OCT_14_31, 2))

    def test_correction_factor_epc_g_and_classes(self):
        factors = self.env['regie.peb.correction.factor']
        self.assertEqual(factors._get_factor('g', date(2025, 10, 13)), 0.979611041)
        self.assertEqual(factors._get_factor('e', date(2025, 10, 14)), 0.949447646)
        self.assertEqual(factors._get_factor('f', date(2026, 3, 1)), 0.935992433)
        self.assertEqual(factors._get_factor('d', date(2026, 3, 1)), 1.0)

    def test_no_correction_factor_for_recent_lease(self):
        lease = self._create_lease(unit=self.unit_b, signature_date='2022-10-20', start_date='2022-11-01')
        lease.state = 'active'
        self.assertEqual(lease._get_peb_correction_factor(date(2025, 11, 1)), 1.0)
        commercial = self._create_lease(unit=self.unit_c, lease_type='commercial', start_date='2020-01-01')
        self.assertEqual(commercial._get_peb_correction_factor(date(2025, 1, 1)), 1.0)

    def test_unregistered_lease_blocked(self):
        lease = self._old_lease(self.unit_a, '2020-10-01', registration_date=False)
        reasons = lease._get_indexation_blocking_reasons(date(2025, 9, 1))
        self.assertIn("The lease is not registered.", reasons)
        self.assertTrue(lease.indexation_blocking_reason)
        with self.assertRaises(UserError):
            lease.action_create_indexation()
        self.env['regie.lease']._cron_create_indexation_proposals(date(2025, 9, 1))
        self.assertFalse(lease.indexation_ids)

    def test_expired_peb_blocked(self):
        lease = self._old_lease(self.unit_a, '2020-10-01')
        self.assertFalse(lease._get_indexation_blocking_reasons(date(2025, 9, 1)))
        self.unit_a.peb_valid_until = '2025-08-31'
        reasons = lease._get_indexation_blocking_reasons(date(2025, 9, 1))
        self.assertEqual(len(reasons), 1)
        self.assertIn("EPC certificate", reasons[0])
        # Not communicated to the tenant
        self.unit_a.peb_valid_until = '2035-12-31'
        lease.peb_communicated = False
        self.assertTrue(lease._get_indexation_blocking_reasons(date(2025, 9, 1)))

    def test_retroactivity_limited_to_three_months(self):
        lease = self._old_lease(self.unit_a, '2020-03-01')
        indexation = lease._create_indexation(date(2025, 3, 1))
        self.assertEqual(indexation._get_effective_date(date(2025, 8, 15)), date(2025, 5, 15))
        self.assertEqual(indexation._get_effective_date(date(2025, 4, 10)), date(2025, 3, 1))
        self.company.regie_indexation_retroactivity_months = 1
        self.assertEqual(indexation._get_effective_date(date(2025, 8, 15)), date(2025, 7, 15))

    def test_workflow_apply_and_arrears(self):
        lease = self._create_lease(signature_date='2023-08-10', start_date='2023-09-01', base_rent=850.0,
                                   initial_index=INDEX_2023_07, invoicing_start_date='2025-07-01')
        lease.state = 'active'
        lease._generate_invoices(date(2025, 9, 25))  # July to October invoiced at 850
        indexation = lease._create_indexation(date(2025, 9, 1))
        indexation.action_validate()
        self.assertEqual(indexation.state, 'validated')
        indexation.request_date = date(2025, 9, 25)
        indexation.action_send()
        self.assertEqual(indexation.state, 'sent')
        self.assertTrue(indexation.letter_attachment_id)
        self.assertEqual(indexation.letter_attachment_id.res_model, 'regie.lease')
        self.assertEqual(indexation.effective_date, date(2025, 9, 1))
        indexation.action_apply()
        self.assertEqual(indexation.state, 'applied')
        self.assertEqual(lease._get_rent_at(date(2025, 9, 1))[0], 899.19)
        self.assertEqual(lease._get_rent_at(date(2025, 8, 31))[0], 850.0)
        # September and October were invoiced at 850: arrears = 2 × 49.19
        self.assertEqual(indexation.arrears_invoice_id.amount_total, 98.38)
        # The schedule takes the new rent over
        lease._generate_invoices(date(2025, 10, 20))
        november = lease.schedule_line_ids.filtered(lambda l: l.period_date == date(2025, 11, 1))
        self.assertEqual(november.rent_amount, 899.19)

    def test_letter_before_sending(self):
        lease = self._old_lease(self.unit_b, '2020-10-20')
        indexation = lease._create_indexation(date(2025, 10, 20))
        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'regie_fonciere.action_report_indexation_letter', indexation.ids)
        self.assertIn(lease.structured_communication, html.decode())

    def test_cron_creates_proposals_before_anniversary(self):
        lease = self._old_lease(self.unit_a, '2020-12-01')
        Lease = self.env['regie.lease']
        Lease._cron_create_indexation_proposals(date(2025, 10, 16))  # 46 days before
        self.assertFalse(lease.indexation_ids)
        Lease._cron_create_indexation_proposals(date(2025, 10, 17))  # 45 days before
        self.assertEqual(lease.indexation_ids.anniversary_date, date(2025, 12, 1))
        self.assertEqual(lease.indexation_ids.state, 'to_validate')
        # The index of November 2025 (month preceding the anniversary) is known in the data
        self.assertFalse(lease.indexation_ids.index_is_provisional)
        Lease._cron_create_indexation_proposals(date(2025, 10, 18))
        self.assertEqual(len(lease.indexation_ids), 1)

    @freeze_time('2026-10-29')
    def test_provisional_index(self):
        lease = self._old_lease(self.unit_a, '2020-01-01')
        indexation = lease._create_indexation(date(2027, 1, 1))  # needs December 2026, not published
        self.assertTrue(indexation.index_is_provisional)
        self.assertEqual(indexation.new_index_month, date(2026, 10, 1))

    def test_validation_reserved_to_supervisor(self):
        lease = self._old_lease(self.unit_a, '2020-10-01')
        indexation = lease._create_indexation(date(2025, 10, 1))
        self.env.user.group_ids -= self.env.ref('regie_fonciere.group_regie_supervisor')
        self.env.user.group_ids += self.env.ref('regie_fonciere.group_regie_property_manager')
        with self.assertRaises(UserError):
            indexation.action_validate()
