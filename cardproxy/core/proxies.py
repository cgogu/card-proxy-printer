import json
import time
from abc import ABC, abstractmethod

import cv2
import numpy as np
import torch
from requests import Session
from simdjson import Parser

from cardproxy.helper_repos.denoise.scunet.models.network_scunet import SCUNet
from cardproxy.helper_repos.sr.torchsr.torchsr.models import (
    ninasr_b0,
)  # speed - quality tradeoff

from .constants import PITCHES
from .decorators import deprecated
from .fab_collection import create_fab_cards_collection
from .image_ops import (
    convert_16bit_to_8bit,
    replace_alpha_with_solid,
    superes_and_denoiser_pipeline,
)
from .utils import get_ext_file


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

        cards_bytes, cards_names, tokens_bytes, tokens_names = payload

        cards = [
            self.process_card_image(
                card_bytes,
                on_canvas_card_width_pixels,
                on_canvas_card_height_pixels,
                apply_denoiser=not self.device.type == "cpu",
                apply_sr=not self.device.type == "cpu",
                apply_rotation="--" in card_name,  # FAB split cards with "//"
            )
            for card_name, card_bytes in zip(cards_names, cards_bytes, strict=False)
        ]

        tokens = {
            token_name: self.process_card_image(
                token_bytes,
                on_canvas_card_width_pixels,
                on_canvas_card_height_pixels,
                apply_denoiser=not self.device.type == "cpu",
                apply_sr=not self.device.type == "cpu",
            )
            for token_name, token_bytes in zip(tokens_names, tokens_bytes, strict=False)
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
        apply_sr: bool = True,
        apply_rotation: bool = False,
    ) -> np.ndarray:
        """
        Card image processing pipeline.
        """

        card_image = cv2.imdecode(
            np.frombuffer(card_image_bytes, np.uint8), cv2.IMREAD_UNCHANGED
        )
        card_image = convert_16bit_to_8bit(card_image)
        if apply_rotation:
            card_image = cv2.rotate(card_image, rotateCode=cv2.ROTATE_90_CLOCKWISE)
        card_image = replace_alpha_with_solid(card_image)
        card_image = superes_and_denoiser_pipeline(
            card_image,
            self.sr_model,
            self.denoise_model,
            apply_denoiser,
            width,
            height,
            self.device,
            apply_sr=apply_sr,
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
        cards_names = []
        for card_face in card_faces:
            if (
                card_image_bytes := self._url_to_bytes(
                    card_face.get("image_uris", {}).get(image_uri_version, None)
                )
            ) is None:
                is_split_card = True
                break

            cards_bytes.append(card_image_bytes)
            cards_names.append({card_set_alias} - {card_set_collector_number})

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
            cards_names.append({card_set_alias} - {card_set_collector_number})

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

                                f"[CARD-PROXY-PRINTER] Can not fetch {token_data['set']}-{token_data['collector_number']} "
                                "token image, skipping..."

                        )
                        continue

                    tokens_bytes.append(token_image_bytes)
                    tokens_names.append(
                        f"{token_data['set']}-{token_data['collector_number']}"
                    )

        return cards_bytes, cards_names, tokens_bytes, tokens_names


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
        interactive: bool = True,
    ) -> None:
        super().__init__(name, endpoint, sr_weights_path, denoise_weights_path, use_api)
        self._identifier_index: dict[str, tuple[str, str]] = {}
        if not use_api:
            create_fab_cards_collection(
                collection_input_path,
                collection_output_path,
                interactive=interactive,
            )
            collection_path = get_ext_file(collection_output_path)
            self.cards_collection_parser = Parser().load(collection_path)
            self._identifier_index = self._build_identifier_index(collection_path)

    @staticmethod
    def _build_identifier_index(collection_path: str) -> dict:
        """
        Map upper-cased set identifiers (e.g. 'SEA082') to ``(name, pitch)`` so
        fabrary-style set-code lookups work against the name-keyed collection.
        """

        with open(collection_path, encoding="utf-8") as f:
            raw = json.load(f)
        index: dict[str, tuple[str, str]] = {}
        for name, pitches in raw.get("cards", {}).items():
            for pitch, card in pitches.items():
                identifier = (card or {}).get("identifier")
                if identifier:
                    index[str(identifier).upper()] = (name, pitch)
        return index

    @deprecated("Use get_card_by_collection() instead.")
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

    def _get_card_by_collection(self, card_name: str, card_pitch: str) -> tuple | None:
        """
        FAB get card using collection data: https://github.com/the-fab-cube/flesh-and-blood-cards.
        """

        try:
            card_data = self.cards_collection_parser.at_pointer(
                f"/cards/{card_name}/{card_pitch}"
            )
        except (KeyError, ValueError, TypeError):
            print(
                f"[CARD-PROXY-PRINTER] Can not find {card_name}_{card_pitch} card, skipping..."
            )
            return

        if (
            card_image_bytes := self._url_to_bytes(card_data.at_pointer("/image_url"))
        ) is None:
            print(
                f"[CARD-PROXY-PRINTER] Can not find {card_name}_{card_pitch} card, skipping..."
            )
            return

        cards_bytes = [card_image_bytes]
        cards_names = [card_name]

        tokens_bytes: list = []
        tokens_names: list = []
        for token_type in ["tokens", "backside"]:
            token_list = card_data.at_pointer(f"/{token_type}")
            if token_list is None:
                continue
            for token_entry in token_list:
                token_entry_str = str(token_entry)
                if "_" in token_entry_str:
                    tk_name, tk_pitch = token_entry_str.split("_", 1)
                else:
                    tk_name = token_entry_str
                    tk_pitch = PITCHES[""]
                try:
                    token_image_url = self.cards_collection_parser.at_pointer(
                        f"/cards/{tk_name}/{tk_pitch}/image_url"
                    )
                except (KeyError, ValueError, TypeError):
                    continue
                token_image_bytes = self._url_to_bytes(token_image_url)
                if token_image_bytes is None:
                    continue
                tokens_bytes.append(token_image_bytes)
                tokens_names.append(tk_name)

        return cards_bytes, cards_names, tokens_bytes, tokens_names

    def get_card(self, card_name: str, card_pitch: str) -> list | None:
        """
        FAB get card method. ``card_name`` may be either an encoded card name
        (paired with ``card_pitch``) or a set identifier such as ``SEA082``
        (resolved through the identifier index built at load time).
        """

        if card_name:
            resolved = self._identifier_index.get(card_name.upper())
            if resolved is not None:
                card_name, card_pitch = resolved

        if self.use_api:
            return self._get_card_by_api(f"{card_name}_{card_pitch}")
        return self._get_card_by_collection(card_name, card_pitch)
