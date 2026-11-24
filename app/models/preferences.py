from typing import Literal

from pydantic import BaseModel, model_validator


LanguageCode = Literal["en", "zh-CN"]


class PreferenceResponse(BaseModel):
    language: LanguageCode | None = None
    visual_slides_enabled: bool = True
    visual_slides_auto_generate: bool = False


class PreferenceUpdateRequest(BaseModel):
    language: LanguageCode | None = None
    visual_slides_auto_generate: bool | None = None

    @model_validator(mode="after")
    def _require_any_field(self) -> "PreferenceUpdateRequest":
        if self.language is None and self.visual_slides_auto_generate is None:
            raise ValueError("At least one preference field must be provided")
        return self
