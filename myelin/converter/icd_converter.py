import json
import os
import zipfile
from datetime import datetime
from typing import Optional

import requests
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    Date,
    Engine,
    Integer,
    String,
    asc,
    create_engine,
    desc,
)
from sqlalchemy.orm import declarative_base, sessionmaker

import myelin.converter.parse_icd_table as parse_icd_table
from myelin.input.claim import Claim, ICDConvertOption

CMS_URL = "https://www.cms.gov/files/zip/{year}-conversion-table.zip"
CMS_PCS_URL = "https://www.cms.gov/files/zip/{year}-icd-10-pcs-conversion-table.zip"

Base = declarative_base()


class ICD10ConvertOutput(BaseModel):
    target_version: Optional[str] = None
    billed_version: Optional[str] = None
    mappings: dict[str, Optional["ICD10CodeOutput"]] = Field(default_factory=dict)


class ICD10CodeOutput(BaseModel):
    original_code: Optional[str] = None
    conversion_choices: Optional[list[str]] = Field(default_factory=list)


class ICD10Conversion(Base):
    __tablename__ = "icd10_conversion"
    id = Column(Integer, primary_key=True)
    previous_code = Column(String, index=True)
    current_code = Column(String, index=True)
    effective_date = Column(Date, index=True)
    code_type = Column(
        Integer, index=True, default=0
    )  # 0 for ICD-10-CM, 1 for ICD-10-PCS

    def __repr__(self):
        return f"<ICD10Conversion(previous_code='{self.previous_code}', current_code='{self.current_code}', effective_date='{self.effective_date}')>"


def create_database(db_uri) -> Engine:
    """Creates the database and tables."""
    engine = create_engine(db_uri)
    Base.metadata.create_all(engine)
    return engine


def populate_database(db: Engine, json_path: str):
    """Populates the database from the parsed JSON file."""
    Session = sessionmaker(bind=db)
    session = Session()

    with open(json_path, "r") as f:
        for line in f:
            data = json.loads(line)
            current_code = data["current_code"]
            effective_date = datetime.strptime(
                data["effective_date"], "%Y-%m-%d"
            ).date()

            for prev_code in data["previous_codes"]:
                conversion_record = ICD10Conversion(
                    previous_code=prev_code.replace(".", ""),
                    current_code=current_code.replace(".", ""),
                    effective_date=effective_date,
                )
                session.add(conversion_record)

    session.commit()
    session.close()


def populate_database_pcs(db: Engine, txt_path: str):
    """Populates the database from the parsed PCS text file."""
    Session = sessionmaker(bind=db)
    session = Session()

    with open(txt_path, "r") as f:
        # File Header as of 9/2025
        # Current code(s) assignment	Code title	Effective year	Previous code(s) assignment	Predecessor code title	Change type	Comment	Effective month/day [MM.DD]
        next(f)  # Skip header line
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 8:
                continue  # Skip malformed lines

            current_code = parts[0]
            effective_year = parts[2]
            previous_codes = parts[3].split(",") if parts[3] else []
            effective_month_day = parts[7]
            if (
                current_code.lower() == "nopcs"
                or previous_codes[0].lower() == "nopcs"
                or current_code == previous_codes[0]
            ):
                continue  # Skip invalid codes

            if effective_year.isdigit() and len(effective_year) == 4:
                year = int(effective_year)
                if effective_month_day and "." in effective_month_day:
                    month, day = map(int, effective_month_day.split("."))
                else:
                    month, day = 1, 1  # Default to January 1st if not provided

                effective_date = datetime(year, month, day).date()

                for prev_code in previous_codes:
                    conversion_record = ICD10Conversion(
                        previous_code=prev_code.replace(".", ""),
                        current_code=current_code.replace(".", ""),
                        effective_date=effective_date,
                        code_type=1,  # Indicate this is an ICD-10-PCS code
                    )
                    session.add(conversion_record)
    session.commit()
    session.close()


