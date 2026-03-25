"""
UB04 Field Mapping: FL numbers ↔ Claim model paths

Maps each Form Locator (FL) on the CMS 1450/UB04 to its corresponding
path in the Myelin Claim model. Used by ub04_pdf.py for both reading
and writing UB04 PDFs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class UB04FieldMapping:
    """Maps a single UB04 form locator to a Claim model path."""

    fl_key: str  # Coordinate key in ub04_coordinates.py (e.g., "FL4", "FL42_1")
    claim_path: str  # Claim key (e.g., "billing_provider.facility_name")
    label: str
    field_type: str = "str"
    date_format: str = "%m%d%y"  # For date fields
    transform_write: Callable[[Any], str] | None = None
    transform_read: Callable[[str], Any] | None = None


def _fmt_date_mmddyy(val: Any) -> str:
    if isinstance(val, datetime):
        return val.strftime("%m%d%y")
    return str(val) if val else ""


def _fmt_date_mmddyyyy(val: Any) -> str:
    if isinstance(val, datetime):
        return val.strftime("%m%d%Y")
    return str(val) if val else ""


def _parse_date_mmddyy(val: str) -> datetime | None:
    val = val.strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, "%m%d%y")
    except ValueError:
        try:
            return datetime.strptime(val, "%m%d%Y")
        except ValueError:
            return None


def _parse_date_mmddyyyy(val: str) -> datetime | None:
    val = val.strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, "%m%d%Y")
    except ValueError:
        try:
            return datetime.strptime(val, "%m%d%y")
        except ValueError:
            return None


def _fmt_charges(val: Any) -> str:
    if val is None:
        return ""
    try:
        f = float(val)
        if f == 0.0:
            return ""
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(val)


def _parse_charges(val: str) -> float:
    val = val.strip().replace(",", "").replace("$", "")
    if not val:
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def _fmt_units(val: Any) -> str:
    if val is None:
        return ""
    try:
        f = float(val)
        if f == 0.0:
            return ""
        if f == int(f):
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return str(val)


def _fmt_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val)


def _fmt_city_st_zip(provider: Any) -> str:
    """Format city, state zip from a Provider or Patient address."""
    if provider is None:
        return ""
    addr = getattr(provider, "address", provider)
    parts = []
    if addr.city:
        parts.append(addr.city)
    if addr.state:
        parts.append(addr.state)
    city_state = ", ".join(parts) if len(parts) == 2 else " ".join(parts)
    if addr.zip:
        return f"{city_state} {addr.zip}"
    return city_state


def _fmt_dx_code(val: Any) -> str:
    """Format a DiagnosisCode or plain string."""
    if val is None:
        return ""
    if hasattr(val, "code"):
        return val.code
    return str(val)


def _fmt_modifiers(mods: Any) -> str:
    """Format modifiers list as space-separated."""
    if not mods:
        return ""
    if isinstance(mods, list):
        return " ".join(str(m) for m in mods if m)
    return str(mods)


HEADER_MAPPINGS: list[UB04FieldMapping] = [
    UB04FieldMapping("FL1_name", "billing_provider.facility_name", "Provider Name"),
    UB04FieldMapping(
        "FL1_addr1", "billing_provider.address.address1", "Provider Addr1"
    ),
    UB04FieldMapping(
        "FL1_addr2", "billing_provider.address.address2", "Provider Addr2"
    ),
    UB04FieldMapping(
        "FL1_city_st_zip",
        "billing_provider",
        "Provider City/St/Zip",
        transform_write=_fmt_city_st_zip,
    ),
    UB04FieldMapping(
        "FL1_phone",
        "billing_provider.address.phone",
        "Provider Phone",
    ),
    UB04FieldMapping("FL3a", "claimid", "Patient Control Number"),
    UB04FieldMapping("FL3b", "patient.medical_record_number", "Medical Record Number"),
    UB04FieldMapping("FL4", "bill_type", "Type of Bill"),
    UB04FieldMapping("FL5", "additional_data.fed_tax_no", "Federal Tax Number"),
    UB04FieldMapping(
        "FL6_from",
        "from_date",
        "Statement From",
        field_type="date",
        transform_write=_fmt_date_mmddyy,
        transform_read=_parse_date_mmddyy,
    ),
    UB04FieldMapping(
        "FL6_thru",
        "thru_date",
        "Statement Through",
        field_type="date",
        transform_write=_fmt_date_mmddyy,
        transform_read=_parse_date_mmddyy,
    ),
    UB04FieldMapping("FL8a", "patient.last_name", "Patient Last Name"),
    UB04FieldMapping("FL8b", "patient.first_name", "Patient First Name"),
    UB04FieldMapping("FL9a", "patient.address.address1", "Patient Street"),
    UB04FieldMapping("FL9b", "patient.address.city", "Patient City"),
    UB04FieldMapping("FL9c", "patient.address.state", "Patient State"),
    UB04FieldMapping("FL9d", "patient.address.zip", "Patient Zip"),
    UB04FieldMapping("FL9e", "patient.address.country", "Patient Country"),
    UB04FieldMapping(
        "FL10",
        "patient.date_of_birth",
        "Patient DOB",
        field_type="date",
        transform_write=_fmt_date_mmddyyyy,
        transform_read=_parse_date_mmddyyyy,
    ),
    UB04FieldMapping("FL11", "patient.sex", "Patient Sex"),
    UB04FieldMapping(
        "FL12",
        "admit_date",
        "Admission Date",
        field_type="date",
        transform_write=_fmt_date_mmddyy,
        transform_read=_parse_date_mmddyy,
    ),
    UB04FieldMapping("FL14", "additional_data.admission_type", "Admission Type"),
    UB04FieldMapping("FL15", "admission_source", "Source of Admission"),
    UB04FieldMapping("FL17", "patient_status", "Patient Discharge Status"),
    UB04FieldMapping("FL56", "billing_provider.npi", "Billing NPI"),
    UB04FieldMapping("FL66", "additional_data.dx_version", "ICD Version Qualifier"),
    UB04FieldMapping(
        "FL69",
        "admit_dx",
        "Admitting Diagnosis",
        transform_write=_fmt_dx_code,
    ),
    UB04FieldMapping("FL76_npi", "servicing_provider.npi", "Attending NPI"),
    UB04FieldMapping("FL76_last", "servicing_provider.last_name", "Attending Last"),
    UB04FieldMapping("FL76_first", "servicing_provider.first_name", "Attending First"),
    UB04FieldMapping("FL80", "additional_data.remarks", "Remarks"),
]

_COND_CODE_FLS = [f"FL{i}" for i in range(18, 29)]
CONDITION_CODE_MAPPINGS: list[tuple[str, int]] = [
    (fl_key, idx) for idx, fl_key in enumerate(_COND_CODE_FLS)
]

OCCURRENCE_CODE_SLOTS = [
    "31a",
    "32a",
    "33a",
    "34a",
    "31b",
    "32b",
    "33b",
    "34b",
]

SPAN_CODE_SLOTS = ["35a", "36a", "35b", "36b"]

VALUE_CODE_SLOTS = [
    "39a",
    "40a",
    "41a",
    "39b",
    "40b",
    "41b",
    "39c",
    "40c",
    "41c",
    "39d",
    "40d",
    "41d",
]

DX_SECONDARY_KEYS = [f"FL67{chr(c)}" for c in range(ord("A"), ord("R"))]

RFVDX_KEYS = ["FL70a", "FL70b", "FL70c"]

PROCEDURE_SLOTS = ["74", "74a", "74b", "74c", "74d", "74e"]


def resolve_claim_value(claim: Any, path: str) -> Any:
    """Resolve a dot-separated path on a claim object.

    Handles 'additional_data.key' by looking up the key in the additional_data dict.
    Returns None if any part of the path is missing.
    """
    parts = path.split(".")
    obj = claim
    for i, part in enumerate(parts):
        if obj is None:
            return None
        if part == "additional_data" and i < len(parts) - 1:
            # Look up remaining path in the additional_data dict
            ad = getattr(obj, "additional_data", {})
            remaining_key = ".".join(parts[i + 1 :])
            return ad.get(remaining_key, "")
        obj = getattr(obj, part, None)
    return obj


def format_field_value(mapping: UB04FieldMapping, raw_value: Any) -> str:
    """Format a raw claim value for writing to PDF."""
    if mapping.transform_write:
        return mapping.transform_write(raw_value)
    return _fmt_str(raw_value)
