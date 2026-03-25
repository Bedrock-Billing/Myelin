"""
UB04 PDF Reader/Writer for Myelin Claims

Provides functionality to:
- Read a filled CMS 1450/UB04 PDF and extract data into a Claim object
- Generate a filled CMS 1450/UB04 PDF from a Claim object

Requires optional dependencies: pypdf, reportlab
Install with: pip install myelin[pdf]
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myelin.input.claim import Claim

logger = logging.getLogger(__name__)

# UB04 template - Source: https://www.cms.gov/regulations-and-guidance/legislation/paperworkreductionactof1995/pra-listing-items/cms-1450
_BLANK_TEMPLATE = Path(__file__).parent / "ub04_data" / "ub04_blank.pdf"

_OCCURRENCE_CODE_SLOTS = ["31a", "32a", "33a", "34a", "31b", "32b", "33b", "34b"]
_SPAN_CODE_SLOTS = ["35a", "36a", "35b", "36b"]
_VALUE_CODE_SLOTS = [
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
_PROCEDURE_SLOTS = ["74", "74a", "74b", "74c", "74d", "74e"]


def _ensure_pdf_libs() -> None:
    """Ensure pypdf and reportlab are available."""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        raise ImportError(
            "pypdf is required for UB04 PDF support. Install with: pip install pypdf"
        )
    try:
        import reportlab  # noqa: F401
    except ImportError:
        raise ImportError(
            "reportlab is required for UB04 PDF support. "
            "Install with: pip install reportlab"
        )


def write_ub04_pdf(
    claim: Claim,
    output_path: str | Path | None = None,
    template_path: str | Path | None = None,
) -> bytes:
    """Generate a filled UB04 PDF from a Claim object.

    Args:
        claim: The Myelin Claim to render onto the UB04 form.
        output_path: Optional file path to write the PDF. If None, only returns bytes.
        template_path: Optional path to a custom blank UB04 template PDF.
            Defaults to the bundled CMS-1450 form.

    Returns:
        The filled PDF as bytes.
    """
    _ensure_pdf_libs()

    from .ub04_field_map import (
        CONDITION_CODE_MAPPINGS,
        DX_SECONDARY_KEYS,
        HEADER_MAPPINGS,
        OCCURRENCE_CODE_SLOTS,
        PROCEDURE_SLOTS,
        RFVDX_KEYS,
        SPAN_CODE_SLOTS,
        VALUE_CODE_SLOTS,
        _fmt_charges,
        _fmt_date_mmddyy,
        _fmt_dx_code,
        _fmt_modifiers,
        _fmt_units,
        format_field_value,
        resolve_claim_value,
    )

    # Build the text overlay
    field_values = _extract_claim_fields(
        claim,
        HEADER_MAPPINGS,
        CONDITION_CODE_MAPPINGS,
        DX_SECONDARY_KEYS,
        RFVDX_KEYS,
        OCCURRENCE_CODE_SLOTS,
        SPAN_CODE_SLOTS,
        VALUE_CODE_SLOTS,
        PROCEDURE_SLOTS,
        format_field_value,
        resolve_claim_value,
        _fmt_charges,
        _fmt_date_mmddyy,
        _fmt_dx_code,
        _fmt_modifiers,
        _fmt_units,
    )

    return _render_ub04_overlay(
        field_values=field_values,
        output_path=output_path,
        template_path=template_path,
    )


def write_ub04_calibration_pdf(
    output_path: str | Path | None = None,
    template_path: str | Path | None = None,
) -> bytes:
    """Generate a calibration UB04 PDF labeled with every coordinate key."""
    from .ub04_coordinates import COORDINATES

    field_values = {fl_key: fl_key.split("_", 1)[0] for fl_key in sorted(COORDINATES)}
    return _render_ub04_overlay(
        field_values=field_values,
        output_path=output_path,
        template_path=template_path,
    )


def _render_ub04_overlay(
    field_values: dict[str, str],
    output_path: str | Path | None = None,
    template_path: str | Path | None = None,
) -> bytes:
    """Render UB04 field text onto the blank template and return PDF bytes."""
    _ensure_pdf_libs()

    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen.canvas import Canvas

    from .ub04_coordinates import (
        COORDINATES,
        FONT_NAME,
        FONT_SIZE,
        FONT_SIZE_SMALL,
        PAGE_HEIGHT,
        PAGE_WIDTH,
    )

    # Create reportlab overlay at standard coordinates (template is normalized to MediaBox [0, 0, 684, 864])
    tpl_path = Path(template_path) if template_path else _BLANK_TEMPLATE

    overlay_buf = BytesIO()
    c = Canvas(overlay_buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setFont(FONT_NAME, FONT_SIZE)

    for fl_key, text in field_values.items():
        if not text:
            continue
        coords = COORDINATES.get(fl_key)
        if coords is None:
            logger.debug(f"No coordinates for {fl_key}, skipping")
            continue
        x, y = coords
        if fl_key.startswith(("FL67", "FL70", "FL69", "FL72")):
            c.setFont(FONT_NAME, FONT_SIZE_SMALL)
        else:
            c.setFont(FONT_NAME, FONT_SIZE)
        c.drawString(x, y, text)

    c.save()
    overlay_buf.seek(0)

    # Merge overlay onto template
    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter(clone_from=str(tpl_path))
    writer.pages[0].merge_page(overlay_reader.pages[0])

    output_buf = BytesIO()
    writer.write(output_buf)
    pdf_bytes = output_buf.getvalue()

    if output_path:
        Path(output_path).write_bytes(pdf_bytes)

    return pdf_bytes


def _extract_claim_fields(
    claim: Any,
    header_mappings: list,
    condition_code_mappings: list,
    dx_secondary_keys: list,
    rfvdx_keys: list,
    occurrence_code_slots: list,
    span_code_slots: list,
    value_code_slots: list,
    procedure_slots: list,
    format_field_value: Any,
    resolve_claim_value: Any,
    _fmt_charges: Any,
    _fmt_date_mmddyy: Any,
    _fmt_dx_code: Any,
    _fmt_modifiers: Any,
    _fmt_units: Any,
) -> dict[str, str]:
    """Extract all claim fields into a dict keyed by FL coordinate keys."""
    fields: dict[str, str] = {}

    for mapping in header_mappings:
        raw = resolve_claim_value(claim, mapping.claim_path)
        fields[mapping.fl_key] = format_field_value(mapping, raw)

    for fl_key, idx in condition_code_mappings:
        if idx < len(claim.cond_codes):
            fields[fl_key] = str(claim.cond_codes[idx])

    fields["FL67"] = _fmt_dx_code(claim.principal_dx)

    for i, fl_key in enumerate(dx_secondary_keys):
        if i < len(claim.secondary_dxs):
            fields[fl_key] = _fmt_dx_code(claim.secondary_dxs[i])

    for i, fl_key in enumerate(rfvdx_keys):
        if i < len(claim.rfvdx):
            fields[fl_key] = str(claim.rfvdx[i])

    for i, slot in enumerate(occurrence_code_slots):
        if i < len(claim.occurrence_codes):
            oc = claim.occurrence_codes[i]
            fields[f"FL{slot}_code"] = oc.code
            fields[f"FL{slot}_date"] = _fmt_date_mmddyy(oc.date)

    for i, slot in enumerate(span_code_slots):
        if i < len(claim.span_codes):
            sc = claim.span_codes[i]
            fields[f"FL{slot}_code"] = sc.code
            fields[f"FL{slot}_from"] = _fmt_date_mmddyy(sc.start_date)
            fields[f"FL{slot}_thru"] = _fmt_date_mmddyy(sc.end_date)

    for i, slot in enumerate(value_code_slots):
        if i < len(claim.value_codes):
            vc = claim.value_codes[i]
            fields[f"FL{slot}_code"] = vc.code
            fields[f"FL{slot}_amount"] = _fmt_charges(vc.amount)

    for i, slot in enumerate(procedure_slots):
        if i < len(claim.inpatient_pxs):
            px = claim.inpatient_pxs[i]
            fields[f"FL{slot}_code"] = px.code
            fields[f"FL{slot}_date"] = _fmt_date_mmddyy(px.date)

    total_charges = 0.0
    max_lines = min(len(claim.lines), 22)
    for i in range(max_lines):
        line = claim.lines[i]
        row = i + 1
        fields[f"FL42_{row}"] = line.revenue_code
        fields[f"FL43_{row}"] = ""  # Description (not mapped)
        hcpcs_str = line.hcpcs
        mod_str = _fmt_modifiers(line.modifiers)
        if mod_str:
            hcpcs_str = f"{hcpcs_str} {mod_str}"
        fields[f"FL44_{row}"] = hcpcs_str
        fields[f"FL45_{row}"] = _fmt_date_mmddyy(line.service_date)
        fields[f"FL46_{row}"] = _fmt_units(line.units)
        fields[f"FL47_{row}"] = _fmt_charges(line.charges)
        total_charges += line.charges

    if len(claim.lines) > 22:
        logger.warning(
            f"Claim has {len(claim.lines)} lines but UB04 supports max 22 data lines. "
            "Lines beyond 22 are truncated."
        )

    fields["FL42_page"] = "1"
    fields["FL42_pages_total"] = "1"
    fields["FL44_creation_date"] = datetime.now().strftime("%m%d%y")

    total = claim.total_charges if claim.total_charges else total_charges
    if total:
        fields["FL47_total_charges"] = _fmt_charges(total)

    return fields


def read_ub04_pdf(pdf_path: str | Path | BytesIO) -> Claim:
    """Read a filled UB04 PDF and extract data into a Claim object.

    Supports two types of filled PDFs:
    1. Text-overlay PDFs produced by Myelin
    2. External AcroForm PDFs (interactive form fields) as a compatibility path

    Args:
        pdf_path: Path to the PDF file, or a BytesIO buffer.

    Returns:
        A populated Claim object.
    """
    _ensure_pdf_libs()

    from pypdf import PdfReader

    if isinstance(pdf_path, BytesIO):
        reader = PdfReader(pdf_path)
    else:
        reader = PdfReader(str(pdf_path))

    # Here we check if the supplied pdf has AcroForm fields before defaulting to text overlay
    # This code path will not almost certainly not work as is but its an step to support other UB04 pdf templates
    form_fields = reader.get_fields()
    if form_fields:
        return _read_external_acroform(form_fields)

    # Primary path for PDFs generated by this library.
    return _read_from_text(reader)


def _split_hcpcs_and_modifiers(raw_value: str) -> tuple[str, list[str]]:
    """Split FL44 text into HCPCS and modifiers."""
    tokens = [token for token in raw_value.split() if token]
    if not tokens:
        return "", []
    return tokens[0], tokens[1:]


def _build_claim_from_field_values(field_values: dict[str, str]) -> Claim:
    """Build a Claim from normalized UB04 FL-keyed values."""
    from myelin.input.claim import (
        Address,
        Claim,
        DiagnosisCode,
        LineItem,
        OccurrenceCode,
        Patient,
        ProcedureCode,
        Provider,
        SpanCode,
        ValueCode,
    )

    from .ub04_field_map import _parse_charges, _parse_date_mmddyy, _parse_date_mmddyyyy

    claim_data: dict[str, Any] = {}

    claimid = field_values.get("FL3a", "")
    if claimid:
        claim_data["claimid"] = claimid

    bill_type = field_values.get("FL4", "")
    if bill_type:
        claim_data["bill_type"] = bill_type

    from_date = _parse_date_mmddyy(field_values.get("FL6_from", ""))
    thru_date = _parse_date_mmddyy(field_values.get("FL6_thru", ""))
    admit_date = _parse_date_mmddyy(field_values.get("FL12", ""))
    if from_date:
        claim_data["from_date"] = from_date
    if thru_date:
        claim_data["thru_date"] = thru_date
    if admit_date:
        claim_data["admit_date"] = admit_date

    patient_status = field_values.get("FL17", "")
    admission_source = field_values.get("FL15", "")
    if patient_status:
        claim_data["patient_status"] = patient_status
    if admission_source:
        claim_data["admission_source"] = admission_source

    additional_data: dict[str, Any] = {}
    if field_values.get("FL5", ""):
        additional_data["fed_tax_no"] = field_values["FL5"]
    if field_values.get("FL14", ""):
        additional_data["admission_type"] = field_values["FL14"]
    if field_values.get("FL66", ""):
        additional_data["dx_version"] = field_values["FL66"]
    if field_values.get("FL80", ""):
        additional_data["remarks"] = field_values["FL80"]
    if additional_data:
        claim_data["additional_data"] = additional_data

    patient_address_data = {
        "address1": field_values.get("FL9a", ""),
        "city": field_values.get("FL9b", ""),
        "state": field_values.get("FL9c", ""),
        "zip": field_values.get("FL9d", ""),
        "country": field_values.get("FL9e", ""),
    }
    patient_data: dict[str, Any] = {
        "last_name": field_values.get("FL8a", ""),
        "first_name": field_values.get("FL8b", ""),
        "medical_record_number": field_values.get("FL3b", ""),
        "sex": field_values.get("FL11", ""),
    }
    dob = _parse_date_mmddyyyy(field_values.get("FL10", ""))
    if dob:
        patient_data["date_of_birth"] = dob
    if any(patient_address_data.values()):
        patient_data["address"] = Address(**patient_address_data)
    if any(v for v in patient_data.values()):
        claim_data["patient"] = Patient(**patient_data)

    provider_address_data = {
        "address1": field_values.get("FL1_addr1", ""),
        "address2": field_values.get("FL1_addr2", ""),
        "phone": field_values.get("FL1_phone", ""),
    }
    provider_data: dict[str, Any] = {
        "npi": field_values.get("FL56", ""),
        "facility_name": field_values.get("FL1_name", ""),
    }
    if any(provider_address_data.values()):
        provider_data["address"] = Address(**provider_address_data)
    if any(v for v in provider_data.values()):
        claim_data["billing_provider"] = Provider(**provider_data)

    servicing_provider_data = {
        "npi": field_values.get("FL76_npi", ""),
        "last_name": field_values.get("FL76_last", ""),
        "first_name": field_values.get("FL76_first", ""),
    }
    if any(servicing_provider_data.values()):
        claim_data["servicing_provider"] = Provider(**servicing_provider_data)

    pdx = field_values.get("FL67", "")
    if pdx:
        claim_data["principal_dx"] = DiagnosisCode(code=pdx)

    secondary_dxs = []
    for letter_idx in range(17):
        letter = chr(ord("A") + letter_idx)
        code = field_values.get(f"FL67{letter}", "")
        if code:
            secondary_dxs.append(DiagnosisCode(code=code))
    if secondary_dxs:
        claim_data["secondary_dxs"] = secondary_dxs

    admit_dx = field_values.get("FL69", "")
    if admit_dx:
        claim_data["admit_dx"] = DiagnosisCode(code=admit_dx)

    rfvdx = [field_values.get(f"FL70{suffix}", "") for suffix in ("a", "b", "c")]
    rfvdx = [code for code in rfvdx if code]
    if rfvdx:
        claim_data["rfvdx"] = rfvdx

    cond_codes = [field_values.get(f"FL{i}", "") for i in range(18, 29)]
    cond_codes = [code for code in cond_codes if code]
    if cond_codes:
        claim_data["cond_codes"] = cond_codes

    occurrence_codes = []
    for slot in _OCCURRENCE_CODE_SLOTS:
        code = field_values.get(f"FL{slot}_code", "")
        date = _parse_date_mmddyy(field_values.get(f"FL{slot}_date", ""))
        if code or date:
            occurrence_codes.append(OccurrenceCode(code=code, date=date))
    if occurrence_codes:
        claim_data["occurrence_codes"] = occurrence_codes

    span_codes = []
    for slot in _SPAN_CODE_SLOTS:
        code = field_values.get(f"FL{slot}_code", "")
        start_date = _parse_date_mmddyy(field_values.get(f"FL{slot}_from", ""))
        end_date = _parse_date_mmddyy(field_values.get(f"FL{slot}_thru", ""))
        if code or start_date or end_date:
            span_codes.append(
                SpanCode(code=code, start_date=start_date, end_date=end_date)
            )
    if span_codes:
        claim_data["span_codes"] = span_codes

    value_codes = []
    for slot in _VALUE_CODE_SLOTS:
        code = field_values.get(f"FL{slot}_code", "")
        amount_text = field_values.get(f"FL{slot}_amount", "")
        amount = _parse_charges(amount_text)
        if code or amount_text:
            value_codes.append(ValueCode(code=code, amount=amount))
    if value_codes:
        claim_data["value_codes"] = value_codes

    inpatient_pxs = []
    for slot in _PROCEDURE_SLOTS:
        code = field_values.get(f"FL{slot}_code", "")
        date = _parse_date_mmddyy(field_values.get(f"FL{slot}_date", ""))
        if code or date:
            inpatient_pxs.append(ProcedureCode(code=code, date=date))
    if inpatient_pxs:
        claim_data["inpatient_pxs"] = inpatient_pxs

    lines = []
    for row in range(1, 23):
        rev = field_values.get(f"FL42_{row}", "")
        raw_hcpcs = field_values.get(f"FL44_{row}", "")
        hcpcs, modifiers = _split_hcpcs_and_modifiers(raw_hcpcs)
        if rev or hcpcs or raw_hcpcs:
            line_data: dict[str, Any] = {
                "revenue_code": rev,
                "hcpcs": hcpcs,
                "modifiers": modifiers,
            }
            svc_date = _parse_date_mmddyy(field_values.get(f"FL45_{row}", ""))
            if svc_date:
                line_data["service_date"] = svc_date
            units_str = field_values.get(f"FL46_{row}", "")
            if units_str:
                try:
                    line_data["units"] = float(units_str)
                except ValueError:
                    pass
            charges_str = field_values.get(f"FL47_{row}", "")
            if charges_str:
                line_data["charges"] = _parse_charges(charges_str)
            lines.append(LineItem(**line_data))
    if lines:
        claim_data["lines"] = lines
        total_charges = _parse_charges(field_values.get("FL47_total_charges", ""))
        claim_data["total_charges"] = total_charges or sum(ln.charges for ln in lines)

    return Claim(**claim_data)


def _read_external_acroform(fields: dict[str, Any]) -> Claim:
    """Build a Claim from external AcroForm field values.

    Myelin does not write AcroForm fields; this exists to support UB04 PDFs
    created by other tools that expose interactive form data.
    """
    # AcroForm field names vary by PDF creator. We attempt common patterns.
    # Build a normalized lookup: lowercase field name → value
    normalized: dict[str, str] = {}
    for name, field_obj in fields.items():
        val = ""
        if isinstance(field_obj, dict):
            val = str(field_obj.get("/V", ""))
        elif hasattr(field_obj, "value"):
            val = str(field_obj.value) if field_obj.value else ""
        else:
            val = str(field_obj)
        # pypdf's None representation
        if val in ("None", "none", "/"):
            val = ""
        normalized[name.lower().strip()] = val.strip()

    def _find_field(*candidates: str) -> str:
        """Search for a field value by trying multiple name patterns."""
        for c in candidates:
            cl = c.lower().strip()
            if cl in normalized:
                return normalized[cl]
            # Try partial match
            for k, v in normalized.items():
                if cl in k and v:
                    return v
        return ""

    field_values = {
        "FL1_name": _find_field("1", "fl1", "provider_name"),
        "FL1_addr1": _find_field("1_addr1", "fl1_addr1", "provider_addr1"),
        "FL1_addr2": _find_field("1_addr2", "fl1_addr2", "provider_addr2"),
        "FL1_phone": _find_field("1_phone", "fl1_phone", "provider_phone"),
        "FL3a": _find_field("3a", "fl3a", "patient_control", "patcntl"),
        "FL3b": _find_field("3b", "fl3b", "med_rec", "mrn"),
        "FL4": _find_field("4", "fl4", "type_of_bill", "tob"),
        "FL5": _find_field("5", "fl5", "federal_tax_number", "fed_tax_no"),
        "FL6_from": _find_field("6_from", "fl6_from", "stmt_from"),
        "FL6_thru": _find_field("6_thru", "fl6_thru", "stmt_thru"),
        "FL8a": _find_field("8a", "fl8a", "patient_last"),
        "FL8b": _find_field("8b", "fl8b", "patient_first"),
        "FL9a": _find_field("9a", "fl9a", "patient_address1"),
        "FL9b": _find_field("9b", "fl9b", "patient_city"),
        "FL9c": _find_field("9c", "fl9c", "patient_state"),
        "FL9d": _find_field("9d", "fl9d", "patient_zip"),
        "FL9e": _find_field("9e", "fl9e", "patient_country"),
        "FL10": _find_field("10", "fl10", "patient_dob", "birthdate"),
        "FL11": _find_field("11", "fl11", "patient_sex", "sex"),
        "FL12": _find_field("12", "fl12", "admit_date"),
        "FL14": _find_field("14", "fl14", "admission_type"),
        "FL15": _find_field("15", "fl15", "source_admission"),
        "FL17": _find_field("17", "fl17", "patient_status", "discharge_status"),
        "FL56": _find_field("56", "fl56", "billing_npi", "npi"),
        "FL66": _find_field("66", "fl66", "dx_version"),
        "FL67": _find_field("67", "fl67", "principal_dx", "pdx"),
        "FL69": _find_field("69", "fl69", "admit_dx", "admitting_dx"),
        "FL76_npi": _find_field("76_npi", "fl76_npi", "attending_npi"),
        "FL76_last": _find_field("76_last", "fl76_last", "attending_last"),
        "FL76_first": _find_field("76_first", "fl76_first", "attending_first"),
        "FL80": _find_field("80", "fl80", "remarks"),
    }

    for letter_idx in range(17):
        letter = chr(ord("A") + letter_idx)
        field_values[f"FL67{letter}"] = _find_field(
            f"67{letter}", f"fl67{letter}", f"dx_{letter}"
        )

    for suffix in ("a", "b", "c"):
        field_values[f"FL70{suffix}"] = _find_field(
            f"70{suffix}", f"fl70{suffix}", f"reason_dx_{suffix}"
        )

    for i in range(18, 29):
        field_values[f"FL{i}"] = _find_field(str(i), f"fl{i}", f"cond_{i}")

    for slot in _OCCURRENCE_CODE_SLOTS:
        field_values[f"FL{slot}_code"] = _find_field(
            f"{slot}_code", f"fl{slot}_code", f"occ_{slot}_code"
        )
        field_values[f"FL{slot}_date"] = _find_field(
            f"{slot}_date", f"fl{slot}_date", f"occ_{slot}_date"
        )

    for slot in _SPAN_CODE_SLOTS:
        field_values[f"FL{slot}_code"] = _find_field(
            f"{slot}_code", f"fl{slot}_code", f"span_{slot}_code"
        )
        field_values[f"FL{slot}_from"] = _find_field(
            f"{slot}_from", f"fl{slot}_from", f"span_{slot}_from"
        )
        field_values[f"FL{slot}_thru"] = _find_field(
            f"{slot}_thru", f"fl{slot}_thru", f"span_{slot}_thru"
        )

    for slot in _VALUE_CODE_SLOTS:
        field_values[f"FL{slot}_code"] = _find_field(
            f"{slot}_code", f"fl{slot}_code", f"value_{slot}_code"
        )
        field_values[f"FL{slot}_amount"] = _find_field(
            f"{slot}_amount", f"fl{slot}_amount", f"value_{slot}_amount"
        )

    for slot in _PROCEDURE_SLOTS:
        field_values[f"FL{slot}_code"] = _find_field(
            f"{slot}_code", f"fl{slot}_code", f"proc_{slot}_code"
        )
        field_values[f"FL{slot}_date"] = _find_field(
            f"{slot}_date", f"fl{slot}_date", f"proc_{slot}_date"
        )

    for row in range(1, 23):
        field_values[f"FL42_{row}"] = _find_field(
            f"42_{row}", f"fl42_{row}", f"rev_{row}"
        )
        field_values[f"FL44_{row}"] = _find_field(
            f"44_{row}", f"fl44_{row}", f"hcpcs_{row}"
        )
        field_values[f"FL45_{row}"] = _find_field(
            f"45_{row}", f"fl45_{row}", f"svc_date_{row}"
        )
        field_values[f"FL46_{row}"] = _find_field(
            f"46_{row}", f"fl46_{row}", f"units_{row}"
        )
        field_values[f"FL47_{row}"] = _find_field(
            f"47_{row}", f"fl47_{row}", f"charges_{row}"
        )

    field_values["FL42_page"] = _find_field("42_page", "fl42_page", "page")
    field_values["FL42_pages_total"] = _find_field(
        "42_pages_total", "fl42_pages_total", "pages_total", "total_pages"
    )
    field_values["FL44_creation_date"] = _find_field(
        "44_creation_date", "fl44_creation_date", "creation_date"
    )
    field_values["FL47_total_charges"] = _find_field(
        "47_total_charges", "fl47_total_charges", "47_23", "fl47_23", "total_charges"
    )
    field_values["FL48_total_non_covered_charges"] = _find_field(
        "48_total_non_covered_charges",
        "fl48_total_non_covered_charges",
        "48_23",
        "fl48_23",
        "total_non_covered_charges",
    )

    return _build_claim_from_field_values(field_values)


def _read_from_text(reader: Any) -> Claim:
    """Build a Claim from text extraction with position-based field matching.

    This is a best-effort fallback for PDFs that don't have AcroForm fields.
    It extracts text fragments with their positions and maps them to FL fields
    based on coordinate proximity.
    """
    from myelin.input.claim import Claim

    from .ub04_coordinates import COORDINATES

    # Extract text with positions using visitor pattern
    text_fragments: list[tuple[str, float, float]] = []

    def visitor(text: str, cm: Any, tm: Any, font_dict: Any, font_size: float) -> None:
        if text.strip():
            # tm is the text matrix; tm[4]=x, tm[5]=y
            x = float(tm[4])
            y = float(tm[5])
            text_fragments.append((text.strip(), x, y))

    page = reader.pages[0]
    page.extract_text(visitor_text=visitor)

    if not text_fragments:
        logger.warning("No text fragments extracted from PDF")
        return Claim()

    # Match text fragments to FL fields by coordinate proximity
    tolerance = 8
    field_values: dict[str, str] = {}

    for fl_key, (fx, fy) in COORDINATES.items():
        best_text = ""
        best_dist = tolerance + 1
        for text, tx, ty in text_fragments:
            dist = ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_text = text
        if best_text and best_dist <= tolerance:
            field_values[fl_key] = best_text

    return _build_claim_from_field_values(field_values)
