import os
from glob import glob
from datetime import datetime

import cv2
import numpy as np
from natsort import natsorted
from fpdf import FPDF
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
            # Top text
            top_page_text = "card-proxy-printer"
            (tw, th), _ = cv2.getTextSize(
                text=top_page_text,
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                thickness=2,
            )
            cv2.putText(
                img=self.page,
                text=top_page_text,
                org=[
                    self.data_model.width_pixels // 2 - tw // 2,
                    self.y_step // 2 + th // 2,
                ],
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                color=[0, 0, 0],
                thickness=2,
            )

            # Bottom text
            bottom_page_text = f"{str(num_page).zfill(2)}/{str(num_pages).zfill(2)}"
            (bw, bh), _ = cv2.getTextSize(
                text=bottom_page_text,
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                thickness=2,
            )
            cv2.putText(
                img=self.page,
                text=bottom_page_text,
                org=[
                    self.data_model.width_pixels // 2 - bw // 2,
                    self.data_model.height_pixels - self.y_step // 2 + bh // 2,
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

        decklist_pdf = FPDF(orientation="portrait", unit="in", format="A4")

        for current_canvas_page_path in natsorted(
            glob(os.path.join(tmpdir, f"*.{self.image_ext}"), recursive=True)
        ):
            decklist_pdf.add_page()
            decklist_pdf.image(
                current_canvas_page_path,
                x=0,
                y=0,
                w=self.data_model.width_inch,
                h=self.data_model.height_inch,
            )

        decklist_pdf.output(
            output_pdf_path := os.path.join(
                path_to_output,
                f"{card_game_alias}-deck-snapshot-a4-actual-size-print-setup-{datetime.now().isoformat().replace(':', '-')}.pdf",
            )
        )

        print(
            f"[CARD-PROXY-PRINTER] Done proxying decklist with output at: {output_pdf_path}. "
            "Print the decklist using the A4 'Actual Size' printer page sizing and handling for "
            "the expected layout and cards size."
        )
