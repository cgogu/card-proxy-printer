from typing import Any, Literal

from pydantic import BaseModel, Field

# Standard SI conversion (1 in = 25.4 mm). Any "printer fudge" belongs in the
# printer driver / "Actual Size" settings, not in these dimensions.
MM_PER_INCH = 25.4


class CardModel(BaseModel):
    """
    Card data model.

    Flesh and Blood and Magic: The Gathering cards are both printed at
    63 × 88 mm (standard "poker" trading-card size).
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
    dpi: int = Field(default=600, ge=300, exclude=True)
    width_mm: int = Field(default=63, exclude=True)
    height_mm: int = Field(default=88, exclude=True)
    bleed_mm: int = Field(default=3, exclude=True)
    width_inch: float | None = Field(default=None, exclude=True)
    height_inch: float | None = Field(default=None, exclude=True)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)
    bleed_pixels: int | None = Field(default=None, exclude=True)
    total_width_pixels: int | None = Field(default=None, exclude=True)
    total_height_pixels: int | None = Field(default=None, exclude=True)
    art_variations: list | None = Field(default=None, exclude=True)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_inch = self.width_mm / MM_PER_INCH
        self.height_inch = self.height_mm / MM_PER_INCH
        self.width_pixels = round(self.dpi * self.width_inch)
        self.height_pixels = round(self.dpi * self.height_inch)
        self.bleed_pixels = round(self.dpi * self.bleed_mm / MM_PER_INCH)
        self.total_width_pixels = self.width_pixels + 2 * self.bleed_pixels
        self.total_height_pixels = self.height_pixels + 2 * self.bleed_pixels
        return super().model_post_init(__context)


class CanvasModel(BaseModel):
    """
    Canvas data model.
    """

    format: str = Field(default="A4")
    dpi: int = Field(default=600, ge=300)
    width_mm: float = Field(default=210.0)
    height_mm: float = Field(default=297.0)
    width_inch: float | None = Field(default=None)
    height_inch: float | None = Field(default=None)
    width_pixels: int | None = Field(default=None)
    height_pixels: int | None = Field(default=None)

    def model_post_init(self, __context: Any) -> None:
        """
        Post initalization processing.
        """

        self.width_inch = self.width_mm / MM_PER_INCH
        self.height_inch = self.height_mm / MM_PER_INCH
        self.width_pixels = round(self.dpi * self.width_inch)
        self.height_pixels = round(self.dpi * self.height_inch)
        return super().model_post_init(__context)


class DecklistEntry(BaseModel):
    """
    One parsed decklist line. ``first_part`` / ``second_part`` map onto the
    proxifier's ``generate_card`` signature so callers can forward them
    directly without a positional tuple unpack.
    """

    count: int = Field(gt=0)
    first_part: str
    second_part: str


class AppConfig(BaseModel):
    """
    Combined runtime configuration for both CLI and GUI flows.

    Unknown YAML keys are silently ignored so users can add annotations to
    their configs without tripping validation.
    """

    model_config = {"extra": "ignore"}

    card_game_alias: Literal["fab", "mtg"]

    path_to_database: str | None = None
    path_to_collection_input: str | None = None
    path_to_sr_weights: str | None = None
    path_to_denoise_weights: str | None = None

    # Derived by parse_config for the CLI flow (or provided directly via CLI args).
    path_to_decklist: str | None = None
    path_to_output: str | None = None
    path_to_collection_output: str | None = None

    cards_per_page_width: int = Field(default=1, ge=1)
    cards_per_page_height: int = Field(default=1, ge=1)
    paper_width_mm: float = Field(default=210.0, gt=0)
    paper_height_mm: float = Field(default=297.0, gt=0)
    dpi: int = Field(default=600, ge=300)


class CollectionMetadata(BaseModel):
    """
    Metadata block persisted at the top of every ``fab-cards-collection-*.json``
    snapshot. Ties an on-disk collection to the source-repo commit it was built
    from and to the ``CardModel`` dimensions used at generation time.
    """

    model_config = {"extra": "ignore"}

    author: str = "cgogu"
    datetime: str
    hash: str
    dpi: int = Field(ge=300)
    width_inch: float
    height_inch: float
    width_pixels: int
    height_pixels: int
