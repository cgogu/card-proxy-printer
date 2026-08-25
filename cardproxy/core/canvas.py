import os
from datetime import datetime
from glob import glob

import cv2
import numpy as np
from fpdf import FPDF
from natsort import natsorted

from .models import MM_PER_INCH, CanvasModel, CardModel


class Canvas:
    """
    Canvas for standard print paper.
    """

    def __init__(
        self,
        dpi: int = 600,
        cards_per_page_width: int = 1,
        cards_per_page_height: int = 1,
        paper_width_mm: float = 210.0,
        paper_height_mm: float = 297.0,
    ) -> None:
        if cards_per_page_width < 1 or cards_per_page_height < 1:
            raise ValueError(
                "cards_per_page_width and cards_per_page_height must be >= 1."
            )
        if paper_width_mm <= 0 or paper_height_mm <= 0:
            raise ValueError("Paper dimensions must be > 0.")
        self.__card_data_model = CardModel(dpi=dpi)
        self.data_model = CanvasModel(
            dpi=dpi, width_mm=paper_width_mm, height_mm=paper_height_mm
        )
        self.num_page = None
        self.num_pages = None
        self.image_ext = "png"
        self.num_cards_per_page_width = cards_per_page_width
        self.num_cards_per_page_height = cards_per_page_height
        self._generate_layout_data()

    @property
    def on_canvas_card_width_pixels(self):
        return self.__card_data_model.width_pixels

    @property
    def on_canvas_card_height_pixels(self):
        return self.__card_data_model.height_pixels

    def _generate_layout_data(self) -> None:
        """
        Generate a centered grid of cards (with bleed) on the canvas.

        The leftover page space is split into (n_cols + 1) horizontal and
        (n_rows + 1) vertical equal slots, so outer margins and inter-card
        gaps are the same and the grid stays centered on the page.
        """

        n_cols = self.num_cards_per_page_width
        n_rows = self.num_cards_per_page_height
        total_w = self.__card_data_model.total_width_pixels
        total_h = self.__card_data_model.total_height_pixels
        page_w = self.data_model.width_pixels
        page_h = self.data_model.height_pixels

        available_w = page_w - n_cols * total_w
        available_h = page_h - n_rows * total_h
        if available_w < 0 or available_h < 0:
            raise ValueError(
                f"Grid of {n_cols}x{n_rows} cards (with bleed) does not fit "
                "on the page."
            )

        self.x_gap = available_w // (n_cols + 1)
        self.y_gap = available_h // (n_rows + 1)
        # Absorb the leftover pixel(s) into the outer margin so the grid is
        # still visually centered even when the division isn't exact.
        self.x_step = self.x_gap + (available_w - (n_cols + 1) * self.x_gap) // 2
        self.y_step = self.y_gap + (available_h - (n_rows + 1) * self.y_gap) // 2

    def _draw_crop_marks(self) -> None:
        """
        Draw crop marks around each card indicating the trim boundary.
        """

        bleed_px = self.__card_data_model.bleed_pixels
        total_w = self.__card_data_model.total_width_pixels
        total_h = self.__card_data_model.total_height_pixels
        n_cols = self.num_cards_per_page_width
        n_rows = self.num_cards_per_page_height

        grid_left = self.x_step
        grid_right = self.x_step + n_cols * total_w + (n_cols - 1) * self.x_gap
        grid_top = self.y_step
        grid_bottom = self.y_step + n_rows * total_h + (n_rows - 1) * self.y_gap

        # 5 mm long marks, 2 mm gap from the grid edge
        mark_length_px = round(self.__card_data_model.dpi * 5 / MM_PER_INCH)
        mark_gap_px = round(self.__card_data_model.dpi * 2 / MM_PER_INCH)
        page_h, page_w = self.page.shape[:2]

        trim_xs = []
        for c in range(n_cols):
            card_left_c = grid_left + c * (total_w + self.x_gap)
            trim_xs.append(card_left_c + bleed_px)
            trim_xs.append(card_left_c + total_w - bleed_px)

        trim_ys = []
        for r in range(n_rows):
            card_top_r = grid_top + r * (total_h + self.y_gap)
            trim_ys.append(card_top_r + bleed_px)
            trim_ys.append(card_top_r + total_h - bleed_px)

        # Vertical marks above/below the whole grid
        for x in trim_xs:
            top_start = max(0, grid_top - mark_gap_px - mark_length_px)
            top_end = max(0, grid_top - mark_gap_px)
            self.page[top_start:top_end, x, :] = 0

            bot_start = min(page_h, grid_bottom + mark_gap_px)
            bot_end = min(page_h, grid_bottom + mark_gap_px + mark_length_px)
            self.page[bot_start:bot_end, x, :] = 0

        # Horizontal marks left/right of the whole grid
        for y in trim_ys:
            left_start = max(0, grid_left - mark_gap_px - mark_length_px)
            left_end = max(0, grid_left - mark_gap_px)
            self.page[y, left_start:left_end, :] = 0

            right_start = min(page_w, grid_right + mark_gap_px)
            right_end = min(page_w, grid_right + mark_gap_px + mark_length_px)
            self.page[y, right_start:right_end, :] = 0

    def _draw_page_info(self, num_page: int | None, num_pages: int | None) -> None:
        """
        Draw the header text and page numbering in the top/bottom margins.
        """

        if num_page is None or num_pages is None:
            return

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
        draw_crop_marks: bool = False,
        draw_page_info: bool = False,
    ) -> None:
        """
        Create a new canvas page.
        """

        self.num_page = num_page
        self.num_pages = num_pages
        self.clear_page() if hasattr(self, "page") else self.blank_page()

        if draw_crop_marks:
            self._draw_crop_marks()

        if draw_page_info:
            self._draw_page_info(num_page, num_pages)

    def save_page(self, output_dir: str) -> None:
        """
        Save canvas page on disk as an image.
        """

        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        cv2.imwrite(
            os.path.join(output_dir, f"{str(self.num_page).zfill(2)}.{self.image_ext}"),
            self.page,
        )

    def fill_page(self, cards: tuple) -> None:
        """
        Fill canvas page with cards.
        """

        print(
            f"[CARD-PROXY-PRINTER] Fill page {self.num_page}/{self.num_pages} with cards."
        )

        bleed_px = self.__card_data_model.bleed_pixels
        total_w = self.__card_data_model.total_width_pixels
        total_h = self.__card_data_model.total_height_pixels

        for card_index, card in enumerate(cards):
            x_index = card_index % self.num_cards_per_page_width
            y_index = card_index // self.num_cards_per_page_width
            card_with_bleed = cv2.copyMakeBorder(
                card,
                top=bleed_px,
                bottom=bleed_px,
                left=bleed_px,
                right=bleed_px,
                borderType=cv2.BORDER_CONSTANT,
                value=[0, 0, 0],
            )

            # Paint the bleed/card seam black to hide SR/denoise edge fringing.
            card_with_bleed[bleed_px, bleed_px:-bleed_px, :] = 0
            card_with_bleed[-bleed_px - 1, bleed_px:-bleed_px, :] = 0
            card_with_bleed[bleed_px:-bleed_px, bleed_px, :] = 0
            card_with_bleed[bleed_px:-bleed_px, -bleed_px - 1, :] = 0

            x0 = self.x_step + x_index * (total_w + self.x_gap)
            y0 = self.y_step + y_index * (total_h + self.y_gap)
            self.page[
                y0 : y0 + total_h,
                x0 : x0 + total_w,
                :,
            ] = card_with_bleed

    def save_pdf(self, tmpdir: str, path_to_output: str, card_game_alias: str) -> None:
        """
        Save canvas pages as a PDF file.
        """

        decklist_pdf = FPDF(
            orientation="portrait",
            unit="in",
            format=(self.data_model.width_inch, self.data_model.height_inch),
        )

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
