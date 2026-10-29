# regie_fonciere – working notes

Custom Odoo 20 Enterprise module for a Brussels municipal land agency (*régie foncière*)
renting out **its own** properties (no third-party owners, no owner accounts, no payouts).
First draft = demo for the agency; business rules are working assumptions, kept configurable.

## Local environment (discovered)

| Item | Value |
| --- | --- |
| Odoo source (community + enterprise merged) | `C:\Odoo\20\odoo\odoo\addons` (base: `C:\Odoo\20\odoo\odoo\addons\base`) |
| Odoo launcher | `C:\Odoo\20\odoo-bin` |
| Python venv | `C:\Odoo\20\venv\Scripts\python.exe` |
| Config file | `C:\Odoo\20\wb.conf` (addons_path includes `C:\Odoo\wb\odoo.20`, port 8070, `dbfilter=^wb_.*`) |
| Local database | `wb_dev` (demo data loaded) — **the only database to use** |
| PostgreSQL | localhost, user `odoo` / `odoo`, `C:\Program Files\PostgreSQL\17\bin\psql.exe` |
| Custom addons repo | `C:\Odoo\wb\odoo.20` (git, branch `main`) |
| VS Code helpers | `C:\Odoo\wb\settings\.vscode\run_odoo*.bat` |

Never use a remote database, Odoo.sh, staging or production. Never `git push`.

### Commands (run from `C:\Odoo\20`)

Git Bash rewrites arguments starting with `/` (e.g. `/regie_fonciere`) into Windows paths:
prefix test commands with `MSYS_NO_PATHCONV=1` in Git Bash (not needed in PowerShell/cmd).

```bash
# install (first time)
venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev -i regie_fonciere --stop-after-init

# update
venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev -u regie_fonciere --stop-after-init

# update + tests of this module only
MSYS_NO_PATHCONV=1 venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev -u regie_fonciere \
    --test-tags /regie_fonciere --stop-after-init --log-level=test

# reinstall from scratch (drops the module data, then installs again with demo)
venv/Scripts/python.exe odoo-bin module uninstall -c wb.conf -d wb_dev regie_fonciere
venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev -i regie_fonciere --stop-after-init

# export translations (template / French / Dutch)
venv/Scripts/python.exe odoo-bin i18n export -c wb.conf -d wb_dev -l pot -o ../wb/odoo.20/regie_fonciere/i18n/regie_fonciere.pot regie_fonciere

# run the server
venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev --dev=xml
```

Warnings that are **not** ours and can be ignored: `rag_odoo_mcp_server has an incompatible version`,
missing `pdfminer.six`, missing `markdown2`.

## Odoo 20 conventions verified in the source

- Access rights: **`security/ir.access.csv`** (model `ir.access`): columns
  `id,name,model_id,group_id/id,operation,domain`; `model_id` is the **model name**
  (e.g. `regie.lease`), `operation` is a subset of `crud`.
  **There is no `ir.rule` any more**: multi-company/record rules are `ir.access` rows with an
  empty group (= restriction) and a `domain`, e.g. `"[('company_id', 'in', company_ids)]"`.
- Groups: `res.groups` with `privilege_id` → `res.groups.privilege` (which has `category_id`);
  the field for users is `user_ids` (not `users`), for groups of a user `group_ids`.
- SQL constraints / indexes: class attributes `models.Constraint('unique(...)', msg)`,
  `models.Index(...)` (no `_sql_constraints`).
- Translations in Python: `self.env._("text %s", arg)`.
- Views: `<list>`, `invisible="expr"` / `readonly="expr"` / `required="expr"` (no `attrs`),
  `<chatter/>`, settings view with `<app>/<block>/<setting>`.
- Boolean search methods receive `operator == 'in'` (return `NotImplemented` otherwise).
- Crons: `ir.cron` fields `interval_number`, `interval_type`, `nextcall`, `code`, `model_id`
  (no `numbercall`).
- Direct debit: model `account.direct.debit.mandate` (module `account_direct_debit`,
  `mandate_type = 'sepa'` added by `account_sepa_direct_debit`),
  `account.move._get_usable_mandate()`.
- Belgian structured communication: journal `invoice_reference_model = 'be'`; an explicitly set
  `payment_reference` on an invoice is kept at posting.
- Chart of accounts on the demo company: `account.chart.template._load('be_comp', company, install_demo=False)`
  (`try_loading` logs a warning when called while the registry is loading).
- Tests: `AccountTestInvoicingCommon` + `@AccountTestInvoicingCommon.setup_country('be')` on
  `setUpClass` creates an independent Belgian company with `be_comp`; the test user gets the
  groups of `get_default_groups()` (overridden in `tests/common.py` to add our Supervisor group).

## Module conventions

- Code, field names, comments: **English**. UI tested in French; `i18n/fr.po` complete,
  `i18n/nl.po` prepared (Dutch translations to be completed later).
- Model prefix `regie.`; XML ids prefixed by model (`regie_lease_view_form`...); demo XML ids `demo_*`.
- No `x_` fields (no Studio), no dependency on `sale_subscription`, `documents`, `sign`,
  `industry_real_estate`.
- Every main record has the chatter (`mail.thread` + `mail.activity.mixin`).
- Every model has a `company_id` (stored, related when derived) and a multi-company `ir.access`
  restriction row.
- Business values (deadlines, caps, days, factors) are **company settings or data tables**, never
  hard-coded in the logic.
- Demo data that needs code (generated invoices, computed statements) is produced by
  `_regie_demo_*` methods called from demo XML (`<function>`); they must be **idempotent**
  because `<function>` tags run again on every module update.

## Security groups

| Group (xml id) | FR label | Scope |
| --- | --- | --- |
| `group_regie_property_manager` | Gestionnaire | buildings, units, leases, deposits, indexation proposals |
| `group_regie_accountant` | Comptable | invoicing, charges, charge statements (implies *Invoicing*) |
| `group_regie_supervisor` | Responsable | validations, configuration; implies both groups above |

Future household income data (income-based rents, out of scope) must be restricted to
`group_regie_supervisor` (field-level `groups=` attribute + dedicated model access).

## Zones

1. **Properties** (`regie.building`, `regie.unit`, `regie.meter`): building analytic account created
   automatically in the analytic plan *Buildings*; unit status computed (free / rented / under works).
