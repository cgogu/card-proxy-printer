from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from .models import CanvasModel, CardModel


class Canvas:
    """
    Canvas for standard print paper.
    """

    def __init__(self, dpi: int = 300) -> None:
        self.__card_data_model = CardModel(identifier="", dpi=dpi)
        self.data_model = CanvasModel(dpi=dpi)
        (
            self.num_cards_per_page_width,
            self.num_cards_per_page_height,
            self.x_step,
            self.y_step,
        ) = self._generate_layout_data()

    def _generate_layout_data(self) -> tuple:
        """
        Generate cards layout for the canvas.
        """

        num_cards_per_page_width = (
            self.data_model.width_px // self.__card_data_model.width_px
        )
        num_cards_per_page_height = (
            self.data_model.height_px // self.__card_data_model.height_px
        )

        return (
            num_cards_per_page_width,
            num_cards_per_page_height,
            (
                self.data_model.width_px
                - self.__card_data_model.width_px * num_cards_per_page_width
            )
            // 2,
            (
                self.data_model.height_px
                - self.__card_data_model.height_px * num_cards_per_page_height
            )
            // 2,
        )

    def _draw_layout_helpers(self, num_page: int | None, num_pages: int | None) -> None:
        """
        Draw cards layout on the canvas.
        """

        # X-axis
        for card_idx in range(self.num_cards_per_page_width + 1):
            self.page[
                :, self.x_step + (self.__card_data_model.width_px * card_idx), :
            ] = 0

        # Y-axis
        for card_idx in range(self.num_cards_per_page_height + 1):
            self.page[
                self.y_step + (self.__card_data_model.height_px * card_idx), :, :
            ] = 0

        if num_page is not None and num_pages is not None:
            page_text = f"{str(num_page).zfill(2)}/{str(num_pages).zfill(2)}"
            (fw, fh), _ = cv2.getTextSize(
                text=page_text,
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                thickness=2,
            )
            cv2.putText(
                img=self.page,
                text=page_text,
                org=[
                    self.data_model.width_px // 2 - fw // 2,
                    self.data_model.height_px - self.y_step // 2 + fh // 2,
                ],
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                color=[0, 0, 0],
                thickness=2,
            )

    def blank_page(self) -> None:
        """
        Create a blank (empty) canvas page.
        """

        self.page = np.full(
            (self.data_model.height_px, self.data_model.width_px, 3),
            fill_value=255,
            dtype=np.uint8,
        )

    def clear_page(self) -> None:
        """
        Clear canvas page.
        """

        self.page[...] = 255

    def new_page(
        self,
        num_page: int | None,
        num_pages: int | None,
        draw_layout: bool = True,
    ) -> None:
        """
        Create a new canvas page.
        """

        self.clear_page() if hasattr(self, "page") else self.blank_page()
        if draw_layout:
            self._draw_layout_helpers(num_page, num_pages)

    def save_page(
        self, output_dir: str, output_filename: str = "proxifier.png"
    ) -> None:
        """
        Save canvas page on disk as an image.
        """

        if not (output_dir := Path(output_dir)).exists():
            output_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite((output_dir / output_filename).as_posix(), self.page)

    def fill_page(self, cards: Iterable[dict]) -> None:
        """
        Fill canvas page with cards.
        """

        for card_index, card in enumerate(cards):
            y_index = card_index % self.num_cards_per_page_height
            x_index = card_index // self.num_cards_per_page_width
            self.page[
                self.y_step
                + (card["height"] * y_index) : self.y_step
                + (card["height"] * (y_index + 1)),
                self.x_step
                + (card["width"] * x_index) : self.x_step
                + (card["width"] * (x_index + 1)),
                :,
            ] = card["image"]
