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
  `_regie_demo_*` methods called from demo XML (`<function>`); keep them idempotent.
- **Demo files are loaded in `noupdate` mode**: on `-u`, existing demo records are not updated
  and demo `<function>` tags are **not executed** (only at install). New demo records are created.
  To check demo changes, uninstall and reinstall the module (see commands).
- After an uninstall, the demo company (it has a chart of accounts) and its partners cannot be
  deleted; their xml ids survive, so a reinstall reuses them. At install,
  `_regie_demo_reset_previous_company` deletes the accounting documents, SEPA mandates and
  follow-up levels left in **the demo company only** by a previous demo, so the reinstall does not
  duplicate them. Building analytic accounts are reused by code (plan *Buildings*).
  (Creating a new demo company on each reinstall was tried and rejected: mail alias conflicts
  with the journals of the old company.) An archived company
  "Régie foncière (démo, archivée …)" may exist in `wb_dev` from that attempt; it is harmless.
- **Windows filestore bug (Odoo core)**: Odoo writes filestore files read-only (`0o444`), Windows
  refuses to delete them, the attachment GC leaves `*.__gc` files and the next GC fails on an
  assertion. `tests/common.py` skips the test GC on Windows. If an Odoo log shows
  `_file_gc could not unlink`, the leftovers (unreferenced by definition) can be removed with
  `find /c/Odoo/20/data/filestore/wb_dev -name "*__gc" -exec chmod u+w {} + -exec rm -f {} +`.

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
   automatically in the analytic plan *Buildings*; unit status computed (free / rented / under works),
   stored, recomputed from the lease states.
2. **Leases** (`regie.lease`, `regie.lease.rent.line`, `regie.charge.category`):
   - one or more units (`unit_ids`) with a main unit; one or more tenants (`tenant_ids`) with a
     main tenant (`partner_id`, the invoiced one), joint liability flag, guarantors.
   - States: draft → signed → active → notice → terminated; rescinded; litigation. A daily cron
     (`_cron_update_states`) activates signed leases on their effective date and terminates
     leases the day after the move-out date. Units are *rented* while a lease is active, in notice
     or in litigation.
   - **Rent history**: every change (initial, indexation, revision, amendment, provision adjustment)
     is a dated line; `_get_rent_at(date)` returns the (rent, provision) in force at a date.
   - Default durations per type in `LEASE_TYPE_DEFAULT_DURATION`, short-term ≤ 36 months
     (`SHORT_TERM_MAX_DURATION`). Housing = all types except commercial and parking.
   - Reference rent mandatory to sign a housing lease.
   - **Structured communication** unique per lease: company prefix (`regie_communication_prefix`,
     default `9`, keeps it apart from Odoo's invoice-based references) + lease id on 10 digits,
     check digits = modulo 97 (97 when 0) — `tools.format_structured_communication`.
   - `invoicing_start_date`: first day invoiced by the schedule (defaults to the effective date;
     used to take over existing leases).
   - Open balance / overdue invoices from `account.move.regie_lease_id`; buttons for a one-off
     invoice or credit note.
   - Lease numbers `BAIL/<year of the effective date>/NNNN`.
3. **Rent invoicing** (`regie.lease.schedule.line`, `models/regie_lease_invoicing.py`):
   - No subscription, no sale order: the lease is the only reference.
   - Company settings (Land Agency settings): generation day (default 20) and month
     (default *previous month*, rent paid in advance), due day (default 1st of the invoiced month),
     rent journal, rent and charge provision income accounts, communication prefix.
   - Schedule line = lease + month (`period_date`), dates, prorata, rent and charge amounts,
     invoice, status. **Unique (lease, period)**: a month is never invoiced twice.
   - `_generate_invoices(today)`: creates the missing lines from `invoicing_start_date` up to the
     last period whose generation date is reached (missed months are **caught up**), then one
     **posted** invoice per line, dated `today`. Daily cron + button *Generate Invoices* on the lease
     + server action on the list (mass).
   - Amounts read in the rent history at the first invoiced day of the month; **prorata per day**
     for the first month (effective date) and the last one (move-out date).
   - Two products (`product_rent`, `product_charge_provision`, no taxes) on the two income
     accounts of the company; building analytic account on every line; taxes only with the VAT
     option of the lease; `payment_reference` = structured communication of the lease.
   - SEPA: `sepa_mandate_id` on the lease (active mandate of the main tenant); while usable, the
     invoices get the *SEPA Direct Debit* preferred payment method of the bank journal.
   - Payment follow-ups: standard `account_followup` levels (demo: 10, 25 and 45 days, no fees).
     `account_followup` is added to the dependencies (not in the initial list) because the
     follow-up levels are a model of that module.
   - Income accounts (Belgian chart, demo company): **700100 Loyers** (class 70, turnover) for the
     rents and **743100 Provisions pour charges locatives** (under 743, miscellaneous operating
     income) for the charge provisions; both created by the demo setup if missing. To be confirmed
     by the agency's accountant (provisions could also be booked on a liability account).
   - Demo payments are posted directly on the bank account (payment account of the manual inbound
     method = bank account): without an outstanding account, Odoo 20 only reconciles payments
     with invoices at bank reconciliation.
