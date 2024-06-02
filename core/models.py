from typing import Any

from pydantic import BaseModel, Field


class CardModel(BaseModel):
    """
    Card data model.
    """

    identifier: str = Field(default=..., exclude=True)
    name: str = Field(default="")
    dpi: int = Field(default=300, ge=300, exclude=True)
    width_inch: float = Field(default=2.5, exclude=True)
    height_inch: float = Field(default=3.5, exclude=True)
    width_px: int = Field(default=-1, alias="width")
    height_px: int = Field(default=-1, alias="height")

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_px = round(self.dpi * self.width_inch)
        self.height_px = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)


class CanvasModel(BaseModel):
    """
    Canvas data model.
    """

    format: str = Field(default="A4")
    dpi: int = Field(default=300, ge=300)
    width_inch: float = Field(default=8.268)
    height_inch: float = Field(default=11.693)
    width_px: int = Field(default=-1)
    height_px: int = Field(default=-1)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_px = round(self.dpi * self.width_inch)
        self.height_px = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)
