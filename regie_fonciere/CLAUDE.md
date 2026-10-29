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

Never use a remote database, Odoo.sh, staging or production. Git: one commit per section, committed
and pushed to `origin/main` without asking (user request of 2026-10-29); English messages, no
tool attribution.

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

# load the interface languages
venv/Scripts/python.exe odoo-bin i18n loadlang -c wb.conf -d wb_dev -l fr_BE nl_BE

# export the translation template (see Translations), reload the .po files
venv/Scripts/python.exe odoo-bin i18n export -c wb.conf -d wb_dev -l pot -o <scratch>/regie_fonciere.pot regie_fonciere
venv/Scripts/python.exe odoo-bin -c wb.conf -d wb_dev -u regie_fonciere --i18n-overwrite --stop-after-init

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

- Code, field names, comments: **English**. UI tested in French; `i18n/fr.po` and `i18n/nl.po`
  complete (see Translations).
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

## Brussels rules (to be confirmed by the agency's legal department)

Every figure is a company setting (Land Agency settings) or an editable table:

| Rule | Implementation | Setting / data |
| --- | --- | --- |
| Indexation once a year at the anniversary of the effective date, on written request | proposals created before the anniversary, letter = written request | `regie_indexation_notice_days` (45) |
| New index = health index of the month preceding the anniversary; initial index = month preceding the signature | `regie.health.index` (Statbel, base 2013) | `regie_index_base_year` (2013) |
| Lease must be written and registered, no exclusion clause, indexation not disabled | blocking reasons on the lease | lease fields |
| Valid EPC certificate at the request date, communicated to the tenant (dwellings) | blocking reasons | unit EPC fields, `peb_communicated` |
| EPC correction factor for leases in force before 14/10/2022, EPC E, F or G (art. 224/2 Housing Code, ordinance 13/10/2023) | factor by anniversary month, October split on the 14th | `regie_peb_correction_cutoff_date` (14/10/2022), table `regie.peb.correction.factor` |
| Retroactivity limited before the written request | effective date = max(anniversary, request − N months) | `regie_indexation_retroactivity_months` (3) |
| Rental deposit of a housing lease: max. 2 months of rent excluding charges (since 1/11/2024) | non-blocking warning | `regie_deposit_cap_months` (2) |
| Deposit on an account in the tenant's name, returned within 2 months after the move-out | follow-up outside the accounting, activities at +30 / +50 days | `regie_deposit_return_months` (2), `regie_deposit_reminder_days_1/2` (30, 50) |
| Recoverable charges: limitative list in the lease | categories per lease; others borne by the agency | `charge_category_ids` on the lease |
| Yearly statement of the charges, distinct from the rent | calendar-year statement per building | — |
| Statement can be rectified for 2 years | mention in the statement PDF; statement can be reset to draft and recomputed | — |
| Reference rent: mandatory mention in housing leases | required to sign a housing lease | `reference_rent` |

## Working assumptions of this first draft (to validate with the agency)

- Rent paid in advance: invoice generated on the 20th of the previous month, due on the 1st
  (`regie_invoice_day`, `regie_invoice_month_offset`, `regie_due_day`); one invoice per month,
  dated on the generation day (also for caught-up months).
- Prorata per calendar day of the month for the first and last month.
- Rent and provisions read at the first invoiced day of the month (a change during a month applies
  from the next month).
- Income accounts 700100 (rents) and 743100 (charge provisions) — to confirm with the accountant.
- Charge statement: *provisions called* (invoiced) are compared to the actual share; flat-rate
  leases are not regularised; costs without allocation key are split by surface.
- Letters to the tenants in French (Brussels language legislation may require the tenant's
  language — `res.company._regie_get_letter_lang` is the single place to change).
- Indexation proposal created 45 days before the anniversary with the last published index when
  the right one is not available yet (flagged *provisional*).
- Arrears invoice for the months already invoiced when an indexation is applied (not in the
  specification, added so that retroactivity is actually invoiced).
- Company settings are edited by Odoo administrators; supervisors maintain the tables.

## Tests (`tests/`, 44 tests, `--test-tags /regie_fonciere`)

| Requirement | Test |
| --- | --- |
| Monthly generation without duplicate, catch-up of a missed month | `test_invoicing.test_monthly_generation_without_duplicate`, `test_missed_months_are_caught_up` |
| Rent change during the year taken over by the schedule | `test_invoicing.test_rent_change_during_the_year` |
| Prorata at entry and exit | `test_invoicing.test_prorata_entry_and_exit` |
| Normal indexation | `test_indexation.test_normal_indexation` |
| Correction factor E / F-G, anniversary before and after 14 October | `test_indexation.test_correction_factor_epc_e_before_october_14`, `test_correction_factor_epc_f_after_october_14`, `test_correction_factor_epc_g_and_classes` |
| Unregistered lease, expired EPC | `test_indexation.test_unregistered_lease_blocked`, `test_expired_peb_blocked` |
| Retroactivity | `test_indexation.test_retroactivity_limited_to_three_months` |
| Deposit cap warning | `test_deposit.test_cap_warning_housing_lease`, `test_no_cap_for_commercial_lease` |
| Charge allocation with vacant unit and departure during the year | `test_charge.test_allocation_with_vacant_unit_and_departure` |
| Valid structured communication | `test_lease.test_structured_communication_format`, `test_structured_communication_unique_per_lease` |
| Also | lifecycle, VAT option, apply + arrears, cron proposals, provisional index, letter, release + reminders, allocation keys, regularisation moves, dashboard, security and multi-company |

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

