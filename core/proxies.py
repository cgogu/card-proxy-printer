from abc import ABC, abstractmethod

import cv2
import time
import requests
import numpy as np
from .models import CardModel
from .utils import replace_alpha_with_solid


class CardGameProxifier(ABC):
    def __init__(self, name: str, endpoint: str) -> None:
        self.name = name
        self.endpoint = endpoint

    @abstractmethod
    def get_card(self):
        raise NotImplementedError

    @abstractmethod
    def generate_card(self):
        raise NotImplementedError

    def process_card_image_bytes(
        self, card_image_bytes: bytes, width: int, height: int
    ) -> np.ndarray:
        card_image = cv2.imdecode(np.frombuffer(card_image_bytes, np.uint8), -1)
        card_image = replace_alpha_with_solid(card_image)
        card_image = cv2.resize(
            card_image,
            (width, height),
            interpolation=cv2.INTER_CUBIC,
        )
        return card_image


class MTGProxifier(CardGameProxifier):
    def __init__(
        self, name: str = "MTG", endpoint: str = "https://api.scryfall.com/cards"
    ) -> None:
        super().__init__(name, endpoint)

    def get_card(self, card_set_alias: str, card_set_collector_number: int):
        pass

    def generate_card(self):
        pass

    def _content_to_image(self, content: bytes) -> np.ndarray:
        card_image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        card_image = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
        return card_image


class FABProxifier(CardGameProxifier):
    def __init__(
        self, name: str = "FAB", endpoint: str = "https://api.fabdb.net/cards"
    ) -> None:
        # https://fabdb2.imgix.net/cards/printings/ARC042.png - future endpoint
        # where the "ARC042" represents the card set alias and collector number
        self.headers = {"Accept": "application/json"}
        super().__init__(name, endpoint)

    def get_card(self, card_name: str) -> tuple | None:
        time.sleep(0.1)  # required
        if not (
            card_data_response := requests.get(
                url=f"{self.endpoint}/{card_name}",
                headers=self.headers,
                verify=True,
            )
        ).ok:
            return

        card_data = card_data_response.json()
        time.sleep(0.1)  # required
        if not (
            card_image_response := requests.get(
                url=card_data.get("image", "").split("?")[0],
                headers=self.headers,
                verify=True,
            )
        ).ok:
            return

        return card_data, card_image_response.content

    def generate_card(self, card_name: str, card_index: int) -> dict:
        if (card_data := self.get_card(card_name)) is None:
            return

        card_meta, card_image_bytes = card_data
        card_model = CardModel(
            identifier=card_meta.get("identifier", ""),
            name=card_meta.get("name", ""),
            index=card_index,
        )
        card_image = self.process_card_image_bytes(
            card_image_bytes, card_model.width_px, card_model.height_px
        )
        card = card_model.model_dump(by_alias=True)
        card["image"] = card_image

        return card
