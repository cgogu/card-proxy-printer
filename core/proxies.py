import json
import os
from abc import ABC, abstractmethod

import cv2
import time
import torch
import numpy as np
from simdjson import Parser
from requests import Session
from .models import CardModel
from .utils import (
    replace_alpha_with_solid,
    apply_superes_and_denoiser_pipeline,
    create_fab_cards_collection,
    get_json_file,
)
from helper_repos.sr.torchsr.torchsr.models import (
    ninasr_b0,
    ninasr_b1,
    ninasr_b2,
)  # speed - quality tradeoff
from helper_repos.denoise.scunet.models.network_scunet import SCUNet


class CardGameProxifier(ABC):

    def __init__(
        self,
        name: str,
        endpoint: str,
        sr_weights_path: str | None,
        denoise_weights_path: str | None,
        use_api: bool = True,
    ) -> None:
        self.name = name
        self.endpoint = endpoint
        self.sr_weights_path = sr_weights_path
        self.denoise_weights_path = denoise_weights_path
        self.use_api = use_api
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.session = Session()
        self.session.headers.update({"Accept": "application/json"})
        self._generate_nn_models()

    @abstractmethod
    def get_card(self):
        raise NotImplementedError

    @abstractmethod
    def generate_card(self):
        raise NotImplementedError

    def _generate_nn_models(self) -> None:
        if self.sr_weights_path is not None:
            self.sr_model = ninasr_b2(scale=4, pretrained=False)
            self.sr_model.load_state_dict(
                torch.load(
                    self.sr_weights_path,
                    map_location=self.device,
                ),
                strict=True,
            )
            self.sr_model.eval()
            for _, v in self.sr_model.named_parameters():
                v.requires_grad = False

        if self.denoise_weights_path is not None:
            self.denoise_model = SCUNet(in_nc=3, config=[4, 4, 4, 4, 4, 4, 4], dim=64)
            self.denoise_model.load_state_dict(
                torch.load(
                    self.denoise_weights_path,
                    map_location=self.device,
                ),
                strict=True,
            )
            self.denoise_model.eval()
            for _, v in self.denoise_model.named_parameters():
                v.requires_grad = False

    def process_card_image(
        self, card_image_bytes: bytes, width: int, height: int
    ) -> np.ndarray:
        card_image = cv2.imdecode(np.frombuffer(card_image_bytes, np.uint8), -1)
        card_image = replace_alpha_with_solid(card_image)
        card_image = apply_superes_and_denoiser_pipeline(
            card_image, self.sr_model, self.denoise_model, width, height, self.device
        )
        return card_image


class MTGProxifier(CardGameProxifier):

    # MTG
    # set_alias = "woe"
    # collector_number = 3
    # card_response = requests.get(f"https://api.scryfall.com/cards/{set_alias}/{collector_number}")
    # if card_response is not None:
    #     card_data = card_response.json()
    # card_name = card_data["name"].lower().replace(" ", "-")
    # image_response = requests.get(card_data["image_uris"]["png"])

    def __init__(
        self,
        name: str = "MTG",
        endpoint: str = "https://api.scryfall.com/cards",
        sr_weights_path: str | None = None,
        denoise_weights_path: str | None = None,
    ) -> None:
        super().__init__(name, endpoint, sr_weights_path, denoise_weights_path)

    def get_card(self, card_set_alias: str, card_set_collector_number: int):
        pass

    def generate_card(self):
        pass


class FABProxifier(CardGameProxifier):

    def __init__(
        self,
        name: str = "fab",
        endpoint: str = "https://api.fabdb.net/cards",
        sr_weights_path: str | None = None,
        denoise_weights_path: str | None = None,
        use_api: bool = False,
        collection_input_path: str | None = None,
        collection_output_path: str | None = None,
    ) -> None:
        super().__init__(name, endpoint, sr_weights_path, denoise_weights_path, use_api)
        if not use_api:
            create_fab_cards_collection(
                collection_input_path, collection_output_path, name
            )
            self.cards_collection_parser = Parser().load(
                get_json_file(os.path.join(collection_output_path, name))
            )

    def _get_card_by_api(self, card_name: str) -> bytes | None:
        # Card name and pitch value delimiter: "_"
        card_name = card_name.replace("_", "-")

        time.sleep(0.1)  # required
        if not (
            card_data_response := self.session.get(
                url=f"{self.endpoint}/{card_name}",
                verify=True,
            )
        ).ok:
            return

        card_data = card_data_response.json()
        time.sleep(0.1)  # required
        if not (
            card_image_response := self.session.get(
                url=card_data.get("image", "").split("?")[0],
                verify=True,
            )
        ).ok:
            return

        return card_image_response.content

    def _get_card_by_collection(self, card_name: str) -> bytes | None:
        # Card name and pitch value delimiter: "_"
        if "_" in card_name:
            card_name, card_pitch = card_name.split("_")
        else:
            card_pitch = "unique"

        time.sleep(0.1)  # required
        if not (
            card_image_response := self.session.get(
                url=self.cards_collection_parser.at_pointer(
                    f"/cards/{card_name}/{card_pitch}/image_url"
                ).split("?")[0],
                verify=True,
            )
        ).ok:
            return

        return card_image_response.content

    def get_card(self, card_name: str) -> list | None:
        return (
            self._get_card_by_api(card_name)
            if self.use_api
            else self._get_card_by_collection(card_name)
        )

    def generate_card(
        self,
        card_name: str,
        on_canvas_card_width_pixels: int,
        on_canvas_card_height_pixels: int,
    ) -> dict:
        if (card_image_bytes := self.get_card(card_name)) is None:
            return

        return self.process_card_image(
            card_image_bytes, on_canvas_card_width_pixels, on_canvas_card_height_pixels
        )