## Translations

- `i18n/fr.po` and `i18n/nl.po` are **complete** (647 terms each, Brussels terminology: régie
  foncière / grondregie, bail / huurovereenkomst, PEB / EPB, CPAS / OCMW, Fonds du Logement /
  Woningfonds, Dutch names of the 19 municipalities). `fr.po` serves `fr_BE`, `nl.po` serves `nl_BE`.
- Languages loaded in `wb_dev`: `odoo-bin i18n loadlang -c wb.conf -d wb_dev -l fr_BE nl_BE`.
- After changing strings: export the template
  (`odoo-bin i18n export -c wb.conf -d wb_dev -l pot -o <scratch>/regie_fonciere.pot regie_fonciere`;
  `*.pot` is git-ignored in this repository), merge it into both files (e.g.
  `msgmerge --update i18n/fr.po regie_fonciere.pot` or polib), translate the new entries, then
  `-u regie_fonciere --i18n-overwrite` to reload them.
- Keep placeholders (`%s`, `%(name)s`), HTML tags and the leading/trailing punctuation of QWeb
  fragments identical to the English source.
- Letters (indexation, deposit release, charge statement) are rendered in `fr_BE` (else `fr_FR`);
  numbers use the language formats (`float` / `monetary` widgets).

## Demo data (`demo/`, company "Régie foncière (démo)")

Fictitious data, texts in **French** (tenants and suppliers in `fr_BE`, so the invoice lines,
letters and activities are in French); translatable fields of data records (charge categories
name and description, products, analytic plan) have English, French and Dutch values via the
`.po` files. Demo functions run with `lang='fr_BE'`.

| Item | Content |
| --- | --- |
| Buildings | Résidence du Héron Cendré (8 apartments incl. 1 studio + shop), Clos des Saules Pleureurs (4 apartments + 4 parkings), Maison des Trois Lanternes (house); all in Watermael-Boitsfort (1170), fictitious streets |
| Units | 18; EPC E (HER-1.2, SAU-0.1), F (HER-1.1), G (HER-3.2), expired EPC (HER-4.1); 6 free units |
| Leases | L01 old main residence EPC F · L02 old main residence EPC E · L03 recent (SEPA mandate) · L04 not registered · L05 EPC expired · L06 short term (starts mid-month, flat-rate charges) · L07 shared housing, 2 tenants + guarantor · L08 commercial with VAT · L09 parking · L10 apartment + parking in notice · L11 transit terminated mid-month · L12 house in litigation |
| Invoicing | generated by the schedule month by month from January 2025 (22 months instead of 18, so the 2025 charge statement has a full year of provisions): paid, partially paid (L05), overdue (L04, L11, L12), open (November 2026) |
| Indexation | to validate (L01 F with provisional index, L02 E), validated (L07), sent (L06), applied with arrears invoice (L03), refused (L09); L04/L05 blocked |
| Deposits | blocked accounts, progressive bank guarantee (partial), CPAS, Housing Fund (requested), other; L02 above the cap; L11 release requested with retentions and reminders; L12 retained |
| Charges | 2025 vendor bills of the Héron building with categories and analytic, allocation keys (consumption, shares, equal parts, surface), heat cost allocator readings, 2025 statement invoiced (5 regularisation invoices, 1 credit note) |
| Follow-ups | 3 levels without fees: 10, 25, 45 days |

Letters are not rendered as PDF while the demo is loaded (no HTTP server); print them from the
records.

## Explanation of the rent amounts

- `regie.lease.rent.line.explanation` (computed, *Explanation* column of the rent history on the
  lease): initial rent with the initial index; indexation formula with the indexes, the EPC factor
  and the retroactivity (from the proposal, or recomputed from the index tables for history lines
  encoded by hand, with the encoded amount when it differs); provision adjustment from the charge
  statement. `_get_explanation()` is extended in `regie_lease_indexation.py` and
  `regie_charge_statement.py`.
- `regie.lease.schedule.line.explanation` (lease > Invoicing tab, and Invoicing > Invoicing
  Schedule): rent and charges in force at the first invoiced day, rent history line used, prorata
  in days. Also copied in the notes (`narration`) of each rent invoice, in the tenant's language.
