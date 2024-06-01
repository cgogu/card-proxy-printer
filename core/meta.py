from typing import Any
from pydantic import BaseModel, Field


class CardMeta(BaseModel):
    name: str = Field(default=...)
    index: int = Field(default=...)
    count: int = Field(default=1)
    dpi: int = Field(default=300, ge=300)
    width_inch: float = Field(default=2.5)
    height_inch: float = Field(default=3.5)
    width_px: int = Field(default=-1)
    height_px: int = Field(default=-1)

    def model_post_init(self, __context: Any) -> None:
        self.width_px = round(self.dpi * self.width_inch)
        self.height_px = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)


class CanvasMeta(BaseModel):
    format: str = Field(default="A4")
    dpi: int = Field(default=300, ge=300)
    width_inch: float = Field(default=8.268)
    height_inch: float = Field(default=11.693)
    width_px: int = Field(default=-1)
    height_px: int = Field(default=-1)

    def model_post_init(self, __context: Any) -> None:
        self.width_px = round(self.dpi * self.width_inch)
        self.height_px = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)
