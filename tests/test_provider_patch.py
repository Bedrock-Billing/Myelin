"""Tests for IPSF and OPSF patch methods."""

import os
import tempfile
from datetime import datetime
from unittest.mock import patch

from myelin.pricers.ipsf import DATATYPES as IPSF_DATATYPES
from myelin.pricers.ipsf import IPSF, IPSFDatabase
from myelin.pricers.opsf import DATATYPES as OPSF_DATATYPES
from myelin.pricers.opsf import OPSF, OPSFDatabase


class TestIPSFPatch:
    """Test IPSFDatabase.patch() method."""

    def test_patch_empty_table_calls_populate_with_truncate(self):
        """When table is empty, patch should call populate with truncate=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = IPSFDatabase(db_path=db_path)

            with patch.object(db, "populate", return_value=100) as mock_populate:
                result = db.patch()

                mock_populate.assert_called_once_with(
                    download=True, batch_size=4000, truncate=True
                )
                assert result == 100

    def test_patch_with_existing_data_calculates_next_day(self):
        """When table has data, patch should calculate next day and perform upsert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = IPSFDatabase(db_path=db_path)

            # Insert a test record with a known last_updated date
            last_date = datetime(2024, 1, 15)
            with db.session() as sess:
                record = IPSF(
                    provider_ccn="123456",
                    effective_date=20240101,
                    last_updated=last_date.strftime("%Y-%m-%d"),
                )
                sess.add(record)
                sess.commit()

            # Create a minimal CSV file for the patch to read
            csv_content = (
                "provider_ccn,effective_date,fiscal_year_begin_date,export_date,termination_date,waiver_indicator,intermediary_number,provider_type,census_division,msa_actual_geographic_location,msa_wage_index_location,msa_standardized_amount_location,sole_community_or_medicare_dependent_hospital_base_year,change_code_for_lugar_reclassification,temporary_relief_indicator,federal_pps_blend,state_code,pps_facility_specific_rate,cost_of_living_adjustment,interns_to_beds_ratio,bed_size,operating_cost_to_charge_ratio,case_mix_index,supplemental_security_income_ratio,medicaid_ratio,special_provider_update_factor,operating_dsh,fiscal_year_end_date,special_payment_indicator,hosp_quality_indicator,cbsa_actual_geographic_location,cbsa_wi_location,cbsa_standardized_amount_location,special_wage_index,pass_through_amount_for_capital,pass_through_amount_for_direct_medical_education,pass_through_amount_for_organ_acquisition,pass_through_total_amount,capital_pps_payment_code,hospital_specific_capital_rate,old_capital_hold_harmless_rate,new_capital_hold_harmless_rate,capital_cost_to_charge_ratio,new_hospital,capital_indirect_medical_education_ratio,capital_exception_payment_rate,vpb_participant_indicator,vbp_adjustment,hrr_participant_indicator,hrr_adjustment,bundle_model_discount,hac_reduction_participant_indicator,uncompensated_care_amount,ehr_reduction_indicator,low_volume_adjustment_factor,county_code,medicare_performance_adjustment,ltch_dpp_indicator,supplemental_wage_index,supplemental_wage_index_indicator,change_code_wage_index_reclassification,national_provider_identifier,pass_through_amount_for_allogenic_stem_cell_acquisition,pps_blend_year_indicator,last_updated,pass_through_amount_for_direct_graduate_medical_education,pass_through_amount_for_kidney_acquisition,pass_through_amount_for_supply_chain\n"
                "789012,20240201,20240201,20240215,20241231,,,TEST_TYPE,,,,,,,,,TX,0.0,0.0,0.0,100,0.5,1.2,0.1,0.2,0.0,0.0,20241231,,,,,,,,0.0,0.0,0.0,0.0,,0.0,0.0,0.0,0.0,,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,,,,,,,,,,,,,2024-01-20,0.0,0.0,0.0,\n"
            )
            csv_path = os.path.join(tmpdir, "ipsf_data.csv")
            with open(csv_path, "w") as f:
                f.write(csv_content)

            # Mock download to do nothing (we already created the CSV)
            with patch.object(db, "download") as mock_download:
                result = db.patch()

                # Verify download was called (URL should have fromDate = 2024-01-16)
                mock_download.assert_called_once()
                call_args = mock_download.call_args
                assert "url" in call_args.kwargs
                url = call_args.kwargs["url"]
                assert "fromDate=2024-01-16" in url

            # Verify the new record was inserted
            with db.session() as sess:
                new_record = (
                    sess.query(IPSF)
                    .filter_by(provider_ccn="789012", effective_date=20240201)
                    .first()
                )
                assert new_record is not None
                assert new_record.provider_type == "TEST_TYPE"

            assert result == 1

    def test_patch_handles_invalid_date_format(self):
        """When last_updated has invalid format, patch should fall back to full populate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = IPSFDatabase(db_path=db_path)

            # Insert a test record with invalid date format
            with db.session() as sess:
                record = IPSF(
                    provider_ccn="123456",
                    effective_date=20240101,
                    last_updated="invalid-date",
                )
                sess.add(record)
                sess.commit()

            with patch.object(db, "populate", return_value=100) as mock_populate:
                result = db.patch()

                # Should fall back to full populate with truncate=True
                mock_populate.assert_called_once_with(
                    download=True, batch_size=4000, truncate=True
                )
                assert result == 100

    def test_patch_upserts_existing_records(self):
        """When patching, existing records with same provider_ccn + effective_date should be replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = IPSFDatabase(db_path=db_path)

            # Insert an existing record
            with db.session() as sess:
                old_record = IPSF(
                    provider_ccn="123456",
                    effective_date=20240101,
                    last_updated="2024-01-10",
                    provider_type="OLD_TYPE",
                    state_code="CA",
                )
                sess.add(old_record)
                sess.commit()

            # Create a CSV with updated data for the same provider_ccn + effective_date
            # Build the CSV programmatically to ensure correct field count
            fields = list(IPSF_DATATYPES.keys())
            csv_values = {field: "" for field in fields}
            csv_values["provider_ccn"] = "123456"
            csv_values["effective_date"] = "20240101"
            csv_values["provider_type"] = "NEW_TYPE"
            csv_values["state_code"] = "NY"
            csv_values["last_updated"] = "2024-01-20"

            csv_header = ",".join(fields)
            csv_data = ",".join(str(csv_values[field]) for field in fields)
            csv_content = f"{csv_header}\n{csv_data}\n"

            csv_path = os.path.join(tmpdir, "ipsf_data.csv")
            with open(csv_path, "w") as f:
                f.write(csv_content)

            # Mock download to do nothing (we already created the CSV)
            with patch.object(db, "download"):
                result = db.patch()

            # Verify the record was updated, not duplicated
            with db.session() as sess:
                records = (
                    sess.query(IPSF)
                    .filter_by(provider_ccn="123456", effective_date=20240101)
                    .all()
                )

                assert len(records) == 1, (
                    "Should have exactly one record (upserted, not duplicated)"
                )
                updated_record = records[0]
                assert updated_record.provider_type == "NEW_TYPE", (
                    "Provider type should be updated"
                )
                assert updated_record.state_code == "NY", "State code should be updated"
                assert updated_record.last_updated == "2024-01-20", (
                    "Last updated should be updated"
                )

            assert result == 1


