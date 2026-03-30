from datetime import datetime

from myelin import Claim
from myelin.helpers.claim_examples import (
    opps_claim_example,
)
from myelin.input import (
    Provider,
)


def build_provider() -> Provider:
    provider = Provider(
        npi="1234567890",
        other_id="010001",
        facility_name="MYELIN OUTPATIENT SURGERY CENTER",
    )
    provider.address.address1 = "123 MAIN ST"
    provider.address.address2 = "STE 200"
    provider.address.city = "BIRMINGHAM"
    provider.address.state = "AL"
    provider.address.zip = "35203"
    provider.address.phone = "2055550100"
    return provider


def build_claim() -> Claim:
    opps_claim = opps_claim_example()
    opps_claim.claimid = "001"
    opps_claim.billing_provider = build_provider()
    opps_claim.patient.first_name = "JOHN"
    opps_claim.patient.last_name = "DOE"
    opps_claim.patient.medical_record_number = "MRN123456"
    opps_claim.patient.date_of_birth = datetime(1960, 3, 15)
    opps_claim.patient.address.address1 = "456 OAK AVE"
    opps_claim.patient.address.city = "BIRMINGHAM"
    opps_claim.patient.address.state = "AL"
    opps_claim.patient.address.zip = "35209"
    opps_claim.admit_date = opps_claim.from_date
    opps_claim.total_charges = sum(line.charges for line in opps_claim.lines)
    opps_claim.additional_data["fed_tax_no"] = "123456789"
    opps_claim.additional_data["admission_type"] = "1"
    opps_claim.additional_data["dx_version"] = "0"
    opps_claim.additional_data["remarks"] = "Form test claim"

    return opps_claim


def main():
    opps_claim = build_claim()
    opps_claim.to_ub04_pdf("opps_claim.pdf")


if __name__ == "__main__":
    main()
