from datetime import date

from odoo.tests import tagged

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestChargeStatement(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'regie_rent_account_id': cls.company_data['default_account_revenue'].id,
            'regie_charge_account_id': cls.copy_account(cls.company_data['default_account_revenue']).id,
        })
        cls.heating = cls.env.ref('regie_fonciere.charge_category_heating')
        cls.cleaning = cls.env.ref('regie_fonciere.charge_category_cleaning')
        # Unit A (60 m²) rented all year, B (40 m²) left on 30/06, C (100 m²) vacant.
        cls.lease_a = cls._create_lease(unit=cls.unit_a, charge_category_ids=[(6, 0, cls.heating.ids)])
        cls.lease_b = cls._create_lease(
            unit=cls.unit_b, partner_id=cls.tenant_2.id, initial_charge_provision=50.0,
            charge_category_ids=[(6, 0, (cls.heating | cls.cleaning).ids)])
        cls.lease_a.state = 'active'
        cls.lease_b.write({'state': 'active'})
        (cls.lease_a | cls.lease_b)._generate_invoices(date(2025, 6, 1))
        cls.lease_b.write({'exit_date': date(2025, 6, 30), 'state': 'terminated'})
        (cls.lease_a | cls.lease_b)._generate_invoices(date(2025, 12, 31))
        cls.supplier = cls.env['res.partner'].create({'name': "Supplier"})

    def _create_bill(self, category, amount, bill_date='2025-11-30', analytic_percentage=100.0):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.supplier.id,
            'invoice_date': bill_date,
            'invoice_line_ids': [(0, 0, {
                'name': category.name,
                'account_id': self.company_data['default_account_expense'].id,
                'quantity': 1.0,
                'price_unit': amount,
                'tax_ids': [(6, 0, [])],
                'analytic_distribution': {str(self.building.analytic_account_id.id): analytic_percentage},
                'regie_charge_category_id': category.id,
            })],
        })
        bill.action_post()
        return bill

    def _statement(self):
        statement = self.env['regie.charge.statement'].create({'building_id': self.building.id, 'year': 2025})
        statement.action_compute()
        return statement

    def _result(self, statement, lease):
        return statement.lease_line_ids.filtered(lambda l: l.lease_id == lease)

    def test_allocation_with_vacant_unit_and_departure(self):
        self._create_bill(self.heating, 2000.0)
        self._create_bill(self.heating, 1000.0, bill_date='2024-12-31')  # other year: ignored
        statement = self._statement()
        self.assertEqual(statement.total_cost, 2000.0)
        # Surface split (default): A 60/200, B 40/200, C 100/200 (vacant)
        result_a, result_b = self._result(statement, self.lease_a), self._result(statement, self.lease_b)
        self.assertEqual(result_a.actual_amount, 600.0)
        self.assertEqual(result_b.actual_amount, round(400.0 * 181 / 365, 2))  # 01/01 → 30/06
        self.assertAlmostEqual(statement.total_agency, 2000.0 - 600.0 - result_b.actual_amount, places=2)
        # Provisions called: A 12 × 100, B 6 × 50
        self.assertEqual(result_a.provisions_amount, 1200.0)
        self.assertEqual(result_b.provisions_amount, 300.0)
        self.assertEqual(result_a.balance, -600.0)

    def test_category_not_provided_by_the_lease(self):
        self._create_bill(self.cleaning, 900.0)
        statement = self._statement()
        # Lease A does not provide cleaning: its share is borne by the agency
        self.assertFalse(self._result(statement, self.lease_a).actual_amount)
        self.assertEqual(self._result(statement, self.lease_b).actual_amount, round(180.0 * 181 / 365, 2))

    def test_allocation_keys(self):
        self._create_bill(self.heating, 1000.0)
        key = self.env['regie.allocation.key'].create({
            'building_id': self.building.id, 'category_id': self.heating.id, 'method': 'equal',
        })
        statement = self._statement()
        self.assertEqual(self._result(statement, self.lease_a).actual_amount, round(1000.0 / 3, 2))
        key.write({'method': 'shares', 'line_ids': [
            (0, 0, {'unit_id': self.unit_a.id, 'shares': 3}),
            (0, 0, {'unit_id': self.unit_b.id, 'shares': 1}),
        ]})
        statement.action_compute()
        self.assertEqual(self._result(statement, self.lease_a).actual_amount, 750.0)
        key.method = 'consumption'
        self.env['regie.consumption.reading'].create([
            {'unit_id': self.unit_a.id, 'category_id': self.heating.id, 'date_from': '2025-01-01',
             'date_to': '2025-12-31', 'quantity': 400},
            {'unit_id': self.unit_c.id, 'category_id': self.heating.id, 'date_from': '2025-01-01',
             'date_to': '2025-12-31', 'quantity': 600},
        ])
        statement.action_compute()
        self.assertEqual(self._result(statement, self.lease_a).actual_amount, 400.0)

    def test_analytic_share_of_the_building(self):
        self._create_bill(self.heating, 2000.0, analytic_percentage=50.0)
        statement = self._statement()
        self.assertEqual(statement.total_cost, 1000.0)

    def test_regularisation_moves_and_provision_adjustment(self):
        self._create_bill(self.heating, 2000.0)
        self._create_bill(self.cleaning, 3000.0)
        statement = self._statement()
        result_a, result_b = self._result(statement, self.lease_a), self._result(statement, self.lease_b)
        statement.action_generate_invoices()
        self.assertEqual(statement.state, 'invoiced')
        # A: 600 - 1200 → credit note; B: 198.36 + 297.53 - 300 → invoice
        self.assertEqual(result_a.invoice_id.move_type, 'out_refund')
        self.assertEqual(result_a.invoice_id.amount_total, 600.0)
        self.assertEqual(result_b.invoice_id.move_type, 'out_invoice')
        self.assertEqual(result_b.invoice_id.amount_total, round(result_b.balance, 2))
        self.assertEqual(result_b.invoice_id.state, 'posted')
        self.assertEqual((result_b.invoice_id.invoice_date_due - result_b.invoice_id.invoice_date).days, 30)
        # Monthly provision proposed from the actual share of a full year
        self.assertEqual(result_a.proposed_provision, 50.0)
        result_a.action_apply_provision()
        self.assertEqual(result_a.provision_rent_line_id.charge_provision, 50.0)
        self.assertEqual(result_a.provision_rent_line_id.rent, 800.0)
        self.assertEqual(result_a.provision_rent_line_id.reason, 'provision_adjustment')
