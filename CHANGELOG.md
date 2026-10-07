# Changelog

All notable changes to Myelin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`AUTO` mode mutating the caller's claim** - `Myelin.process()` no longer
  appends the auto-generated modules to `claim.modules`; the claim keeps the
  modules the caller set. Previously a claim processed with `[AUTO]` came back
  as e.g. `[AUTO, MCE, MSDRG, IPPS]`, so processing it a second time (retries,
  re-runs, reused template claims) failed with "Auto module cannot be paired
  with any other module request". `[AUTO, AUTO]` is now treated as `[AUTO]`
  instead of being rejected.
- **`AUTO` mode routing psych and LTCH claims to IPPS** - `AUTO` now looks up
  the IPSF provider before choosing modules, so `11x` inpatient claims are
  sent to the IPF (`PSYCH`), LTCH, or IRF pricer based on the provider type,
  with the CCN as a fallback. Previously the provider was never available at
  that point and every `11x` claim went to IPPS, which returned a $0 payment
  for psych and LTCH hospitals. A failed provider lookup no longer blocks
  routing; it is still reported if the selected pricer needs the provider.
  See `docs/docs/auto-routing.md` for the full routing table and CMS sources.
- **`AUTO` mode routing for non-inpatient bill types** - the bill type now
  decides the setting and provider data only picks among inpatient pricers,
  so outpatient (`13x`) claims from psych, LTCH, and rehab hospitals stay on
  IOCE + OPPS. Hospice claims (`81x`/`82x`) now route to the hospice pricer
  and hospital swing-bed claims (`18x`) to the SNF pricer; both previously
  went to IOCE + OPPS.
- **Provider type `00` mapping** - `PROVIDER_TYPES["00"]` (short-term acute
  hospital) now maps to IPPS instead of the IPF pricer, and type `50`
  (rehabilitation distinct part) now maps to IRF to match type `04`.
- **CCN ranges in `AUTO` routing** - the CCN fallback now uses the CMS ranges:
  LTCH `xx2000`-`xx2299`, psych `xx4000`-`xx4499` or units `S`/`M`, and rehab
  units `T`/`R`. Previously any CCN with `2` or `4` in the third position
  matched, which also covered ESRD facilities, community mental health
  centers, and comprehensive outpatient rehab facilities.

## [1.0.2] - 2026-10-06

### Fixed

- **IPPS / IPF / LTCH `process()` kwargs** - `process()` no longer forwards
  caller kwargs (such as `session`) to `process_claim()`, which doesn't accept
  them. Previously `Myelin.process(claim, session=...)` raised an uncaught
  `TypeError` for any claim routed to IPPS, PSYCH, or LTCH.
- **IRF CMG grouper secondary diagnoses** - the first secondary diagnosis is now
  sent to the CMG grouper. Previously it was skipped whenever a principal
  diagnosis was present, which silently dropped comorbidities listed first and
  produced a lower-tier CMG and payment. Blank or `None` secondary codes are
  now skipped instead of raising or being sent as padding, and the cap of 25
  codes now counts the principal plus secondaries consistently.

## [1.0.1] - 2026-08-27

### Fixed

- **CMSDownloader outdated JARs** - the downloader now replaces superseded CMS
  JAR releases instead of keeping stale ones alongside or in place of them.
  - Discovers and selects the latest CMS component releases.
  - Tracks installed release identities to avoid redundant downloads.
  - Replaces superseded JARs transactionally, with rollback on failure.
  - Validates downloaded packages before replacing existing files.
  - Compares multi-part versions correctly.
  - Fails builds when downloads or environment validation fail.

## [1.0.0] - 2026-07-10

First stable release of Myelin. Provides a unified Python interface to the
official CMS (Centers for Medicare & Medicaid Services) Java-based reimbursement
tools via JPype1.

### Added

- **MS-DRG Grouper** (`DrgClient`) - assigns inpatient claims to DRGs for IPPS,
  IPF, and LTCH payment determination.
- **MCE Editor** (`MceClient`) - validates inpatient claims against the Medicare
  Code Editor.
- **IOCE Editor** (`IoceClient`) - processes outpatient claims through the
  Integrated Outpatient Code Editor, assigning APCs and applying edits.
- **HHA Grouper** (`HhagClient`) - groups home health claims using OASIS
  assessment data.
- **IRF Grouper** (`IrfgClient`) - groups inpatient rehabilitation facility
  claims into Case-Mix Groups (CMGs) using IRF-PAI data.
- **Pricer suite** for IPPS, OPPS, IPF (Psych), IRF, LTCH, SNF, HHA, Hospice,
  ESRD, and FQHC.
- **ASC Pricer** - pure-Python Ambulatory Surgical Center pricer with support
  for code-pair offsets, MUE limits, device discounts, and wage index lookup.
- **`Myelin` orchestrator** with a `process(claim)` entry point that wires the
  correct grouper, editor, and pricer together.
- **`AUTO` module** - automatic detection of required modules based on bill
  type, revenue codes, and provider data.
- **IPSF / OPSF provider data** - automatic lookup from CMS provider-specific
  files with per-claim override support for what-if analysis.
- **ICD-10 code conversion** (`ICDConverter`) - forward/backward mapping of
  diagnosis and procedure codes between fiscal years.
