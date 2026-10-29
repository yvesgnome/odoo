from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestBuilding(RegieTestCommon):

    def test_analytic_account_created(self):
        analytic = self.building.analytic_account_id
        self.assertTrue(analytic)
        self.assertEqual(analytic.plan_id, self.env.ref('regie_fonciere.analytic_plan_buildings'))
        self.assertEqual(analytic.company_id, self.company)
        self.building.name = "Renamed Building"
        self.assertEqual(analytic.name, "Renamed Building")

    def test_unit_stats_and_state(self):
        self.assertEqual(self.building.unit_count, 3)
        self.assertEqual(self.building.total_surface, 200.0)
        self.assertEqual(self.unit_a.state, 'free')
        self.unit_a.under_works = True
        self.assertEqual(self.unit_a.state, 'works')
        self.assertEqual(self.building.free_unit_count, 2)

    @freeze_time('2026-01-15')
    def test_peb_validity(self):
        self.unit_a.peb_valid_until = '2026-01-14'
        self.assertFalse(self.unit_a.peb_is_valid)
        self.assertTrue(self.unit_a._is_peb_valid_at(self.unit_a.peb_valid_until))
        expired = self.env['regie.unit'].search([('peb_is_valid', '=', False), ('building_id', '=', self.building.id)])
        self.assertEqual(expired, self.unit_a)

    def test_meter_ean_code(self):
        self.env['regie.meter'].create({
            'unit_id': self.unit_a.id, 'meter_type': 'electricity', 'name': 'M1', 'ean_code': '541448820044123456',
        })
        with self.assertRaises(ValidationError):
            self.env['regie.meter'].create({
                'unit_id': self.unit_a.id, 'meter_type': 'gas', 'name': 'M2', 'ean_code': '5414',
            })
