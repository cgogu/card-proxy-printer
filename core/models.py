from typing import Any

from pydantic import BaseModel, Field


class CardModel(BaseModel):
    """
    Card data model.

    Magic cards are printed at 63 x 88 millimeters.
    """

    uuid: str | None = Field(default=None)  # fab-cube-cards db id
    printing_uuid: str | None = Field(default=None)  # fab-cube-cards db print id
    identifier: str = Field(default=None)
    name: str | None = Field(default=None)
    pitch: str | None = Field(default=None, exclude=True)
    foiling: str | None = Field(default=None, exclude=True)
    image_url: str | None = Field(default=None)
    is_hero: bool | None = Field(default=False)
    is_token: bool | None = Field(default=False)
    tokens: list | None = Field(default=None)
    backside: list | None = Field(default=None)
    dpi: int = Field(default=300, ge=300, exclude=True)
    width_mm: int = Field(default=63, exclude=True)
    height_mm: int = Field(default=88, exclude=True)
    width_inch: float | None = Field(default=None, exclude=True)
    height_inch: float | None = Field(default=None, exclude=True)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)
    art_variations: list | None = Field(default=None, exclude=True)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        mm2inch = 24.4  # use this instead of 25.4 for printing fix at 'Actual Size' printer settings
        self.width_inch = self.width_mm / mm2inch
        self.height_inch = self.height_mm / mm2inch
        self.width_pixels = round(self.dpi * self.width_inch)
        self.height_pixels = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)


class CanvasModel(BaseModel):
    """
    Canvas data model.
    """

    format: str = Field(default="A4")
    dpi: int = Field(default=300, ge=300)
    width_inch: float = Field(default=8.268)
    height_inch: float = Field(default=11.693)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_pixels = round(self.dpi * self.width_inch)
        self.height_pixels = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)
