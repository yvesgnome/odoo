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

Rights per model (`security/ir.access.csv`):
- Property Manager: CRUD buildings, units, meters, leases, rent history, deposits, indexation
  proposals, consumption readings; read schedule, allocation keys and charge statements. No
  access to invoices (lease balance and overdue count are computed with `sudo` and visible to all).
- Accountant: CRUD schedule, allocation keys, charge statements; read buildings, units, leases,
  deposits, indexations. Implies *Invoicing* (posts the rent invoices).
- Supervisor: both + validation and application of indexations and provision adjustments
  (checked in code), CRUD of the configuration tables (health index, EPC factors, charge
  categories).
- Company settings (Land Agency settings, `res.config.settings`) need the Odoo *Settings* (admin)
  right, as for every Odoo setting; the menu is restricted to `base.group_system`.
- Every model with a company has an `ir.access` multi-company restriction
  `[('company_id', 'in', company_ids)]`; health index, EPC factors and charge categories are shared.
- Tests: `tests/test_security.py` (property manager, accountant, multi-company isolation).

Future household income data (income-based rents, out of scope) must be restricted to
`group_regie_supervisor` (field-level `groups=` attribute + dedicated model access).

## Plan

Sections of the specification, in order: 6.1 properties, 6.2 leases, 6.3 rent invoicing,
6.4 indexation, 6.5 deposits, 6.6 charges, 6.7 reports, 8 security, **8b: translate the whole
module into French and Dutch** (`i18n/fr.po` and `i18n/nl.po` both complete — requested on
2026-10-29, replaces "nl.po prepared"), 9 demo data (**texts in French**; translatable fields of demo/data
records filled in English, French and Dutch — requested on 2026-10-29), 10 tests. One commit per section, committed
and pushed without asking (user request of 2026-10-29).

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
4. **Indexation** (`regie.health.index`, `regie.peb.correction.factor`, `regie.indexation`,
   `models/regie_lease_indexation.py`):
   - **Health index base 2013**: real Statbel data, January 2018 → October 2026, loaded as normal
     data (`data/regie_health_index_data.xml`, `noupdate`, source in the file header: Statbel open
     data `CPI All base years.zip`, column `MS_HLTH_IDX`, `NM_BASE_YR = 2013`). The download
     worked: no fictitious values. New months are encoded in Configuration > Health Index.
   - **EPC correction factors**: official table (Bruxelles Logement, art. 224/2 Brussels Housing
     Code, ordinance of 13/10/2023) as normal data, editable (`data/regie_peb_correction_factor_data.xml`).
   - Formula: base rent × new index / initial index (× correction factor), rounded to the cent.
     New index = index of the month preceding the anniversary. When it is not published yet
     (proposal created 45 days before), the last published index is used and the proposal is
     flagged *provisional* (button *Recompute*).
   - Initial index proposed from the table (month preceding the signature) when the signature date
     is encoded.
   - Correction factor when: housing lease on a dwelling, effective date before the company
     cut-off date (default 14/10/2022), EPC class E, F or G; factor by anniversary month (October
     split on the 14th).
   - Blocking conditions (no proposal, reason shown on the lease): written lease, registered,
     no exclusion clause, indexable flag, initial index, and for dwellings a valid EPC at the request
     date that was communicated to the tenant.
   - Daily cron creates the proposals `regie_indexation_notice_days` (45) days before the
     anniversary; button *Create Indexation* on the lease for late requests.
   - States: to validate → validated (Supervisor only) → sent → applied (Supervisor only); refused.
   - **Send**: request date (default today), effective date = max(anniversary, request date −
     retroactivity months (default 3)); French PDF letter (`report/regie_indexation_letter.xml`,
     rendered in `fr_BE`/`fr_FR` when active) attached to the lease and emailed to the tenants from
     the lease chatter. During demo loading (no HTTP server, wkhtmltopdf cannot load the assets) the
     PDF is not generated; print it from the proposal.
   - **Apply**: new line in the rent history at the effective date (taken over by the schedule) and
     an arrears invoice (30 days) for the days already invoiced since the effective date.
   - Menus: Leases > Indexations to Process (grouped by state and anniversary month);
     Reporting > Indexations This Month.
   - QWeb in Odoo 20: variables such as `address` must be set **before** `t-call="web.external_layout"`
     and passed as attributes (`address="address"`).
5. **Rental deposits** (`regie.deposit`, outside the accounting):
   - Forms: blocked account, progressive bank guarantee, CPAS, Housing Fund, other; amount,
     constituted amount, bank (text: Odoo 20 has no `res.bank` model any more), IBAN or reference.
   - States: requested → partially constituted / constituted → release requested → released or
     retained.
   - **Cap** (housing leases only): `regie_deposit_cap_months` (default 2) × rent excluding charges
     in force at the deposit date; non-blocking warning banner above it. No cap for commercial and
     parking leases.
   - Release: *Compute Retentions* reads the open balance of the lease invoices (split rent /
     charges), damages are encoded by hand, retained amount capped at the constituted amount;
     *Request Release* schedules activities at move-out + 30 and + 50 days (settings) for a return
     expected within 2 months; PDF *Deposit Release Form* (`report/regie_deposit_release.xml`, French).
   - Letters to tenants use `res.company._regie_get_letter_lang()` (fr_BE, else fr_FR).
6. **Charges** (`models/regie_charge.py`, `models/regie_charge_statement.py`):
   - Actual costs = posted vendor bill lines with a **charge category** (`regie_charge_category_id`
     on `account.move.line`, column on the bill lines) and the building analytic account in their
     analytic distribution (only the building's percentage is counted).
   - **Allocation keys** per building and category: surface (default when no key), shares
     (quotités), equal parts, consumption (`regie.consumption.reading`, CSV import per unit and
     period; a reading counts for the year in which its period ends).
   - **Yearly statement per building** (calendar year): each unit's share is split by **day of
     occupation** between the leases; vacant days, categories not provided by the lease and
     flat-rate leases are **borne by the agency**. Per lease: provisions called (invoiced schedule
     lines of the year — "provisions payées" of the specification is read as *provisions called*:
     unpaid provisions remain in the open balance), actual share, balance.
   - *Generate Regularisations*: posted invoice (balance due) or credit note (refund), due in 30
     days, product *Charge Regularisation* on the charge provision account, lease taxes with the
     VAT option. PDF statement per lease detailed by category (`report/regie_charge_statement_report.xml`).
   - Provision adjustment: proposed monthly provision = actual share annualised / 12; *Apply
     Provision* (Supervisor) adds a rent history line from the next month.
7. **Reports** (`views/regie_report_views.xml`, `models/regie_dashboard.py`):
   - Unpaid by tenant / by building: open posted rent invoices and credit notes (list + pivot,
     *Overdue* filter), Accountant group.
   - Vacant units (unit status *free*), leases ending within 6 months, indexations to process
     this month = pending proposals (to validate, validated, sent) whose anniversary is before the
     end of next month (the letter must go out this month; late ones included).
   - **Dashboard** (`regie.dashboard`, transient, opened by a server action, first menu): open and
     overdue balance, tenants with overdue invoices, occupancy, vacant units, running / ending /
     litigation leases, indexations, deposit releases, with links to the lists.
