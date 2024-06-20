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
    superes_and_denoiser_pipeline,
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

    def generate_card(
        self,
        first_card_part: str,
        second_card_part: int,
        on_canvas_card_width_pixels: int,
        on_canvas_card_height_pixels: int,
    ) -> tuple | None:
        """
        Generate card method.
        """

        if (payload := self.get_card(first_card_part, second_card_part)) is None:
            return

        cards_bytes, tokens_bytes, tokens_names = payload

        cards = [
            self.process_card_image(
                card_bytes,
                on_canvas_card_width_pixels,
                on_canvas_card_height_pixels,
                apply_denoiser=not self.device.type == "cpu",
            )
            for card_bytes in cards_bytes
        ]

        tokens = {
            token_name: self.process_card_image(
                token_bytes,
                on_canvas_card_width_pixels,
                on_canvas_card_height_pixels,
                apply_denoiser=not self.device.type == "cpu",
            )
            for token_name, token_bytes in zip(tokens_names, tokens_bytes)
        }

        return cards, tokens

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
            self.sr_model.to(self.device)
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
            self.denoise_model.to(self.device)
            self.denoise_model.eval()
            for _, v in self.denoise_model.named_parameters():
                v.requires_grad = False

    def _url_to_bytes(self, card_image_url: str | None) -> bytes | None:
        """
        Card image URL to bytes response.
        """

        if card_image_url is None:
            return

        if "?" in card_image_url:
            card_image_url = card_image_url.split("?")[0]

        time.sleep(0.01)  # required
        if not (
            card_image_response := self.session.get(
                url=card_image_url,
                verify=True,
            )
        ).ok:
            return

        return card_image_response.content

    def process_card_image(
        self,
        card_image_bytes: bytes,
        width: int,
        height: int,
        apply_denoiser: bool = True,
    ) -> np.ndarray:
        """
        Card image processing pipeline.
        """

        card_image = cv2.imdecode(
            np.frombuffer(card_image_bytes, np.uint8), cv2.IMREAD_UNCHANGED
        )
        card_image = convert_16bit_to_8bit(card_image)
        card_image = replace_alpha_with_solid(card_image)
        card_image = superes_and_denoiser_pipeline(
            card_image,
            self.sr_model,
            self.denoise_model,
            apply_denoiser,
            width,
            height,
            self.device,
        )

        return card_image


class MTGProxifier(CardGameProxifier):
    """
    MTG card game proxifier class.
    """

    def __init__(
        self,
        name: str = "mtg",
        endpoint: str = "https://api.scryfall.com/cards",
        sr_weights_path: str | None = None,
        denoise_weights_path: str | None = None,
    ) -> None:
        super().__init__(name, endpoint, sr_weights_path, denoise_weights_path)

    def get_card(
        self,
        card_set_alias: str,
        card_set_collector_number: int,
        image_uri_version: str = "png",
    ):
        """
        MTG get card method.
        """

        time.sleep(0.01)  # required
        if not (
            card_data_response := self.session.get(
                url=f"{self.endpoint}/{card_set_alias}/{card_set_collector_number}",
                verify=True,
            )
        ).ok:
            print(
                f"[CARD-PROXY-PRINTER] Can not get {card_set_alias}-{card_set_collector_number} card data, skipping..."
            )
            return

        card_data = card_data_response.json()
        card_faces = (
            card_data["card_faces"]
            if card_data.get("card_faces", None) is not None
            else [card_data]
        )

        is_split_card = False
        cards_bytes = []
        for card_face in card_faces:
            if (
                card_image_bytes := self._url_to_bytes(
                    card_face.get("image_uris", {}).get(image_uri_version, None)
                )
            ) is None:
                is_split_card = True
                break

            cards_bytes.append(card_image_bytes)

        if is_split_card:
            if (
                card_image_bytes := self._url_to_bytes(
                    card_data.get("image_uris", {}).get(image_uri_version, None)
                )
            ) is None:
                print(
                    f"[CARD-PROXY-PRINTER] Can not fetch {card_set_alias}-{card_set_collector_number} card image, skipping..."
                )
                return

            cards_bytes.append(card_image_bytes)

        tokens_bytes = []
        tokens_names = []
        if (token_parts := card_data.get("all_parts", None)) is not None:
            for token_part in token_parts:
                if token_part["component"] != "token":
                    continue

                time.sleep(0.01)  # required
                if (
                    token_part_data := self.session.get(
                        url=token_part["uri"], verify=True
                    )
                ).ok:
                    token_data = token_part_data.json()

                    if (
                        token_image_bytes := self._url_to_bytes(
                            token_data.get("image_uris", {}).get(
                                image_uri_version, None
                            )
                        )
                    ) is None:
                        print(
                            (
                                f"[CARD-PROXY-PRINTER] Can not fetch {token_data['set']}-{token_data['collector_number']} "
                                "token image, skipping..."
                            )
                        )
                        continue

                    tokens_bytes.append(token_image_bytes)
                    tokens_names.append(
                        f"{token_data['set']}-{token_data['collector_number']}"
                    )

        return cards_bytes, tokens_bytes, tokens_names


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
            create_fab_cards_collection(collection_input_path, collection_output_path)
            self.cards_collection_parser = Parser().load(
                get_ext_file(collection_output_path)
            )

    def _get_card_by_api(self, card_name: str) -> dict | None:
        """
        FAB get card using FABDB API: https://fabdb.net/resources/api.
        Not stable for tokens.
        """

        # Card name and pitch value delimiter: "_"
        card_name = card_name.replace("_", "-")

        time.sleep(0.01)  # required
        if not (
            card_data_response := self.session.get(
                url=f"{self.endpoint}/{card_name}",
                verify=True,
            )
        ).ok:
            return

        card_data = card_data_response.json()

        if (
            card_image_bytes := self._url_to_bytes(card_data.get("image", None))
        ) is None:
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
            card_pitch = PITCHES[""]

        card_data = self.cards_collection_parser.at_pointer(
            f"/cards/{card_name}/{card_pitch}"
        )

        if (
            card_image_bytes := self._url_to_bytes(card_data.at_pointer("/image_url"))
        ) is None:
            print(
                f"[CARD-PROXY-PRINTER] Can not find {card_name}_{card_pitch} card, skipping..."
            )
            return

        cards_bytes = [card_image_bytes]

        tokens_bytes = []
        tokens_names = []
        for token_type in ["tokens", "backside"]:
            if card_data.at_pointer(f"/{token_type}") is not None:
                for token_name in card_data.at_pointer(f"/{token_type}"):
                    if "_" in token_name:
                        token_name, token_pitch = token_name.split("_")
                    else:
                        token_pitch = PITCHES[""]

                    if (
                        token_image_bytes := self._url_to_bytes(
                            self.cards_collection_parser.at_pointer(
                                f"/cards/{token_name}/{token_pitch}/image_url"
                            )
                        )
                    ) is not None:
                        tokens_bytes.append(token_image_bytes)
                        tokens_names.append(token_name)

        return cards_bytes, tokens_bytes, tokens_names

    def get_card(self, card_name: str, card_pitch: str) -> list | None:
        """
        FAB get card method.
        """

        full_card_name = f"{card_name}_{card_pitch}"

        return (
            self._get_card_by_api(full_card_name)
            if self.use_api
            else self._get_card_by_collection(full_card_name)
        )
