from pydantic import BaseModel, field_validator


class IrfPai(BaseModel):
    assessment_system: str | None = "IRF-PAI"
    transaction_type: int | None = 1
    impairment_admit_group_code: str | None = None
    # variable names for assessment items taken from Appendix A of CMG Grouper Program Documentation pdf
    eating_self_admsn_cd: str | None = None
    oral_hygne_admsn_cd: str | None = None
    toileting_hygne_admsn_cd: str | None = None
    bathing_hygne_admsn_cd: str | None = None
    upper_body_dressing_cd: str | None = None
    lower_body_dressing_cd: str | None = None
    footwear_dressing_cd: str | None = None
    sit_to_lying_cd: str | None = None
    lying_to_sit_cd: str | None = None
    sit_to_stand_cd: str | None = None
    chair_bed_transfer_cd: str | None = None
    toilet_transfer_cd: str | None = None
    walk_10_feet_cd: str | None = None
    walk_50_feet_cd: str | None = None
    walk_150_feet_cd: str | None = None
    step_1_cd: str | None = None
    urinary_continence_cd: str | None = None
    bowel_continence_cd: str | None = None

    @field_validator("assessment_system")
    def check_assessment_system(cls, v: str | None) -> str | None:
        if v != "IRF-PAI":
            raise ValueError("Invalid assessment system")
        return v

    @field_validator("transaction_type")
    def check_transaction_type(cls, v: int | None) -> int | None:
        if v not in [1, 2]:
            raise ValueError("Invalid transaction type")
        return v
