import os
from abc import ABC, abstractmethod

import cv2
import time
import torch
import numpy as np
from simdjson import Parser
from requests import Session
from .utils import (
    replace_alpha_with_solid,
    convert_16bit_to_8bit,
    apply_superes_and_denoiser_pipeline,
    create_fab_cards_collection,
    get_ext_file,
    PITCHES,
)
from helper_repos.sr.torchsr.torchsr.models import (
    ninasr_b0,
)  # speed - quality tradeoff
from helper_repos.denoise.scunet.models.network_scunet import SCUNet


class CardGameProxifier(ABC):
    """
    Base card game proxifier class.
    """

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
        """
        Base get card method.
        """

        raise NotImplementedError

    @abstractmethod
    def generate_card(self):
        """
        Base generate card method.
        """

        raise NotImplementedError

    def _generate_nn_models(self) -> None:
        """
        Create and load weights for used nn models.
        """

        if self.sr_weights_path is not None:
            self.sr_model = ninasr_b0(scale=4, pretrained=False)
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

    def _url_to_bytes(self, card_image_url: str) -> bytes | None:
        """
        Card image URL to bytes response.
        """

        time.sleep(0.1)  # required
        if "?" in card_image_url:
            card_image_url = card_image_url.split("?")[0]
        if not (
            card_image_response := self.session.get(
                url=card_image_url,
                verify=True,
            )
        ).ok:
            return

        return card_image_response.content

    def process_card_image(
        self, card_image_bytes: bytes, width: int, height: int
    ) -> np.ndarray:
        """
        Card image processing pipeline.
        """

        card_image = cv2.imdecode(
            np.frombuffer(card_image_bytes, np.uint8), cv2.IMREAD_UNCHANGED
        )
        card_image = convert_16bit_to_8bit(card_image)
        card_image = replace_alpha_with_solid(card_image)
        card_image = apply_superes_and_denoiser_pipeline(
            card_image, self.sr_model, self.denoise_model, width, height, self.device
        )

        return card_image


class MTGProxifier(CardGameProxifier):
    """
    MTG card game proxifier class.
    """

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
        """
        MTG get card method.
        """

        pass

    def generate_card(self):
        """
        MTG generate card method.
        """

        pass


class FABProxifier(CardGameProxifier):
    """
    FAB card game proxifier class.
    """

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
                get_ext_file(os.path.join(collection_output_path, name))
            )

    def _get_card_by_api(self, card_name: str) -> dict | None:
        """
        FAB get card using FABDB API: https://fabdb.net/resources/api.
        Not stable for tokens.
        """

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

        if (card_image_bytes := self._url_to_bytes(card_data.get("image", ""))) is None:
            return

        return card_image_bytes

    def _get_card_by_collection(self, card_name: str) -> tuple | None:
        """
        FAB get card using collection data: https://github.com/the-fab-cube/flesh-and-blood-cards.
        """

        # Card name and pitch value delimiter: "_"
        if "_" in card_name:
            card_name, card_pitch = card_name.split("_")
        else:
            card_pitch = PITCHES("")

        card_data = self.cards_collection_parser.at_pointer(
            f"/cards/{card_name}/{card_pitch}"
        )

        if (
            card_image_bytes := self._url_to_bytes(card_data.at_pointer("/image_url"))
        ) is None:
            return

        tokens_bytes = []
        tokens_names = set()
        for token_type in ["tokens", "backside"]:
            if card_data.at_pointer(f"/{token_type}") is not None:
                for token_name in card_data.at_pointer(f"/{token_type}"):
                    if (
                        token_image_bytes := self._url_to_bytes(
                            self.cards_collection_parser.at_pointer(
                                f"/cards/{token_name}/{PITCHES[""]}/image_url"
                            )
                        )
                    ) is not None:
                        tokens_bytes.append(token_image_bytes)
                        tokens_names.add(token_name)

        return card_image_bytes, tokens_bytes, tokens_names

    def get_card(self, card_name: str) -> list | None:
        """
        FAB get card method.
        """

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
        processed_token_names: set | None = None,
    ) -> dict:
        """
        FAB generate card method.
        """

        if (card_payload := self.get_card(card_name)) is None:
            return
        
        card_bytes, tokens_bytes, tokens_names = card_payload

        card = self.process_card_image(
            card_bytes,
            on_canvas_card_width_pixels,
            on_canvas_card_height_pixels,
        )

        tokens = []
        for token_name, token_bytes in zip(tokens_names, tokens_bytes):
            if processed_token_names is None or token_name not in processed_token_names:
                tokens.append(
                    self.process_card_image(
                        token_bytes,
                        on_canvas_card_width_pixels,
                        on_canvas_card_height_pixels
                    )
                )
        processed_token_names.update(tokens_names)

        return card, tokens
