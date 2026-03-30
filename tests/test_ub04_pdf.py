"""Tests for UB04 PDF reader/writer functionality."""

from datetime import datetime
from io import BytesIO

import pytest

from myelin.helpers.ub04_coordinates import COORDINATES
from myelin.helpers.ub04_field_map import (
    HEADER_MAPPINGS,
    _fmt_charges,
    _fmt_date_mmddyy,
    _fmt_date_mmddyyyy,
    _fmt_dx_code,
    _fmt_units,
    _parse_date_mmddyy,
    _parse_date_mmddyyyy,
    resolve_claim_value,
)
from myelin.helpers.ub04_pdf import (
    read_ub04_pdf,
    write_ub04_calibration_pdf,
    write_ub04_pdf,
)
from myelin.input.claim import (
    Claim,
    DiagnosisCode,
    LineItem,
    OccurrenceCode,
    Patient,
    PoaType,
    ProcedureCode,
    Provider,
    SpanCode,
    ValueCode,
)

# --- Fixtures ---


@pytest.fixture
def sample_claim() -> Claim:
    """Build a sample claim with diverse fields for testing."""
    claim = Claim()
    claim.claimid = "TEST001"
    claim.bill_type = "131"
    claim.from_date = datetime(2025, 7, 1)
    claim.thru_date = datetime(2025, 7, 10)
    claim.admit_date = datetime(2025, 7, 1)
    claim.patient_status = "01"
    claim.admission_source = "1"
    claim.total_charges = 1234.56

    # Patient
    claim.patient = Patient(
        last_name="DOE",
        first_name="JOHN",
        medical_record_number="MRN12345",
        date_of_birth=datetime(1960, 3, 15),
        sex="M",
    )

    # Provider
    claim.billing_provider = Provider(
        npi="1234567890",
        facility_name="TEST MEDICAL CENTER",
    )
    claim.billing_provider.address.address1 = "123 MAIN ST"
    claim.billing_provider.address.city = "ANYTOWN"
    claim.billing_provider.address.state = "AL"
    claim.billing_provider.address.zip = "36101"

    # Attending physician
    claim.servicing_provider = Provider(
        npi="9876543210",
        last_name="SMITH",
        first_name="JANE",
    )

    # Diagnoses
    claim.principal_dx = DiagnosisCode(code="A021", poa=PoaType.Y)
    claim.admit_dx = DiagnosisCode(code="A021")
    claim.secondary_dxs = [
        DiagnosisCode(code="I82411", poa=PoaType.N),
        DiagnosisCode(code="E1165", poa=PoaType.Y),
    ]
    claim.rfvdx = ["R109", "R197"]

    # Condition codes
    claim.cond_codes = ["15", "25"]

    # Value codes
    claim.value_codes = [
        ValueCode(code="59", amount=43.02),
        ValueCode(code="80", amount=100.00),
    ]

    # Occurrence codes
    claim.occurrence_codes = [
        OccurrenceCode(code="11", date=datetime(2025, 6, 28)),
    ]

    # Span codes
    claim.span_codes = [
        SpanCode(
            code="70", start_date=datetime(2025, 7, 1), end_date=datetime(2025, 7, 5)
        ),
    ]

    # Procedure codes
    claim.inpatient_pxs = [
        ProcedureCode(code="0016070", date=datetime(2025, 7, 2)),
    ]

    # Service lines
    claim.lines = [
        LineItem(
            service_date=datetime(2025, 7, 1),
            revenue_code="0360",
            hcpcs="29305",
            modifiers=["22"],
            units=1,
            charges=435.00,
        ),
        LineItem(
            service_date=datetime(2025, 7, 1),
            revenue_code="0610",
            hcpcs="72196",
            units=1,
            charges=140.67,
        ),
    ]

    return claim


# --- Transform function tests ---


class TestTransformFunctions:
    def test_fmt_date_mmddyy(self):
        assert _fmt_date_mmddyy(datetime(2025, 7, 1)) == "070125"
        assert _fmt_date_mmddyy(None) == ""

    def test_fmt_date_mmddyyyy(self):
        assert _fmt_date_mmddyyyy(datetime(1960, 3, 15)) == "03151960"
        assert _fmt_date_mmddyyyy(None) == ""

    def test_parse_date_mmddyy(self):
        result = _parse_date_mmddyy("070125")
        assert result is not None
        assert result.month == 7
        assert result.day == 1

    def test_parse_date_mmddyyyy(self):
        result = _parse_date_mmddyyyy("03151960")
        assert result is not None
        assert result.year == 1960
        assert result.month == 3
        assert result.day == 15

    def test_parse_date_empty(self):
        assert _parse_date_mmddyy("") is None
        assert _parse_date_mmddyyyy("") is None

    def test_fmt_charges(self):
        assert _fmt_charges(435.00) == "435.00"
        assert _fmt_charges(1234.56) == "1,234.56"
        assert _fmt_charges(0.0) == ""
        assert _fmt_charges(None) == ""

    def test_fmt_units(self):
        assert _fmt_units(1.0) == "1"
        assert _fmt_units(2.5) == "2.5"
        assert _fmt_units(0.0) == ""

    def test_fmt_dx_code(self):
        dx = DiagnosisCode(code="A021")
        assert _fmt_dx_code(dx) == "A021"
        assert _fmt_dx_code(None) == ""


