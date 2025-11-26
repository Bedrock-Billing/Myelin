import jpype
from pydantic import BaseModel, Field
from typing_extensions import override

from myelin.converter.icd_converter import ICD10ConvertOutput


class MsdrgHac(BaseModel):
    hac_number: int | None = None
    hac_status: str | None = None
    hac_list: str | None = None

    def from_java(self, java_obj: jpype.JObject) -> "MsdrgHac":
        self.hac_number = java_obj.getHacNumber()
        self.hac_status = str(java_obj.getHacStatus().name())
        self.hac_list = str(java_obj.getHacList())
        return self


class MsdrgOutputDxCode(BaseModel):
    grouping_impact: str | None = None
    final_severity_flag: str | None = None
    initial_severity_flag: str | None = None
    hac_list: list[MsdrgHac] = Field(default_factory=list)
    poa_error_code: str | None = None
    recognized_by_grouper: bool | None = None

    def from_java(self, java_obj: jpype.JObject) -> "MsdrgOutputDxCode":
        self.grouping_impact = str(java_obj.getDiagnosisAffectsDrg().name())
        self.final_severity_flag = str(java_obj.getFinalSeverityUsage().name())
        self.initial_severity_flag = str(java_obj.getInitialSeverityUsage().name())
        hac_list = java_obj.getHacs()
        self.hac_list = []
        for hac in hac_list:
            hac_obj = MsdrgHac().from_java(hac)
            self.hac_list.append(hac_obj)
        self.poa_error_code = str(java_obj.getPoaErrorCode().name())
        self.recognized_by_grouper = java_obj.isDiagnosisRecognizedByGrouper()
        return self


class MsdrgGrouperFlags(BaseModel):
    admit_dx_grouper_flag: str | None = None
    final_secondary_dx_cc_mcc_flag: str | None = None
    initial_secondary_dx_cc_mcc_flag: str | None = None
    num_hac_categories_satisfied: int | None = None
    hac_status_value: str | None = None

    def from_java(self, java_obj: jpype.JObject) -> "MsdrgGrouperFlags":
        self.admit_dx_grouper_flag = str(java_obj.getAdmitDxGrouperFlag().name())
        self.final_secondary_dx_cc_mcc_flag = str(
            java_obj.getFinalDrgSecondaryDxCcMcc().name()
        )
        self.initial_secondary_dx_cc_mcc_flag = str(
            java_obj.getInitialDrgSecondaryDxCcMcc().name()
        )
        self.num_hac_categories_satisfied = java_obj.getNumHacCategoriesSatisfied()
        self.hac_status_value = str(java_obj.getHacStatusValue().name())
        return self


class MsdrgOutputPrCode(BaseModel):
    grouping_impact: str | None = None
    is_or_procedure: bool | None = None
    recognized_by_grouper: bool | None = None
    hac_usage: list[MsdrgHac] = Field(default_factory=list)

    def from_java(self, java_obj: jpype.JObject) -> "MsdrgOutputPrCode":
        self.grouping_impact = str(java_obj.getProcedureAffectsDrg().name())
        self.is_or_procedure = java_obj.isProcedureIsOperatingRoomProcedure()
        self.recognized_by_grouper = java_obj.isProcedureRecognizedByGrouper()
        hac_usage = java_obj.getHacUsage()
        self.hac_usage = []
        if hac_usage:
            for hac in hac_usage:
                hac_obj = MsdrgHac().from_java(hac)
                self.hac_usage.append(hac_obj)
        return self


class MsdrgOutput(BaseModel):
    claim_id: str = ""
    drg_version: str = ""
    grouper_flags: MsdrgGrouperFlags = Field(default_factory=MsdrgGrouperFlags)
    initial_grc: str = ""
    final_grc: str = ""
    initial_mdc_value: str = ""
    initial_mdc_description: str = ""
    initial_drg_value: str = ""
    initial_drg_description: str = ""
    initial_base_drg_value: str = ""
    initial_base_drg_description: str = ""
    initial_med_surg_type: str = ""
    initial_severity: str = ""
    initial_drg_sdx_severity: str = ""
    final_mdc_value: str = ""
    final_mdc_description: str = ""
    final_drg_value: str = ""
    final_drg_description: str = ""
    final_base_drg_value: str = ""
    final_base_drg_description: str = ""
    final_med_surg_type: str = ""
    final_severity: str = ""
    final_drg_sdx_severity: str = ""
    hac_status: str = ""
    num_hac_categories_satisfied: int = 0
    principal_dx_output: MsdrgOutputDxCode = Field(default_factory=MsdrgOutputDxCode)
    secondary_dx_outputs: list[MsdrgOutputDxCode] = Field(default_factory=list)
    procedure_outputs: list[MsdrgOutputPrCode] = Field(default_factory=list)
    icd10_conversion_output: ICD10ConvertOutput | None = None

    @override
    def __str__(self) -> str:
        return f"MsdrgOutput(final_drg={self.final_drg_value}, final_mdc={self.final_mdc_value}, final_severity={self.final_severity})"

    @override
    def __repr__(self) -> str:
        return self.__str__()
