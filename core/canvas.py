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
        self.__card_data_model = CardModel(dpi=dpi)
        self.data_model = CanvasModel(dpi=dpi)
        self._generate_layout_data()

    @property
    def on_canvas_card_width_pixels(self):
        return self.__card_data_model.width_pixels

    @property
    def on_canvas_card_height_pixels(self):
        return self.__card_data_model.height_pixels

    def _generate_layout_data(self) -> None:
        """
        Generate cards layout for the canvas.
        """

        self.num_cards_per_page_width = (
            self.data_model.width_pixels // self.__card_data_model.width_pixels
        )
        self.num_cards_per_page_height = (
            self.data_model.height_pixels // self.__card_data_model.height_pixels
        )
        self.x_step = (
            self.data_model.width_pixels
            - self.__card_data_model.width_pixels * self.num_cards_per_page_width
        ) // 2
        self.y_step = (
            self.data_model.height_pixels
            - self.__card_data_model.height_pixels * self.num_cards_per_page_height
        ) // 2

    def _draw_layout_helpers(self, num_page: int | None, num_pages: int | None) -> None:
        """
        Draw cards layout on the canvas.
        """

        # X-axis
        for card_idx in range(self.num_cards_per_page_width + 1):
            self.page[
                :, self.x_step + (self.__card_data_model.width_pixels * card_idx), :
            ] = 0

        # Y-axis
        for card_idx in range(self.num_cards_per_page_height + 1):
            self.page[
                self.y_step + (self.__card_data_model.height_pixels * card_idx), :, :
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
                    self.data_model.width_pixels // 2 - fw // 2,
                    self.data_model.height_pixels - self.y_step // 2 + fh // 2,
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
            (self.data_model.height_pixels, self.data_model.width_pixels, 3),
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

        print(f"[CARD-PROXY-PRINTER] Fill canvas with cards.")

        for card_index, card in enumerate(cards):
            y_index = card_index % self.num_cards_per_page_height
            x_index = card_index // self.num_cards_per_page_width
            self.page[
                self.y_step
                + (self.__card_data_model.height_pixels * y_index) : self.y_step
                + (self.__card_data_model.height_pixels * (y_index + 1)),
                self.x_step
                + (self.__card_data_model.width_pixels * x_index) : self.x_step
                + (self.__card_data_model.width_pixels * (x_index + 1)),
                :,
            ] = card