# --- Field mapping tests ---


class TestFieldMapping:
    OPTIONAL_HEADER_COORDINATES = {"FL1_phone"}

    def test_resolve_simple_path(self, sample_claim):
        assert resolve_claim_value(sample_claim, "claimid") == "TEST001"
        assert resolve_claim_value(sample_claim, "bill_type") == "131"

    def test_resolve_nested_path(self, sample_claim):
        assert resolve_claim_value(sample_claim, "patient.last_name") == "DOE"
        assert resolve_claim_value(sample_claim, "billing_provider.npi") == "1234567890"

    def test_resolve_deep_nested_path(self, sample_claim):
        assert (
            resolve_claim_value(sample_claim, "billing_provider.address.address1")
            == "123 MAIN ST"
        )

    def test_resolve_additional_data(self, sample_claim):
        sample_claim.additional_data["fed_tax_no"] = "123456789"
        assert (
            resolve_claim_value(sample_claim, "additional_data.fed_tax_no")
            == "123456789"
        )

    def test_resolve_missing_path(self, sample_claim):
        assert resolve_claim_value(sample_claim, "nonexistent.field") is None

    def test_all_header_mappings_have_coordinates(self):
        """Every header mapping's fl_key should exist in COORDINATES."""
        missing = []
        for m in HEADER_MAPPINGS:
            if (
                m.fl_key not in COORDINATES
                and m.fl_key not in self.OPTIONAL_HEADER_COORDINATES
            ):
                missing.append(m.fl_key)
        assert not missing, f"Header mappings missing coordinates: {missing}"


# --- Coordinate tests ---


class TestCoordinates:
    def test_coordinates_within_page_bounds(self):
        from myelin.helpers.ub04_coordinates import PAGE_HEIGHT, PAGE_WIDTH

        for key, (x, y) in COORDINATES.items():
            assert 0 <= x <= PAGE_WIDTH, f"{key} x={x} out of bounds"
            assert 0 <= y <= PAGE_HEIGHT, f"{key} y={y} out of bounds"

    def test_service_line_coordinates_generated(self):
        for i in range(1, 23):
            assert f"FL42_{i}" in COORDINATES
            assert f"FL47_{i}" in COORDINATES
        assert "FL42_page" in COORDINATES
        assert "FL42_pages_total" in COORDINATES
        assert "FL44_creation_date" in COORDINATES
        assert "FL47_total_charges" in COORDINATES
        assert "FL48_total_non_covered_charges" in COORDINATES

    def test_diagnosis_coordinates_exist(self):
        assert "FL67" in COORDINATES
        for letter in "ABCDEFGHIJKLMNOPQ":
            assert f"FL67{letter}" in COORDINATES


# --- Write tests ---


