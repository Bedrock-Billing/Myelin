from typing import Any

import jpype
from pydantic import BaseModel, Field

DX_EDIT_FLAGS = {
    0: "Invalid diagnosis code",
    1: "Sex conflict",
    2: "Age conflict",
    3: "Questionable admission",
    4: "Manifestation code as principal diagnosis",
    5: "Nonspecific principal diagnosis",
    6: "E-code as principal diagnosis",
    7: "Unacceptable principal diagnosis",
    8: "Duplicate of principal diagnosis",
    9: "Medicare is secondary payer",
    10: "Requires secondary diagnosis",
    11: {
        0: "No age conflict",
        1: "Newborn",
        2: "Pediatric",
        3: "Maternity",
        4: "Adult",
    },
    12: "POA indicator invalid or missing (for future use)",
    13: "Wrong procedure performed",
    14: "Unspecified",
    15: "Unused",
    16: "Unused",
    17: "Unused",
    18: "Unused",
    19: "Unused",
}
PX_EDIT_FLAGS = {
    0: "Invalid procedure code",
    1: "Sex conflict",
    2: "Nonspecific O.R. procedure",
    3: "Open biopsy check",
    4: "Non-covered procedure",
    5: "Bilateral procedure",
    6: "ICD9 - Limited coverage, lung volume reduction surgery",
    7: "ICD9 - Limited coverage, lung transplant",
    8: "Limited coverage, combination heart and lung transplant",
    9: "Limited coverage, heart transplant",
    10: "Limited coverage, implant of heart assist system",
    11: "Limited coverage, intestine or multi-visceral transplant",
    12: "Limited coverage, liver transplant",
    13: "Limited coverage, kidney transplant",
    14: "Limited coverage, pancreas transplant",
    15: "Limited coverage, artificial heart",
    16: "Procedure inconsistent with length of stay",
    17: "Unused",
    18: "Unused",
    19: "Unused",
}


class MceOutputDxCode(BaseModel):
    code: str
    edit_flags: list[str] = Field(default_factory=list)
    age_conflict_type: str | None = None


class MceOutputPrCode(BaseModel):
    code: str
    edit_flags: list[str] = Field(default_factory=list)


class MceOutput(BaseModel):
    version_used: int = 0
    edit_type: str = ""
    edit_counters: dict[str, Any] = Field(default_factory=dict)
    diagnosis_codes: list[MceOutputDxCode] = Field(default_factory=list)
    procedure_codes: list[MceOutputPrCode] = Field(default_factory=list)

    # Java classes for jpype integration (not part of Pydantic model)
    java_map_class: Any = Field(default=None, exclude=True)
    icd_vers: Any = Field(default=None, exclude=True)

    def model_post_init(self, __context: Any) -> None:
        """Initialize Java classes after Pydantic model creation"""
        self.java_map_class = jpype.JClass("java.util.Map")
        self.icd_vers = jpype.JClass("gov.cms.editor.mce.component.edit.Const")

    def from_java(self, java_output: jpype.JObject, mce_record: jpype.JObject) -> None:
        self.version_used = java_output.getVersionUsed()
        self.edit_type = str(java_output.getEditType().name())
        edit_counters = java_output.getEditCounter()
        self.edit_counters = {}  # Clear before populating
        for key in edit_counters.keySet():
            self.edit_counters[str(key.name())] = edit_counters.get(key)

        dx_codes = mce_record.getDiagnoses()
        self.diagnosis_codes = []
        for dx in dx_codes:
            dx_code = str(dx.getValue())
            edit_string = dx.getEditsString(self.icd_vers.ICD_10)
            # iterate over edit_string characters, the index is the flag number
            edit_flags = []
            for i, char in enumerate(edit_string):
                edit = DX_EDIT_FLAGS.get(int(i), "Unknown")
                if char == "1" and isinstance(edit, str):
                    edit_flags.append(edit)
                elif char != "0" and isinstance(edit, dict):
                    # char is a ascii character, convert to int by subtracting 48
                    sub_edit = edit.get(int(char) - 48, "Unknown")
                    edit_flags.append(sub_edit)
            age_conflict_type = dx.getAgeConflictType()
            if age_conflict_type is not None:
                age_conflict_type = str(age_conflict_type.name())
            self.diagnosis_codes.append(
                MceOutputDxCode(
                    code=dx_code,
                    edit_flags=edit_flags,
                    age_conflict_type=age_conflict_type,
                )
            )

        pr_codes = mce_record.getProcedures()
        self.procedure_codes = []
        for pr in pr_codes:
            pr_code = str(pr.getValue())
            edit_string = pr.getEditsString(self.icd_vers.ICD_10)
            # iterate over edit_string characters, the index is the flag number
            edit_flags = []
            for i, char in enumerate(edit_string):
                edit = PX_EDIT_FLAGS.get(int(i), "Unknown")
                if char == "1" and isinstance(edit, str):
                    edit_flags.append(edit)
                elif char != "0" and isinstance(edit, dict):
                    sub_edit = edit.get(int(char), "Unknown")
                    edit_flags.append(sub_edit)
            self.procedure_codes.append(
                MceOutputPrCode(
                    code=pr_code,
                    edit_flags=edit_flags,
                )
            )
        return