- **UB-04 (CMS-1450) PDF read/write** - generate a filled UB-04 PDF from a
  `Claim` and parse a filled UB-04 PDF back into a `Claim` object, plus a
  calibration PDF helper for verifying field mappings.
- **Excel export** - `MyelinOutput.to_excel()` and `to_excel_bytes()` for
  producing human-readable summaries of pricing/editing decisions.
- **Pydantic input/output models** throughout for type-safe claim construction
  and result handling.
- **Plugin system** via `pluggy` (`client_load_classes`, `client_methods`
  hookspecs) for custom Java class loading and client method extension.
- **CMSDownloader** - async, robust downloader for CMS grouper, editor, and
  pricer JARs with version tracking and extraction.
- **SQLite and PostgreSQL** database backends for provider data and ICD-10
  conversion tables.
- **JVM lifecycle management** - thread-safe startup/shutdown, context-manager
  support (`with Myelin(...) as m:`), and clean integration with multi-process
  workloads.
- ~~**Java stub generation** (`create_stubs.py`) for IDE type checking of JPype
  interop.~~ This effort was abandoned, may revisit in the future.
- **New IOCE fields added**
  - IoceOutputHcpcsModifier.description — for modifier descriptions on both input and output modifier lists
  - IoceOutputLineItem: action_flag_output_description, rejection_denial_flag_description, payment_method_flag_description, payment_indicator_description, revenue_code_description, discounting_formula_description
  - IoceOutput: claim_rejection_edit_disposition_description, claim_denial_edit_disposition_description, claim_return_to_provider_edit_disposition_description, claim_suspension_edit_disposition_description, line_rejection_edit_disposition_description, line_denial_edit_disposition_description
- **New descriptions added to ICOE output**
  - _enrich_disposition_and_edits now calls getEditDispositionDescription per disposition group when edits are present
  - Line items now also call: getLineItemActionFlagDescription, getLineItemDenialRejectionFlagDescription, getPaymentMethodFlagDescription, getPaymentIndicatorDescription, getRevenueCodeDescription, getDiscountFormulaDescription
  - Both input and output HCPCS modifier lists now call getHcpcsModifierDescription per modifier in addition to the existing edit descriptions
- **Provider data patching** - `IPSFDatabase.patch()` and `OPSFDatabase.patch()` methods for incremental updates to provider-specific data. Queries the maximum `last_updated` date, downloads only new records from that point forward, and upserts them (updating existing records with the same provider_ccn + effective_date, inserting new ones). Supports both YYYYMMDD and YYYY-MM-DD date formats.
- **MS-DRG diagnosis output codes** - `MsdrgOutputDxCode` now includes the
  original diagnosis code value, making principal and secondary diagnosis
  outputs easier to trace back to claim input.
- **IOCE description enrichment** - IOCE output now fills additional claim
  disposition, edit, line-item flag, modifier, payment indicator, revenue code,
  discount formula, and APC descriptions, with latest-description fallbacks when
  version-specific lookup text is unavailable.
- **IRF wage-index outputs** - `IrfOutput` now exposes inherited final CBSA and
  final wage-index values from the CMS payment data.


### Changed

- Centralized IPSF / OPSF provider lookups and exposed them on `MyelinOutput`
  alongside pricer results.
- Refactored `Myelin.process()` to make provider lookup errors non-halting and
  standardize error returns to `ReturnCode` values.
- Improved type safety across the library with `Protocol` types for Java
  interop surfaces.
- LTCH pricer now accepts an optional review code via claim `additional_data`
  and defaults the blend indicator to `0` when not provided.
- OPPS pricer tolerates a missing discount formula from IOCE.
- Hospice pricer tolerates a missing admit date and an optional IOCE output
  pass-through.
- IPSF / OPSF data is whitespace-stripped before being passed to Java pricers.
- Default `county_code` is now `0` instead of an empty string.
- Excel exporter strips nested-structure prefixes from column names and can
  optionally include the input claim on its own sheet.
- ASC Pricer no longer requires an OPSF provider (ASCs do not appear in OPSF).
- MCE input construction validates the discharge status.
- **CMSDownloader** - rewritten for clearer component discovery, jar inventory
  validation, missing-jar detection, bounded concurrent pricer downloads, shared
  request timeout handling, and cleaner extraction of only the required CMS
  runtime jars.


### Fixed

- Duplicate IRFG client initialization and duplicate ASC client setup in
  `Myelin` removed.
- Duplicate `IPSF` definition in `core.py` removed.
- LTCH-specific updates now applied prior to the Java call.
- HHA claim input construction.
- ICD converter no longer raises on a `None` check.
- Minor formatting issue on the Excel exporter summary tab.
- `IoceReturnCode` renamed from `ReturnCode` to avoid duplicate naming with the
  shared utility.
- **IPPS procedure codes** - inpatient procedure codes are now passed to the
  IPPS Java claim object as Java strings and assigned with `setProcedureCodes`.
- **IPSF HRR participant indicator** - preserves `0` values instead of treating
  them as missing, preventing invalid return codes and incorrect pricing.
- **Supplemental wage index mapping** - LTCH, SNF, and IRF now opt in to sending
  IPSF supplemental wage-index fields to the CMS Java provider object while IPF
  and other shared IPSF call sites keep the previous default behavior.
