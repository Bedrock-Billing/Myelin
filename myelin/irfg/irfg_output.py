import jpype
from pydantic import BaseModel


class IrfgOutput(BaseModel):
    claim_id: str = ""
    irf_version: int | None = None
    motor_score: float | None = None
    ric: int | None = None
    cmg_group: str | None = None
    error_code: int | None = None
    error_description: str | None = None

    def from_java(self, java_obj: jpype.JObject) -> None:
        if not java_obj:
            return
        self.irf_version = java_obj.getUsedIrfVersion()
        self.motor_score = float(java_obj.getCalculatedMotorScore())
        self.ric = int(java_obj.getCalculatedRic())
        self.cmg_group = str(java_obj.getCmgGroup())
        self.error_code = int(java_obj.getError())
        error_enum = jpype.JClass("gov.cms.grouper.irf.model.Error")
        java_enum = error_enum.getError(self.error_code)
        self.error_description = str(java_enum.getReason())
