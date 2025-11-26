from pydantic import BaseModel


class OasisAssessment(BaseModel):
    fall_risk: int | None = 0
    weight_loss: int | None = 0
    multiple_hospital_stays: int | None = 0
    multiple_ed_visits: int | None = 0
    mental_behavior_risk: int | None = 0
    compliance_risk: int | None = 0
    five_or_more_meds: int | None = 0
    exhaustion: int | None = 0
    other_risk: int | None = 0
    none_of_above: int | None = 0
    grooming: str | None = "00"
    dress_upper: str | None = "00"
    dress_lower: str | None = "00"
    bathing: str | None = "00"
    toileting: str | None = "00"
    transferring: str | None = "00"
    ambulation: str | None = "00"
