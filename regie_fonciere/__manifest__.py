{
    'name': "Régie foncière",
    'summary': "Rental management for a Brussels municipal land agency (régie foncière)",
    'description': """
Rental management for a public municipal real estate operator in Brussels
that rents out its own properties: buildings and units, leases, monthly rent
invoicing schedule, health-index indexation (with the Brussels EPC correction
factor), rental deposits and recoverable charges statements.
    """,
    'version': '20.0.1.0.0',
    'category': 'Real Estate',
    'author': "Yves Randoux",
    'license': 'LGPL-3',
    'depends': [
        'contacts',
        'account_accountant',
        'l10n_be',
        'account_sepa_direct_debit',
        'mail',
    ],
    'data': [
        'security/regie_security.xml',
        'security/ir.access.csv',
        'data/regie_analytic_data.xml',
        'views/regie_building_views.xml',
        'views/regie_unit_views.xml',
        'views/regie_menus.xml',
    ],
    'demo': [
        'demo/regie_company_demo.xml',
        'demo/regie_building_demo.xml',
    ],
    'application': True,
    'installable': True,
}
