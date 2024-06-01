import cv2
import numpy as np

from .meta import CanvasMeta, CardMeta


class Canvas:
    def __init__(self, dpi: int = 300) -> None:
        self.__card_metadata = CardMeta(name="mock", index=0, dpi=dpi)
        self.metadata = CanvasMeta(dpi=dpi)
        self.num_cards_per_page, self.x_step, self.y_step = self._generate_layout_data()

    def _generate_layout_data(self) -> tuple:
        num_cards_per_page_width = (
            self.metadata.width_px // self.__card_metadata.width_px
        )
        num_cards_per_page_height = (
            self.metadata.height_px // self.__card_metadata.height_px
        )
        num_cards_per_page = min(num_cards_per_page_width, num_cards_per_page_height)

        return (
            num_cards_per_page,
            (
                self.metadata.width_px
                - self.__card_metadata.width_px * num_cards_per_page
            )
            // 2,
            (
                self.metadata.height_px
                - self.__card_metadata.height_px * num_cards_per_page
            )
            // 2,
        )

    def _draw_layout_helpers(self, num_page: int | None, num_pages: int | None) -> None:
        for card_idx in range(self.num_cards_per_page + 1):
            # X-axis
            self.page[
                :, self.x_step + (self.__card_metadata.width_px * card_idx), :
            ] = 0
            # Y-axis
            self.page[
                self.y_step + (self.__card_metadata.height_px * card_idx), :, :
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
                    self.metadata.width_px // 2 - fw // 2,
                    self.metadata.height_px - self.y_step // 2 + fh // 2,
                ],
                fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                fontScale=1,
                color=[0, 0, 0],
                thickness=2,
            )

    def blank_page(self) -> None:
        self.page = np.full(
            (self.metadata.height_px, self.metadata.width_px, 3),
            fill_value=255,
            dtype=np.uint8,
        )

    def clear_page(self) -> None:
        self.page[...] = 255

    def new_page(
        self,
        num_page: int | None,
        num_pages: int | None,
        draw_layout: bool = True,
    ) -> None:
        self.clear_page() if hasattr(self, "page") else self.blank_page()
        if draw_layout:
            self._draw_layout_helpers(num_page, num_pages)
