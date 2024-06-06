from typing import Any

from pydantic import BaseModel, Field


class CardModel(BaseModel):
    """
    Card data model.
    """

    uuid: str | None = Field(default=None)  # fab-cube-cards db id
    printing_uuid: str | None = Field(default=None)  # fab-cube-cards db print id
    identifier: str = Field(default=None)
    name: str | None = Field(default=None)
    image_url: str | None = Field(default=None)
    foiling: str | None = Field(default=None, exclude=True)
    pitch: str | None = Field(default=None, exclude=True)
    backside: list | None = Field(default=None)
    tokens: list | None = Field(default=None)
    is_token: bool | None = Field(default=False)
    dpi: int = Field(default=300, ge=300, exclude=True)
    width_inch: float = Field(default=2.5, exclude=True)
    height_inch: float = Field(default=3.5, exclude=True)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

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
    width_pixels: int = Field(default=-1)
    height_pixels: int = Field(default=-1)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_pixels = round(self.dpi * self.width_inch)
        self.height_pixels = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)
