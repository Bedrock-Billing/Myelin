# FHIR Support for Myelin — Research & Implementation Plan

> **Status:** Researched and scoped, awaiting decisions before implementation begins.
> **Audience:** Maintainers and contributors returning to this work later.

## 1. Goal

Add **HL7 FHIR R4** support to Myelin so that institutional (UB-04) claims and
their adjudication results can be produced and consumed as standard FHIR
resources, enabling interop with modern EHRs, payer Patient Access APIs, and
analytics pipelines.

Concretely, by the end of v1, a user should be able to:

```python
from myelin import Claim, Myelin
from myelin.fhir import to_fhir_claim, to_fhir_eob, to_fhir_bundle, to_carin_bundle

myelin = Myelin()
output = myelin.process(claim)

fhir_claim = to_fhir_claim(claim)                            # myelin.fhir.Claim
eob        = to_fhir_eob(output, claim=claim)                # myelin.fhir.ExplanationOfBenefit
bundle     = to_fhir_bundle(output, claim=claim)             # myelin.fhir.Bundle (collection)
carin      = to_carin_bundle(output, claim=claim)            # CARIN-IG-shaped bundle

# Round-trip back to Myelin
from myelin.fhir import from_fhir_claim
rebuilt = from_fhir_claim(fhir_claim.model_dump_json())
```

## 2. Scope of v1

### In-scope
- `Claim` resource (egress + ingress).
- `ExplanationOfBenefit` resource (egress; the natural home for all pricer payment numbers).
- `Bundle` resource (collection, document, transaction).
- Party resources: `Patient`, `Organization`, `Practitioner`, `PractitionerRole`, `Coverage`.
- Clinical resources needed to support the above: `Encounter` (with `hospitalization.dischargeDisposition`), `Condition`, `Procedure`.
- `QuestionnaireResponse` for OASIS / IRF-PAI assessments (these have no first-class FHIR resource).
- CARIN Blue Button STU 2.2.0 institutional profile as the primary conformance target.
- Round-trip tests + golden JSON tests + C4BB profile assertion tests.

### Out of scope (v1)
- Da Vinci PDex / PAS prior-authorization flows (v2).
- SMART-on-FHIR OAuth (separate concern; not needed for local model interop).
- Pushing bundles to a live FHIR server (would use `fhirpy` later; not a v1 concern).
- HL7 R5 / R4B support — we target R4.0.1 specifically.
- CMS-1500 (professional) claim mapping — institutional/UB-04 first.

## 3. Library research summary

| Library | Stars | Latest | License | Pydantic v2 native? | R4(R4B) Claim/EOB? | Verdict |
|---|---:|---|---|---|---|---|
| `fhir.resources` (nazrulworld) | 531 | v8.2.0 (Feb 2026) | BSD | **Yes** | Yes (R4B sub-pkg) | Heavy; 5-10 MB for ~12 resources we'll use; R4B not R4 |
| `fhirclient` (SMART) | 693 | v4.4.0 (Feb 2026) | Apache-2.0 | No | R4B | Best for SMART/OAuth; no Pydantic interop |
| `fhirpy` (beda-software) | 212 | v2.2.0 (Oct 2025) | MIT | No (via `fhir-py-types`) | Indirect | Best for async REST client (future) |
| `fhirpack` | 50 | v0.0.10b0 (Jun 2023) | MIT | No | N/A | Stale; wrong problem space |
| `fhiry` | 50 | v5.2.2 (Jan 2026) | MIT | No | No | DataFrame flattening, not models |

**Recommended approach:** hand-roll a small Pydantic v2 `myelin.fhir` subpackage
(no new runtime dependency). See §6 for the dependency decision matrix.

## 4. Hard mapping problems (UB-04 → FHIR)

