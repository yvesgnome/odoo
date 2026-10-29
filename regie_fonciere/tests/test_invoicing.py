from datetime import date

from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestInvoicing(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rent_account = cls.company_data['default_account_revenue']
        cls.charge_account = cls.copy_account(cls.rent_account)
        cls.company.write({
            'regie_rent_account_id': cls.rent_account.id,
            'regie_charge_account_id': cls.charge_account.id,
            'regie_invoice_day': 20,
            'regie_invoice_month_offset': 'previous',
            'regie_due_day': 1,
        })
        cls.lease = cls._create_lease()
        cls.lease.state = 'active'

    def _invoiced_periods(self, lease):
        return sorted(lease.schedule_line_ids.filtered('invoice_id').mapped('period_date'))

    def test_monthly_generation_without_duplicate(self):
        invoices = self.lease._generate_invoices(date(2025, 1, 19))
        self.assertEqual(self._invoiced_periods(self.lease), [date(2025, 1, 1)])
        self.assertEqual(len(invoices), 1)
        # Same day again: nothing new
        self.assertFalse(self.lease._generate_invoices(date(2025, 1, 19)))
        # The 20th: the next month (rent paid in advance) is invoiced
        invoices = self.lease._generate_invoices(date(2025, 1, 20))
        self.assertEqual(self._invoiced_periods(self.lease), [date(2025, 1, 1), date(2025, 2, 1)])

        invoice = invoices
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(invoice.partner_id, self.tenant)
        self.assertEqual(invoice.invoice_date, date(2025, 1, 20))
        self.assertEqual(invoice.invoice_date_due, date(2025, 2, 1))
        self.assertEqual(invoice.payment_reference, self.lease.structured_communication)
        self.assertEqual(invoice.regie_lease_id, self.lease)
        self.assertEqual(invoice.amount_total, 900.0)
        rent_line = invoice.invoice_line_ids.filtered(lambda l: l.product_id == self.env.ref('regie_fonciere.product_rent'))
        charge_line = invoice.invoice_line_ids - rent_line
        self.assertEqual((rent_line.price_unit, rent_line.account_id), (800.0, self.rent_account))
        self.assertEqual((charge_line.price_unit, charge_line.account_id), (100.0, self.charge_account))
        self.assertFalse(invoice.invoice_line_ids.tax_ids)
        analytic_key = str(self.building.analytic_account_id.id)
        for line in invoice.invoice_line_ids:
            self.assertEqual(line.analytic_distribution, {analytic_key: 100.0})

    def test_missed_months_are_caught_up(self):
        self.lease._generate_invoices(date(2025, 1, 19))
        # The cron did not run between January and late April
        invoices = self.lease._generate_invoices(date(2025, 4, 25))
        self.assertEqual(len(invoices), 4)
        self.assertEqual(self._invoiced_periods(self.lease), [date(2025, m, 1) for m in range(1, 6)])
        self.assertEqual(len(self.lease.invoice_ids), 5)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.env['regie.lease.schedule.line'].create({
                'lease_id': self.lease.id, 'period_date': date(2025, 3, 1),
                'date_from': date(2025, 3, 1), 'date_to': date(2025, 3, 31),
            })
            self.env.flush_all()

    def test_rent_change_during_the_year(self):
        self.env['regie.lease.rent.line'].create({
            'lease_id': self.lease.id, 'date_start': date(2025, 3, 1),
            'rent': 900.0, 'charge_provision': 120.0, 'reason': 'amendment',
        })
        self.lease._generate_invoices(date(2025, 3, 20))
        amounts = {
            line.period_date.month: (line.rent_amount, line.charge_amount)
            for line in self.lease.schedule_line_ids
        }
        self.assertEqual(amounts[2], (800.0, 100.0))
        self.assertEqual(amounts[3], (900.0, 120.0))
        self.assertEqual(amounts[4], (900.0, 120.0))

    def test_prorata_entry_and_exit(self):
        lease = self._create_lease(unit=self.unit_b, start_date='2025-01-16', base_rent=620.0, initial_charge_provision=62.0)
        lease.state = 'active'
        lease._generate_invoices(date(2025, 1, 31))
        january = lease.schedule_line_ids.filtered(lambda l: l.period_date == date(2025, 1, 1))
        self.assertEqual(january.date_from, date(2025, 1, 16))
        self.assertAlmostEqual(january.prorata, 16 / 31, places=4)
        self.assertEqual(january.rent_amount, 320.0)
        self.assertEqual(january.charge_amount, 32.0)
        self.assertIn("16/01/2025", january.invoice_id.invoice_line_ids[0].name)
        self.assertIn("16/31", january.explanation)
        self.assertIn("16/31", str(january.invoice_id.narration))

        lease.write({'exit_date': date(2025, 3, 10), 'state': 'terminated'})
        lease._generate_invoices(date(2025, 6, 1))
        self.assertEqual(self._invoiced_periods(lease), [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)])
        march = lease.schedule_line_ids.sorted('period_date')[-1]
        self.assertEqual(march.date_to, date(2025, 3, 10))
        self.assertEqual(march.rent_amount, 200.0)

    def test_vat_option_on_commercial_lease(self):
        shop = self.env['regie.unit'].create({'building_id': self.building.id, 'name': 'SHOP', 'unit_type': 'retail'})
        lease = self._create_lease(unit=shop, lease_type='commercial', reference_rent=0.0,
                                   vat_option=True, tax_ids=[(6, 0, self.tax_sale_a.ids)])
        lease.state = 'active'
        invoice = lease._generate_invoices(date(2025, 1, 5))
        self.assertEqual(invoice.invoice_line_ids.tax_ids, self.tax_sale_a)
        self.assertGreater(invoice.amount_tax, 0)

    def test_cron_and_settings(self):
        self.company.regie_invoice_month_offset = 'current'
        self.company.regie_invoice_day = 1
        self.company.regie_due_day = 10
        invoice = self.lease._generate_invoices(date(2025, 1, 1))
        self.assertEqual(invoice.invoice_date_due, date(2025, 1, 10))
        self.assertEqual(self._invoiced_periods(self.lease), [date(2025, 1, 1)])
