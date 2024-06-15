import os
from math import ceil
from itertools import batched
from tempfile import TemporaryDirectory

from tqdm import tqdm
from core import Canvas, MTGProxifier, FABProxifier, CardProxyError, parse_decklist


class Runner:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.canvas = Canvas(dpi=300)
        self.decklist = parse_decklist(config.path_to_decklist)
        match config.card_game_alias:
            case "fab":
                self.proxifier = FABProxifier(
                    sr_weights_path=config.path_to_sr_weights,
                    denoise_weights_path=config.path_to_denoise_weights,
                    collection_input_path=config.path_to_collection_input,
                    collection_output_path=config.path_to_collection_output,
                )
            case "mtg":
                self.proxifier = MTGProxifier(
                    sr_weights_path=config.path_to_sr_weights,
                    denoise_weights_path=config.path_to_denoise_weights,
                )
            case _:
                raise CardProxyError(
                    f"{config.card_game_alias} not available. Only 'mtg' or 'fab' supported."
                )

    def _collect_decklist_cards_and_tokens(self) -> list:
        main_cards = []
        main_tokens = []
        processed_token_names = []

        with tqdm(
            self.decklist,
            total=len(self.decklist),
            ascii=True,
            desc="[CARD-PROXY-PRINTER] Collect cards and associated tokens from decklist",
        ) as pbar:
            for card_count, card_name, card_pitch in pbar:
                if (
                    card_and_tokens := self.proxifier.generate_card(
                        f"{card_name}_{card_pitch}",
                        self.canvas.on_canvas_card_width_pixels,
                        self.canvas.on_canvas_card_height_pixels,
                    )
                ) is not None:
                    card, tokens = card_and_tokens

                    for _ in range(card_count):
                        main_cards.append(card)

                    for token_name, token in tokens.items():
                        if token_name not in processed_token_names:
                            main_tokens.append(token)
                            processed_token_names.append(token_name)

        return main_cards + main_tokens

    def run(self):
        cards_and_tokens = self._collect_decklist_cards_and_tokens()
        num_pages = ceil(
            len(cards_and_tokens)
            / (
                self.canvas.num_cards_per_page_width
                * self.canvas.num_cards_per_page_height
            )
        )

        if not os.path.exists(self.config.path_to_output):
            os.makedirs(self.config.path_to_output, exist_ok=True)

        with TemporaryDirectory(
            prefix="tmpdir_", dir=self.config.path_to_output
        ) as tmpdir:
            for batch_index, batch_cards in enumerate(
                batched(
                    cards_and_tokens,
                    self.canvas.num_cards_per_page_width
                    * self.canvas.num_cards_per_page_height,
                )
            ):
                self.canvas.new_page(batch_index + 1, num_pages)
                self.canvas.fill_page(batch_cards)
                self.canvas.save_page(tmpdir)
            self.canvas.save_pdf(
                tmpdir, self.config.path_to_output, self.config.card_game_alias
            )