| Myelin field | FHIR target | Notes |
|---|---|---|
| `bill_type` (e.g. `111`) | `Claim.type` = `institutional` + `Claim.subType` | NUBC code goes in `subType.coding[]` |
| `patient_status` (80+ NUBC codes) | `Encounter.hospitalization.dischargeDisposition` | The bound VS `discharge-disposition` has only 11 codes. Strategy: keep raw NUBC in `coding[]` and map the standardized 11. |
| `principal_dx`, `admit_dx`, `secondary_dxs[*]` | `Claim.diagnosis[]` (`diagnosisCodeableConcept` + `type` + `onAdmission` + `packageCode`) | `type` ∈ {admitting, principal, discharge}; sequence from list order. |
| `DiagnosisCode.poa` (Y/N/W/U/ONE/E/BLANK/INVALID) | `Claim.diagnosis[].onAdmission` (VS `ex-diagnosis-on-admission` has only Y/N/U/W) | `ONE/E/BLANK/INVALID` collapse to `n` or use a `data-absent-reason` extension. |
| MS-DRG output | `Claim.diagnosis[].packageCode` (and `ExplanationOfBenefit.diagnosis[].packageCode`) | CodeSystem `http://terminology.hl7.org/CodeSystem/ex-diagnosisrelatedgroup`. |
| `inpatient_pxs[]` (ICD-10-PCS) | `Claim.procedure[]` (`procedureCodeableConcept`) | Principal procedure gets `type=primary`. |
| `cond_codes` (FL 18-28) | `Claim.supportingInfo[]` (`category=info` or `exception`) | NUBC condition-code coding in `code.coding[]`. |
| `value_codes` (FL 39-41, code/amount) | `Claim.supportingInfo[]` (`category=info`, `valueQuantity` for the amount) | Most natural fit; NUBC code in `code.coding[]`. |
| `occurrence_codes` (FL 31-34, code/date) | `Claim.supportingInfo[]` (`category=onset`, `timingDate`) | |
| `span_codes` (FL 35-36, code/date-range) | `Claim.supportingInfo[]` (`category=info`, `timingPeriod`) | |
| `lines[].revenue_code` | `Claim.item[].revenue` | UB-04 FL 42 → `Claim.item[].revenue.coding`. |
| `lines[].hcpcs` | `Claim.item[].productOrService` | CPT/HCPCS coding. |
| `lines[].modifiers` | `Claim.item[].modifier[]` | One `CodeableConcept` per modifier. |
| `lines[].units` / `lines[].charges` | `Claim.item[].quantity` / `Claim.item[].net` | |
| `lines[].service_date` | `Claim.item[].serviced[x]` | `date` for outpatient, `Period` for inpatient day-range. |
| `lines[].ndc` / `ndc_units` | `Claim.item[].detail[].productOrService` / `quantity` | Per CARIN BB. |
| `admit_date` / `from_date` / `thru_date` | `Encounter.period` + `Claim.billablePeriod` | UB-04 FL 12-13 → `Encounter.period.start`; FL 6 → `Claim.billablePeriod`. |
| `admission_source` (FL 15) | `Encounter.hospitalization.admitSource` | |
| `billing_provider` (NPI/CCN) | `Organization` + `Claim.provider` | NPI uses `http://hl7.org/fhir/sid/us-npi`; CCN via NUBC. |
| `servicing_provider` | `Practitioner` / `PractitionerRole` | |
| `oasis_assessment` | `QuestionnaireResponse` (SDC) | OASIS-E items map to standard SDC questions. |
| `irf_pai` | `QuestionnaireResponse` (SDC) | IRF-PAI items map to standard SDC questions. |
| `hmo` (Medicare Advantage flag) | `Coverage.class[]` or a `Coverage` extension | |
| `non_covered_days`, `total_charges`, `opps_flag`, `demo_codes`, `esrd_initial_date` | `Claim.supportingInfo[]` (no first-class FHIR home) | |
| Pricer payment outputs (per-line) | `ExplanationOfBenefit.item[].adjudication[]` (CARIN BB categories) | submittedamount, allowedamount, deductibleapplied, copayapplied, coinsuranceapplied, paidtoprovider, paidbypayer, memberliability, contractualobligation, etc. |
| Pricer totals | `ExplanationOfBenefit.total[]` (category + amount) | submitted, allowed, providerpaid, patientresponsibility, etc. |
| Pricer return codes / claim disposition | `ExplanationOfBenefit.outcome` + `ExplanationOfBenefit.disposition` | |

