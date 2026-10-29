from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged

from .common import RegieTestCommon


@tagged('post_install', '-at_install')
class TestSecurity(RegieTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'regie_rent_account_id': cls.company_data['default_account_revenue'].id,
            'regie_charge_account_id': cls.copy_account(cls.company_data['default_account_revenue']).id,
        })
        cls.manager_user = new_test_user(
            cls.env, login='regie_manager', groups='regie_fonciere.group_regie_property_manager',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.accountant_user = new_test_user(
            cls.env, login='regie_accountant', groups='regie_fonciere.group_regie_accountant',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.lease = cls._create_lease(signature_date='2023-08-10', start_date='2023-09-01', initial_index=128.22)
        cls.lease.state = 'active'
        cls.lease._generate_invoices(date(2025, 9, 25))

    def test_property_manager(self):
        env = self.env(user=self.manager_user)
        building = env['regie.building'].create({'name': "Building PM"})
        unit = env['regie.unit'].create({'building_id': building.id, 'name': 'U1'})
        lease = env['regie.lease'].create({
            'main_unit_id': unit.id, 'partner_id': self.tenant.id, 'start_date': '2025-01-01', 'base_rent': 500.0,
        })
        env['regie.deposit'].create({'lease_id': lease.id, 'amount': 1000.0})
        # The lease form (open balance, invoices...) opens without access error
        with Form(self.lease.with_user(self.manager_user)) as lease_form:
            self.assertEqual(lease_form.open_balance, self.lease.open_balance)
        # Indexation proposals: yes; validation: supervisor only
        indexation = self.lease.with_user(self.manager_user)._create_indexation(date(2025, 9, 1))
        with self.assertRaises(UserError):
            indexation.action_validate()
        Form(indexation)
        # No invoicing, no charge statements
        with self.assertRaises(AccessError):
            env['account.move'].search([('regie_lease_id', '=', self.lease.id)])
        with self.assertRaises(AccessError):
            env['regie.charge.statement'].create({'building_id': self.building.id, 'year': 2025})
        with self.assertRaises(AccessError):
            env['regie.health.index'].create({'month': '2030-01-01', 'value': 150.0})

    def test_accountant(self):
        env = self.env(user=self.accountant_user)
        with self.assertRaises(AccessError):
            env['regie.lease'].create({
                'main_unit_id': self.unit_b.id, 'partner_id': self.tenant.id, 'start_date': '2025-01-01',
                'base_rent': 500.0,
            })
        lease = self.lease.with_user(self.accountant_user)
        self.assertTrue(lease._generate_invoices(date(2025, 10, 20)))
        statement = env['regie.charge.statement'].create({'building_id': self.building.id, 'year': 2025})
        statement.action_compute()
        with self.assertRaises(AccessError):
            env['regie.deposit'].create({'lease_id': self.lease.id, 'amount': 1000.0})

    def test_multi_company(self):
        other_company = self.env['res.company'].create({'name': "Other Agency"})
        other_building = self.env['regie.building'].with_company(other_company).create({
            'name': "Other Building", 'company_id': other_company.id,
        })
        self.manager_user.company_ids = [Command.link(other_company.id)]
        env = self.env(user=self.manager_user, context={'allowed_company_ids': self.company.ids})
        self.assertNotIn(other_building, env['regie.building'].search([]))
        self.assertIn(self.building, env['regie.building'].search([]))
        env = self.env(user=self.manager_user, context={'allowed_company_ids': other_company.ids})
        self.assertEqual(env['regie.building'].search([]), other_building)
