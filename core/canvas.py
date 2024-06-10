import os
from glob import glob
from datetime import datetime

import cv2
import numpy as np
from natsort import natsorted
from img2pdf import convert as pdf_convert
from .models import CanvasModel, CardModel


class Canvas:
    """
    Canvas for standard print paper.
    """

    def __init__(self, dpi: int = 300) -> None:
        self.__card_data_model = CardModel(dpi=dpi)
        self.data_model = CanvasModel(dpi=dpi)
        self.num_page = None
        self.num_pages = None
        self.image_ext = "png"
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

        self.num_page = num_page
        self.num_pages = num_pages
        self.clear_page() if hasattr(self, "page") else self.blank_page()

        if draw_layout:
            self._draw_layout_helpers(num_page, num_pages)

    def save_page(self, output_dir: str) -> None:
        """
        Save canvas page on disk as an image.
        """

        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        cv2.imwrite(
            os.path.join(output_dir, f"{str(self.num_page).zfill(2)}.{self.image_ext}"), self.page
        )

    def fill_page(self, cards: tuple) -> None:
        """
        Fill canvas page with cards.
        """

        print(
            f"[CARD-PROXY-PRINTER] Fill page {self.num_page}/{self.num_pages} with cards."
        )

        for card_index, card in enumerate(cards):
            x_index = card_index % self.num_cards_per_page_width
            y_index = card_index // self.num_cards_per_page_height
            self.page[
                self.y_step
                + (self.__card_data_model.height_pixels * y_index) : self.y_step
                + (self.__card_data_model.height_pixels * (y_index + 1)),
                self.x_step
                + (self.__card_data_model.width_pixels * x_index) : self.x_step
                + (self.__card_data_model.width_pixels * (x_index + 1)),
                :,
            ] = card

    def save_pdf(self, tmpdir: str, path_to_output: str, card_game_alias: str) -> None:
        """
        Save canvas pages as a PDF file.
        """
        
        with open(
            output_pdf_path := os.path.join(
                path_to_output,
                f"{card_game_alias}-deck-snapshot-{datetime.now().strftime("%d%m%Y%H%M%S")}.pdf",
            ), "wb"
        ) as pdf_file:
            pages = natsorted(glob(os.path.join(tmpdir, f"*.{self.image_ext}"), recursive=True))
            pdf_file.write(pdf_convert(pages))

        print(f"[CARD-PROXY-PRINTER] Done proxying decklist with output at: {output_pdf_path}.")
