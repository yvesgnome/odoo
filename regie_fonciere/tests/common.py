from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class RegieTestCommon(AccountTestInvoicingCommon):

    @classmethod
    def get_default_groups(cls):
        return super().get_default_groups() | cls.env.ref('regie_fonciere.group_regie_supervisor')

    @classmethod
    @AccountTestInvoicingCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.building = cls.env['regie.building'].create({
            'name': "Test Building",
            'code': "TST",
            'street': "Rue du Test 1",
            'zip': '1000',
            'city': "Bruxelles",
            'municipality': 'brussels',
        })
        cls.unit_a, cls.unit_b, cls.unit_c = cls.env['regie.unit'].create([
            {
                'building_id': cls.building.id,
                'name': 'A',
                'unit_type': 'apartment',
                'surface': 60.0,
                'peb_class': 'c',
                'peb_certificate_number': 'PEB-A',
                'peb_valid_until': '2035-12-31',
            },
            {
                'building_id': cls.building.id,
                'name': 'B',
                'unit_type': 'apartment',
                'surface': 40.0,
                'peb_class': 'f',
                'peb_certificate_number': 'PEB-B',
                'peb_valid_until': '2035-12-31',
            },
            {
                'building_id': cls.building.id,
                'name': 'C',
                'unit_type': 'apartment',
                'surface': 100.0,
                'peb_class': 'e',
                'peb_certificate_number': 'PEB-C',
                'peb_valid_until': '2035-12-31',
            },
        ])
