# Changelog

All notable changes to Myelin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Provider data patching** - `IPSFDatabase.patch()` and `OPSFDatabase.patch()` methods for incremental updates to provider-specific data. Queries the maximum `last_updated` date, downloads only new records from that point forward, and upserts them (updating existing records with the same provider_ccn + effective_date, inserting new ones). Supports both YYYYMMDD and YYYY-MM-DD date formats.

## [1.0.0] - 2026-06-04

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
- **Java stub generation** (`create_stubs.py`) for IDE type checking of JPype
  interop.

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

[Unreleased]: https://github.com/LibrePPS/myelin/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/LibrePPS/myelin/releases/tag/v1.0.0