class TestWriteUB04:
    def test_write_returns_valid_pdf(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 1000

    def test_write_to_file(self, sample_claim, tmp_path):
        out = tmp_path / "test.pdf"
        pdf_bytes = write_ub04_pdf(sample_claim, output_path=str(out))
        assert out.exists()
        assert out.read_bytes() == pdf_bytes

    def test_write_minimal_claim(self):
        """A claim with almost no fields should still produce valid PDF."""
        claim = Claim()
        pdf_bytes = write_ub04_pdf(claim)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_write_max_lines(self):
        """Claim with 22+ lines should not error (truncates with warning)."""
        claim = Claim()
        claim.from_date = datetime(2025, 1, 1)
        claim.thru_date = datetime(2025, 1, 31)
        for i in range(25):
            claim.lines.append(
                LineItem(
                    service_date=datetime(2025, 1, 1),
                    revenue_code=f"{i:04d}",
                    hcpcs="99213",
                    units=1,
                    charges=100.00,
                )
            )
        pdf_bytes = write_ub04_pdf(claim)
        assert pdf_bytes[:5] == b"%PDF-"


class TestWriteUB04Calibration:
    def test_write_calibration_returns_valid_pdf(self):
        pdf_bytes = write_ub04_calibration_pdf()
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 1000

    def test_write_calibration_to_file(self, tmp_path):
        from pypdf import PdfReader

        out = tmp_path / "ub04_calibration.pdf"
        pdf_bytes = write_ub04_calibration_pdf(output_path=str(out))
        assert out.exists()
        assert out.read_bytes() == pdf_bytes

        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        assert text is not None
        assert "FL1" in text
        assert "FL31a" in text
        assert "FL47" in text
        assert "FL79" in text
        assert "FL1_name" not in text
        assert "FL47_totals" not in text
        assert "FL79_npi" not in text


# --- Read tests ---


class TestReadUB04:
    def test_read_from_written_pdf(self, sample_claim):
        """Write a PDF and read it back — key fields should match."""
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))

        assert claim2.claimid == sample_claim.claimid
        assert claim2.bill_type == sample_claim.bill_type
        assert claim2.patient.last_name == sample_claim.patient.last_name
        assert claim2.patient.first_name == sample_claim.patient.first_name

    def test_read_principal_dx(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))
        assert claim2.principal_dx is not None
        assert claim2.principal_dx.code == "A021"

    def test_read_provider_npi(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))
        assert claim2.billing_provider is not None
        assert claim2.billing_provider.npi == "1234567890"

    def test_read_service_lines(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))
        assert len(claim2.lines) >= 1  # At least some lines should be extracted

    def test_read_service_line_modifiers(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))
        assert claim2.lines[0].hcpcs == sample_claim.lines[0].hcpcs
        assert claim2.lines[0].modifiers == sample_claim.lines[0].modifiers

    def test_read_repeated_claim_sections(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))

        assert claim2.rfvdx == sample_claim.rfvdx
        assert claim2.cond_codes == sample_claim.cond_codes

        assert len(claim2.value_codes) == len(sample_claim.value_codes)
        assert claim2.value_codes[0].code == sample_claim.value_codes[0].code
        assert claim2.value_codes[0].amount == sample_claim.value_codes[0].amount

        assert len(claim2.occurrence_codes) == len(sample_claim.occurrence_codes)
        assert claim2.occurrence_codes[0].code == sample_claim.occurrence_codes[0].code
        assert claim2.occurrence_codes[0].date == sample_claim.occurrence_codes[0].date

        assert len(claim2.span_codes) == len(sample_claim.span_codes)
        assert claim2.span_codes[0].code == sample_claim.span_codes[0].code
        assert claim2.span_codes[0].start_date == sample_claim.span_codes[0].start_date
        assert claim2.span_codes[0].end_date == sample_claim.span_codes[0].end_date

        assert len(claim2.inpatient_pxs) == len(sample_claim.inpatient_pxs)
        assert claim2.inpatient_pxs[0].code == sample_claim.inpatient_pxs[0].code
        assert claim2.inpatient_pxs[0].date == sample_claim.inpatient_pxs[0].date

    def test_read_from_bytesio(self, sample_claim):
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))
        assert claim2.claimid == "TEST001"

    def test_read_empty_pdf(self):
        """Reading the blank template should return a mostly-empty claim."""
        from myelin.helpers.ub04_pdf import _BLANK_TEMPLATE

        claim = read_ub04_pdf(str(_BLANK_TEMPLATE))
        # Should not raise, and should return a valid Claim
        assert isinstance(claim, Claim)


# --- Round-trip tests ---


class TestRoundTrip:
    def test_roundtrip_key_fields(self, sample_claim):
        """Write then read — mapped fields should survive the round trip."""
        pdf_bytes = write_ub04_pdf(sample_claim)
        claim2 = read_ub04_pdf(BytesIO(pdf_bytes))

        assert claim2.claimid == sample_claim.claimid
        assert claim2.bill_type == sample_claim.bill_type
        assert claim2.patient_status == sample_claim.patient_status
        assert claim2.patient.last_name == sample_claim.patient.last_name
        assert claim2.patient.first_name == sample_claim.patient.first_name
        assert (
            claim2.patient.medical_record_number
            == sample_claim.patient.medical_record_number
        )

        assert claim2.principal_dx is not None
        assert claim2.principal_dx.code == sample_claim.principal_dx.code

        assert claim2.billing_provider is not None
        assert claim2.billing_provider.npi == sample_claim.billing_provider.npi

        assert claim2.rfvdx == sample_claim.rfvdx
        assert claim2.cond_codes == sample_claim.cond_codes

        assert claim2.lines[0].hcpcs == sample_claim.lines[0].hcpcs
        assert claim2.lines[0].modifiers == sample_claim.lines[0].modifiers

        assert len(claim2.value_codes) == len(sample_claim.value_codes)
        assert claim2.value_codes[0].code == sample_claim.value_codes[0].code
        assert claim2.value_codes[0].amount == sample_claim.value_codes[0].amount

        assert len(claim2.occurrence_codes) == len(sample_claim.occurrence_codes)
        assert claim2.occurrence_codes[0].code == sample_claim.occurrence_codes[0].code

        assert len(claim2.span_codes) == len(sample_claim.span_codes)
        assert claim2.span_codes[0].code == sample_claim.span_codes[0].code

        assert len(claim2.inpatient_pxs) == len(sample_claim.inpatient_pxs)
        assert claim2.inpatient_pxs[0].code == sample_claim.inpatient_pxs[0].code

    def test_roundtrip_via_claim_methods(self, sample_claim, tmp_path):
        """Test the Claim.to_ub04_pdf / Claim.from_ub04_pdf convenience methods."""
        out = tmp_path / "roundtrip.pdf"
        sample_claim.to_ub04_pdf(filepath=str(out))
        claim2 = Claim.from_ub04_pdf(str(out))
        assert claim2.claimid == sample_claim.claimid
        assert claim2.bill_type == sample_claim.bill_type