class TestOPSFPatch:
    """Test OPSFDatabase.patch() method."""

    def test_patch_empty_table_calls_populate_with_truncate(self):
        """When table is empty, patch should call populate with truncate=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = OPSFDatabase(db_path=db_path)

            with patch.object(db, "populate", return_value=100) as mock_populate:
                result = db.patch()

                mock_populate.assert_called_once_with(
                    download=True, batch_size=5000, truncate=True
                )
                assert result == 100

    def test_patch_with_existing_data_calculates_next_day(self):
        """When table has data, patch should calculate next day and perform upsert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = OPSFDatabase(db_path=db_path)

            # Insert a test record with a known last_updated date
            last_date = datetime(2024, 2, 20)
            with db.session() as sess:
                record = OPSF(
                    provider_ccn="654321",
                    effective_date=20240201,
                    last_updated=last_date.strftime("%Y-%m-%d"),
                )
                sess.add(record)
                sess.commit()

            # Create a minimal CSV file for the patch to read
            fields = list(OPSF_DATATYPES.keys())
            csv_values = {field: "" for field in fields}
            csv_values["provider_ccn"] = "987654"
            csv_values["effective_date"] = "20240301"
            csv_values["provider_type"] = "TEST_TYPE"
            csv_values["last_updated"] = "2024-02-25"

            csv_header = ",".join(fields)
            csv_data = ",".join(str(csv_values[field]) for field in fields)
            csv_content = f"{csv_header}\n{csv_data}\n"

            csv_path = os.path.join(tmpdir, "opsf_data.csv")
            with open(csv_path, "w") as f:
                f.write(csv_content)

            # Mock download to do nothing (we already created the CSV)
            with patch.object(db, "download") as mock_download:
                result = db.patch()

                # Verify download was called (URL should have fromDate = 2024-02-21)
                mock_download.assert_called_once()
                call_args = mock_download.call_args
                assert "url" in call_args.kwargs
                url = call_args.kwargs["url"]
                assert "fromDate=2024-02-21" in url

            # Verify the new record was inserted
            with db.session() as sess:
                new_record = (
                    sess.query(OPSF)
                    .filter_by(provider_ccn="987654", effective_date=20240301)
                    .first()
                )
                assert new_record is not None
                assert new_record.provider_type == "TEST_TYPE"

            assert result == 1

    def test_patch_handles_invalid_date_format(self):
        """When last_updated has invalid format, patch should fall back to full populate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = OPSFDatabase(db_path=db_path)

            # Insert a test record with invalid date format
            with db.session() as sess:
                record = OPSF(
                    provider_ccn="654321",
                    effective_date=20240201,
                    last_updated="not-a-date",
                )
                sess.add(record)
                sess.commit()

            with patch.object(db, "populate", return_value=100) as mock_populate:
                result = db.patch()

                # Should fall back to full populate with truncate=True
                mock_populate.assert_called_once_with(
                    download=True, batch_size=5000, truncate=True
                )
                assert result == 100

    def test_patch_upserts_existing_records(self):
        """When patching, existing records with same provider_ccn + effective_date should be replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = OPSFDatabase(db_path=db_path)

            # Insert an existing record
            with db.session() as sess:
                old_record = OPSF(
                    provider_ccn="654321",
                    effective_date=20240201,
                    last_updated="2024-02-10",
                    provider_type="OLD_TYPE",
                    state_code="TX",
                )
                sess.add(old_record)
                sess.commit()

            # Create a CSV with updated data for the same provider_ccn + effective_date
            fields = list(OPSF_DATATYPES.keys())
            csv_values = {field: "" for field in fields}
            csv_values["provider_ccn"] = "654321"
            csv_values["effective_date"] = "20240201"
            csv_values["provider_type"] = "NEW_TYPE"
            csv_values["state_code"] = "FL"
            csv_values["last_updated"] = "2024-02-25"

            csv_header = ",".join(fields)
            csv_data = ",".join(str(csv_values[field]) for field in fields)
            csv_content = f"{csv_header}\n{csv_data}\n"

            csv_path = os.path.join(tmpdir, "opsf_data.csv")
            with open(csv_path, "w") as f:
                f.write(csv_content)

            # Mock download to do nothing (we already created the CSV)
            with patch.object(db, "download"):
                result = db.patch()

            # Verify the record was updated, not duplicated
            with db.session() as sess:
                records = (
                    sess.query(OPSF)
                    .filter_by(provider_ccn="654321", effective_date=20240201)
                    .all()
                )

                assert len(records) == 1, (
                    "Should have exactly one record (upserted, not duplicated)"
                )
                updated_record = records[0]
                assert updated_record.provider_type == "NEW_TYPE", (
                    "Provider type should be updated"
                )
                assert updated_record.state_code == "FL", "State code should be updated"
                assert updated_record.last_updated == "2024-02-25", (
                    "Last updated should be updated"
                )

            assert result == 1
