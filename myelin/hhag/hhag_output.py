import jpype
from pydantic import BaseModel

from myelin.helpers.utils import ReturnCode


class HhagEdit(BaseModel):
    edit_id: str | None = None
    severity: str | None = None
    description: str | None = None
    type: str | None = None

    def from_java(self, java_obj: jpype.JObject) -> None:
        self.edit_id = str(java_obj.getId().getDescription())
        self.description = str(java_obj.getDescription())
        self.type = str(java_obj.getType().getName())
        self.severity = str(java_obj.getServerityLevel().getName())


class HhagOutput(BaseModel):
    hipps_code: str | None = None
    return_code: ReturnCode | None = None
    validity_flag: str | None = None
    edits: list[HhagEdit] | None = None

    def from_java(self, java_obj: jpype.JObject) -> None:
        return_code = java_obj.getReturnCodeValue()
        if return_code is not None:
            self.return_code = ReturnCode()
            self.return_code.code = str(return_code)
            self.return_code.description = str(java_obj.getReturnCodeDescription())
        self.hipps_code = str(java_obj.getHippsCode())
        edits = (
            java_obj.getEdits()
        )  # <-- Returns an edit colletion, which is not iterable
        if edits is not None:
            for (
                edit
            ) in edits.getEdits():  # <--- We have to call getEdits() on the collection
                if self.edits is None:
                    self.edits = []
                new_edit = HhagEdit()
                new_edit.from_java(edit)
                self.edits.append(new_edit)
