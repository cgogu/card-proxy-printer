from typing import Any

from pydantic import BaseModel, Field


class CardModel(BaseModel):
    """
    Card data model.

    Magic cards are 63 x 88 millimeters, which is 2.48 x 3.46 inches.
    To get the size we should have in pixels, we simply multiply the size of the thing we are printing in inches, with the desired DPI resolution.
    MPC says we should add 1/8" extra bleed area on each side of our card, and they approximate that to 36px at 300dpi. However, 1/8" at 300dpi is 37.5 pixels to be exact but we can't really do things with half pixels.
    MPC also provides templates which tell us the exact measures. The template for MTG-sized cards: https://www.makeplayingcards.com/dl/templates/playingcard/American-poker-size.pdf
    This tells us the truth, the bleed area is not 0.125 inches (which is 1/8"), it's actually 0.12 inches on each side. So 36px is exactly what we should use.
    So our 744 x 1038 image, needs (36 x 2) = 72px bleed area added on each dimension. Which brings us to 816 x 1110 pixels.
    816 x 1110 pixels is what your source images should be when printing 63x88mm cards.
    The PDF template: https://www.makeplayingcards.com/dl/templates/playingcard/poker-size.pdf
    Some people make images sized for 2.5 x 3.5 cards and then print 63 x 88 cards, or vice versa. Don't do this.
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
    width_mm: int = Field(default=63, exclude=True)
    height_mm: int = Field(default=88, exclude=True)
    width_inch: float = Field(default=2.48, exclude=True)
    height_inch: float = Field(default=3.46, exclude=True)
    bleed_area_inch: float = Field(default=0.12, exclude=True)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_pixels = round(
            self.dpi * (self.width_inch + 2 * self.bleed_area_inch)
        )
        self.height_pixels = round(
            self.dpi * (self.height_inch + 2 * self.bleed_area_inch)
        )
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