class ICDConverter:
    def __init__(self, db: Engine):
        """
        ICDConverter class is used to forward and backward convert ICD-10 codes.
        """
        self.engine = db
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def download_icd_conversion_file(self):
        """
        Downloads the latest ICD-10 conversion file from CMS and loads to the SQL database,
        on the class instance.
        """
        # clear the icd10_conversion table
        session = self.Session()
        session.query(ICD10Conversion).delete()
        session.commit()
        session.close()
        now = datetime.now()
        year = now.year + 1
        # first check if a new conversion for next fiscal year is released
        response = requests.head(CMS_URL.format(year=str(year)))
        pcs_response = requests.head(CMS_PCS_URL.format(year=str(year)))
        if response.status_code != 200 and pcs_response.status_code != 200:
            year -= 1  # fallback to current fiscal year
            response = requests.head(CMS_URL.format(year=str(year)))
            pcs_response = requests.head(CMS_PCS_URL.format(year=str(year)))
            if response.status_code != 200 and pcs_response.status_code != 200:
                raise Exception(
                    "No ICD-10 conversion file found for current or next fiscal year."
                )
        if response.status_code == 200 and pcs_response.status_code == 200:
            # Download the file
            response = requests.get(CMS_URL.format(year=str(year)))
            with open(f"icd_conversion_{year}.zip", "wb") as f:
                f.write(response.content)
            pcs_response = requests.get(CMS_PCS_URL.format(year=str(year)))
            with open(f"icd_pcs_conversion_{year}.zip", "wb") as f:
                f.write(pcs_response.content)
            # find the .txt in the .zip and extract it, ignore all else
            txt_file = None
            pcs_txt_file = None
            with zipfile.ZipFile(f"icd_conversion_{year}.zip", "r") as zip_ref:
                for file in zip_ref.namelist():
                    if file.endswith(".txt"):
                        zip_ref.extract(file, f"icd_conversion_{year}")
                        txt_file = file
                        break
            with zipfile.ZipFile(f"icd_pcs_conversion_{year}.zip", "r") as zip_ref:
                for file in zip_ref.namelist():
                    if file.endswith(".txt"):
                        zip_ref.extract(file, f"icd_pcs_conversion_{year}")
                        pcs_txt_file = file
                        break
            if txt_file:
                parsed_data = parse_icd_table.parse_icd_conversion_table(
                    f"./icd_conversion_{year}/{txt_file}"
                )
                with open("./parsed_data.json", "w") as f:
                    for entry in parsed_data:
                        f.write(json.dumps(entry) + "\n")
                populate_database(self.engine, "./parsed_data.json")
                # Optionally, you can remove the zip file after extraction
                os.remove(f"icd_conversion_{year}.zip")
                os.remove(f"icd_conversion_{year}/{txt_file}")
                os.remove("./parsed_data.json")
                os.rmdir(f"icd_conversion_{year}")
            if pcs_txt_file:
                populate_database_pcs(
                    self.engine, f"./icd_pcs_conversion_{year}/{pcs_txt_file}"
                )
                # Optionally, you can remove the zip file after extraction
                os.remove(f"icd_pcs_conversion_{year}.zip")
                os.remove(f"icd_pcs_conversion_{year}/{pcs_txt_file}")
                os.rmdir(f"icd_pcs_conversion_{year}")

    def convert_backward(
        self, code, as_of_date, code_type: int = 0
    ) -> Optional[ICD10CodeOutput]:
        """
        Converts a current ICD code to its previous version based on a given date.
        """
        session = self.Session()
        if isinstance(as_of_date, datetime):
            query_date = as_of_date.date()
        else:
            query_date = datetime.strptime(as_of_date, "%Y-%m-%d").date()

        result = (
            session.query(ICD10Conversion)
            .filter(
                ICD10Conversion.current_code == code.replace(".", ""),
                ICD10Conversion.effective_date > query_date,
                ICD10Conversion.code_type == code_type,
            )
            .order_by(desc(ICD10Conversion.effective_date))
            .first()
        )

        session.close()

        if result:
            return ICD10CodeOutput(
                original_code=code, conversion_choices=[result.previous_code]
            )
        return None

    def convert_forward(
        self, code, as_of_date, code_type: int = 0
    ) -> Optional[ICD10CodeOutput]:
        """
        Converts a previous ICD code to its current version(s) based on a given date.
        """
        session = self.Session()
        if isinstance(as_of_date, datetime):
            query_date = as_of_date.date()
        else:
            query_date = datetime.strptime(as_of_date, "%Y-%m-%d").date()

        results = (
            session.query(ICD10Conversion)
            .filter(
                ICD10Conversion.previous_code == code.replace(".", ""),
                ICD10Conversion.effective_date <= query_date,
                ICD10Conversion.code_type == code_type,
            )
            .order_by(asc(ICD10Conversion.effective_date))
            .all()
        )

        session.close()

        if results:
            return ICD10CodeOutput(
                original_code=code,
                conversion_choices=[res.current_code for res in results],
            )
        return None

    def determine_drg_version(self, date: datetime):
        """
        Determine the DRG version based on the date provided.
        """
        if not isinstance(date, datetime):
            raise ValueError("Date must be a datetime object")

        year = date.year - 1983
        if date.month >= 10:
            return f"{year + 1}0"
        elif date.month > 3:
            return f"{year}1"
        else:
            return f"{year - 1}0"

    def generate_claim_mappings(
        self, claim: Claim, target_vers: Optional[str] = None
    ) -> ICD10ConvertOutput:
        """
        Generate ICD-10 code mappings for a given claim.
        Asserts that claim.thru_date must be provided.
        Asserts that claim.principal_dx must be provided.
        """
        # Determine if we need to do ICD-10 code conversions/mappings
        assert claim.thru_date is not None, "Claim thru_date must be provided"
        assert claim.principal_dx is not None, "Claim principal_dx must be provided"
        mappings = {}
        output = ICD10ConvertOutput()
        if claim.icd_convert is not None:
            if claim.icd_convert.option == ICDConvertOption.MANUAL:
                if (
                    claim.icd_convert.target_version is not None
                    and claim.icd_convert.target_version.isnumeric()
                    and claim.icd_convert.billed_version is not None
                    and claim.icd_convert.billed_version.isnumeric()
                ):
                    target_version_int = int(claim.icd_convert.target_version[0:2], 10)
                    target_eff_year = target_version_int + 1983
                    if claim.icd_convert.target_version.endswith("1"):
                        target_eff_date = datetime(target_eff_year, 4, 1)
                    else:
                        target_eff_date = datetime(target_eff_year - 1, 10, 1)
                    billed_version = int(claim.icd_convert.billed_version[0:2], 10)
                    output.billed_version = claim.icd_convert.billed_version
                    output.target_version = claim.icd_convert.target_version
                else:
                    raise ValueError(
                        "ICD convert target_version and billed_version must be provided for MANUAL option"
                    )
        if (
            claim.icd_convert is None
            or claim.icd_convert.option == ICDConvertOption.AUTO
        ):  # <- We assume auto if claim.icd_convert is None
            if target_vers is None:
                raise ValueError("Target version must be provided for AUTO option")
            billed_version = int(
                self.determine_drg_version(claim.thru_date)[0:2], 10
            )  # <- It's assumed the billed version is the version for discharge date
            target_version_int = int(target_vers[0:2], 10)
            target_eff_year = target_version_int + 1983
            if target_vers.endswith("1"):
                target_eff_date = datetime(target_eff_year, 4, 1)
            else:
                target_eff_date = datetime(target_eff_year - 1, 10, 1)
            output.target_version = target_vers
            output.billed_version = self.determine_drg_version(claim.thru_date)

        if target_version_int >= 100 or billed_version >= 100:
            raise ValueError("Invalid ICD version")

        # @TODO this is probably somewhat inefficient, we run 1 query for every DX code
        # it might make more sense to do a bulk query with an "in" clause that way we get all results
        # in 1 sweep
        if target_version_int < billed_version:  # type: ignore
            # We're mapping backwards
            mappings[claim.principal_dx.code] = self.convert_backward(
                claim.principal_dx.code, target_eff_date, 0
            )
            if claim.admit_dx is not None:
                mappings[claim.admit_dx.code] = self.convert_backward(
                    claim.admit_dx.code, target_eff_date, 0
                )
            for dx in claim.secondary_dxs:
                if dx.code not in mappings:
                    mapping = self.convert_backward(dx.code, target_eff_date, 0)
                    if mapping is not None and mapping.conversion_choices is not None:
                        mappings[dx.code] = mapping
            for op in claim.inpatient_pxs:
                if op.code not in mappings:
                    mapping = self.convert_backward(op.code, target_eff_date, 1)
                    if mapping is not None and mapping.conversion_choices is not None:
                        mappings[op.code] = mapping
        elif target_version_int > billed_version:  # type: ignore
            mappings[claim.principal_dx.code] = self.convert_forward(
                claim.principal_dx.code, target_eff_date, 0
            )
            if claim.admit_dx is not None:
                mappings[claim.admit_dx.code] = self.convert_forward(
                    claim.admit_dx.code, target_eff_date, 0
                )
            # We're mapping forwards
            for dx in claim.secondary_dxs:
                if dx.code not in mappings:
                    mapping = self.convert_forward(dx.code, target_eff_date, 0)
                    if mapping is not None:
                        if mapping.conversion_choices is not None:
                            mappings[dx.code] = mapping
            for op in claim.inpatient_pxs:
                if op.code not in mappings:
                    mapping = self.convert_forward(op.code, target_eff_date, 1)
                    if mapping is not None:
                        if mapping.conversion_choices is not None:
                            mappings[op.code] = mapping
        output.mappings = mappings
        return output