## 5. Package layout (proposed)

```
myelin/fhir/
├── __init__.py                  # public API: to_fhir_*, from_fhir_*, bundle helpers
├── _datatypes.py                # CodeableConcept, Coding, Money, Period, Identifier,
│                                #   HumanName, Address, Reference, Quantity, Attachment
├── codesystems.py               # Canonical URI constants
│                                #   (NUBC, NPI, ex-diagnosisrelatedgroup, C4BB, …)
├── extensions.py                # Myelin-specific extensions (POA data-absent, etc.)
├── patient.py                   # Patient
├── organization.py              # Organization (NPI/CCN identifier types)
├── practitioner.py              # Practitioner, PractitionerRole
├── coverage.py                  # Coverage
├── encounter.py                 # Encounter (incl. hospitalization.dischargeDisposition)
├── condition.py                 # Condition
├── procedure.py                 # Procedure
├── claim.py                     # Claim (supportingInfo, item[], diagnosis[], procedure[])
├── explanation_of_benefit.py    # ExplanationOfBenefit (adjudication[] + total[])
├── bundle.py                    # Bundle (collection/document/transaction)
├── questionnaire.py             # QuestionnaireResponse (OASIS / IRF-PAI)
├── mapper.py                    # Bidirectional UB-04 ↔ FHIR translation engine
└── profile_carin.py             # C4BB-ExplanationOfBenefit-Institutional profile helpers
```

## 6. Dependency decision matrix

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **A. Hand-roll Pydantic v2 (no dep)** | Zero runtime cost; perfect Pydantic v2 round-trip with `Claim`; full control over invariants; keeps `pyproject.toml` clean. | ~12 model files, ~200-300 lines each to maintain. | **Primary.** |
| **B. Add `fhir.resources` as optional `[fhir]` extra** | R5/R4B models out of the box. | 5-10 MB dep; R4B not R4; you still write validators. | **Test-only reference oracle** — use it in the test suite to verify our hand-written `model_dump()` matches theirs for the same input. |
| **C. Add `fhirclient` as optional extra** | OAuth / SMART flow included. | No Pydantic; requires adapter code. | **Skip for v1.** |
| **D. Add `fhirpy` as optional extra** | Async REST client for CMS Patient Access API. | No Pydantic models. | **Skip for v1.** Revisit when we add server push. |

**Decision:** Option A for the package; Option B as a test-only dev dependency
under `[dependency-groups.dev]`.

## 7. Public API

Mirror the existing `to_ub04_pdf` / `from_ub04_pdf` pattern on `Claim`:

```python
# One-way conversions
to_fhir_claim(myelin_claim) -> myelin.fhir.Claim
from_fhir_claim(fhir_json_or_model) -> myelin.input.Claim

to_fhir_eob(myelin_output, claim=...) -> myelin.fhir.ExplanationOfBenefit

# Bundles
to_fhir_bundle(myelin_output, claim=...) -> myelin.fhir.Bundle
to_carin_bundle(myelin_output, claim=...) -> myelin.fhir.Bundle  # CARIN-IG conformant

# Profile assertions (raise if not conformant)
assert_carin_bb_institutional(eob) -> None
```

Re-exported from `myelin/__init__.py` for consistency with the existing
public surface.

## 8. Implementation phases

1. **Foundation** — `_datatypes.py`, `codesystems.py`, `extensions.py`. Small
   Pydantic v2 models with `extra="forbid"` to enforce FHIR invariants.
2. **Party resources** — `Patient`, `Organization`, `Practitioner`,
   `PractitionerRole`, `Coverage`. Each ~80-150 lines, with `from_claim()` /
   `to_claim()` adapter helpers in `mapper.py`.
3. **Clinical resources** — `Encounter` (with dischargeDisposition NUBC
   handling), `Condition`, `Procedure`.
4. **`Claim`** — the load-bearing resource. All §4 mapping rules live here.
5. **`ExplanationOfBenefit`** — consumes the entire `MyelinOutput` and emits
   `EOB.item[].adjudication[]` (C4BB categories) and `EOB.total[]`.
6. **`Bundle`** + **CARIN-IG helpers** — `to_carin_bundle()` produces a
   self-contained collection ready for a Patient Access API POST.
7. **Reverse direction** — `from_fhir_claim()` and `from_fhir_eob()` for
   ingesting FHIR payloads. Returns a `lossy_fields: list[str]` so callers
   know what didn't make it across the round-trip.
8. **Tests** — `tests/fhir/`:
   - Round-trip tests (Claim → FHIR → Claim field-by-field equality where
     possible; lossy-fields asserted explicitly where it isn't).
   - Golden JSON tests (snapshot a fixed input's FHIR JSON for diff-review).
   - CARIN-IG profile assertion tests
     (`assert_carin_bb_institutional(eob)`).
   - DRG placement, supportingInfo sequence numbering, `serviced[x]` choice
     (date vs Period) tests.
   - Cross-check against `fhir.resources` for a few canonical inputs (using
     `fhir.resources` as a reference oracle).

## 9. Open decisions (need user input)

| # | Question | Recommendation |
|---|---|---|
| 1 | **Scope of v1** — full list in §2? | **Yes, as listed.** OASIS/IRF-PAI as QuestionnaireResponse included. |
| 2 | **Dependency strategy** — A, B, or both? | **A primary, B test-only.** |
| 3 | **IG target** — CARIN BB STU 2.2.0 institutional first? | **Yes.** PDex as v2. |
| 4 | **Round-trip direction in v1** — egress, ingress, or both? | **Both, with egress tested more thoroughly** in v1; ingress best-effort with a `lossy_fields: list[str]` return. |
| 5 | **Naming** — `myelin.fhir` subpackage, public symbols re-exported from `myelin/__init__.py`? | **Yes.** |
| 6 | **MIT-compat constraint** — any internal-license concern? | All candidate deps (BSD, Apache-2.0, MIT) are MIT-compatible. None to flag. |

## 10. Key reference URLs

- FHIR R4 Claim — https://www.hl7.org/fhir/R4/claim.html
- FHIR R4 ExplanationOfBenefit — https://www.hl7.org/fhir/R4/explanationofbenefit.html
- FHIR R4 Encounter — https://www.hl7.org/fhir/R4/encounter.html
- FHIR R4 Coverage — https://www.hl7.org/fhir/R4/coverage.html
- FHIR R4 discharge-disposition VS — https://www.hl7.org/fhir/R4/valueset-encounter-discharge-disposition.html
- FHIR R4 example-diagnosis-on-admission VS — https://www.hl7.org/fhir/R4/valueset-ex-diagnosis-on-admission.html
- HL7 R4 → R4B strategy — https://confluence.hl7.org/display/FHIR/Strategies+for+dealing+with+R4+and+R4B
- Da Vinci PDex — https://hl7.org/fhir/us/davinci-pdex/
- CARIN Blue Button — https://hl7.org/fhir/us/carin-bb/
- HL7 Financial Management Work Group (UB-04 mapping) — https://confluence.hl7.org/display/FM/FHIR+Resource+Development
- `fhir.resources` — https://github.com/nazrulworld/fhir.resources
- `fhirclient` — https://github.com/smart-on-fhir/client-py
- `fhirpy` — https://github.com/beda-software/fhir-py

## 11. Estimated effort

- **Phase 1-3 (foundation + party + clinical resources):** 2-3 days
- **Phase 4-5 (Claim + EOB):** 3-4 days
- **Phase 6-7 (Bundle + ingress):** 1-2 days
- **Phase 8 (tests):** 2 days
- **Total:** ~2 weeks of focused work
