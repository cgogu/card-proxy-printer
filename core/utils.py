import argparse
import re
import os
import json
from string import punctuation
from glob import glob, iglob
from datetime import datetime

import torch
import cv2
import numpy as np
from tqdm import tqdm
from git import Repo
from simdjson import Parser
from easydict import EasyDict as edict
from yaml import safe_load
from torchvision.transforms.functional import to_pil_image, to_tensor
from unidecode import unidecode
from helper_repos.denoise.scunet.utils.utils_image import uint2tensor4, tensor2uint
from .models import CardModel

PITCHES = {
    "": "colorless",  # empty pitch naming convention (e.g. heroes, arms, equipment, etc.)
    "1": "red",
    "2": "yellow",
    "3": "blue",
}


class CardProxyError(Exception):
    """
    Base exception.
    """

    pass


def get_cfg() -> argparse.Namespace:
    """
    Arguments parser.
    """

    parser = argparse.ArgumentParser(description="Card proxy printer")
    parser.add_argument(
        "--config",
        type=str,
        help="The aggregated config file",
    )
    parser.add_argument(
        "--card-game-alias",
        type=str,
        help="The card game alias (MTG or FAB)",
    )
    parser.add_argument(
        "--path-to-decklist",
        type=str,
        help="Path to decklist to be proxied",
    )
    parser.add_argument(
        "--path-to-output",
        type=str,
        help="Path to output to save the proxied decklist",
    )
    parser.add_argument(
        "--path-to-sr-weights",
        type=str,
        help="Path to super resolution model weights",
    )
    parser.add_argument(
        "--path-to-denoise-weights",
        type=str,
        help="Path to denoision model weights",
    )
    parser.add_argument(
        "--path-to-collection-input",
        type=str,
        help="Path to local card collection that needs parsing",
    )
    parser.add_argument(
        "--path-to-collection-output",
        type=str,
        help="Path to save local card collection after parsing",
    )
    return parser.parse_args()


def parse_config(config: argparse.Namespace) -> edict | argparse.Namespace:
    """
    Configuration file injector with external file.
    """

    if hasattr(config, "config"):
        with open(config.config, "r", encoding="utf-8") as config_file:
            config_data = safe_load(config_file)

        if (
            config_data.get("path_to_data", None) is None
            or config_data.get("card_game_alias", None) is None
        ):
            raise CardProxyError("Need to provide the data path and card game alias")

        config_data["path_to_collection_input"] = os.path.join(
            config_data["path_to_collection_input"], config_data["card_game_alias"]
        )

        for path, dirname in [
            ["path_to_decklist", "input"],
            ["path_to_output", "output"],
            ["path_to_collection_output", "collection"],
        ]:
            config_data[path] = os.path.join(
                config_data["path_to_data"], config_data["card_game_alias"], dirname
            )

        config = edict(config_data)
    else:
        if (
            not hasattr(config, "path_to_decklist")
            or not hasattr(config, "path_to_output")
            or not hasattr(config, "path_to_collection_output")
        ):
            raise CardProxyError(
                "Need to provide the run configuration file or full cli arguments."
            )

    return config


def get_ext_file(input_path: str, ext: str = "json") -> str | None:
    """
    Get json file from path.
    """

    if not os.path.exists(input_path):
        return

    if len((ext_file := glob(os.path.join(input_path, f"*.{ext}")))) == 0:
        return

    return ext_file[0]


def replace_alpha_with_solid(
    image: np.ndarray,
    solid_color: list = [0, 0, 0],
    is_rgb: bool = False,
) -> np.ndarray:
    """
    Replace the alpha channel from an image with a solid color.
    """

    # Check if the image has an alpha channel
    if image.shape[2] == 4:
        # Split the image into channels
        if is_rgb:
            red_ch, green_ch, blue_ch, alpha_ch = cv2.split(image)
        else:
            blue_ch, green_ch, red_ch, alpha_ch = cv2.split(image)

        # Compute the alpha value between 0-1
        alpha = alpha_ch / 255.0

        # Replace the alpha channel with the specified color
        chs = [
            (solid_color[0 if is_rgb else 2] * (1.0 - alpha) + red_ch * alpha).astype(
                np.uint8
            ),
            (solid_color[1] * (1.0 - alpha) + green_ch * alpha).astype(np.uint8),
            (solid_color[2 if is_rgb else 0] * (1.0 - alpha) + blue_ch * alpha).astype(
                np.uint8
            ),
        ]

        # Merge the channels back
        image = cv2.merge(chs if is_rgb else chs[::-1]).astype(np.uint8)

    return image


def convert_16bit_to_8bit(image: np.ndarray) -> np.ndarray:
    """
    Convert image from 16-bit to 8-bit.
    """

    if image.dtype == np.uint8:
        return image

    return (image / 256).astype(np.uint8)


def superes_and_denoiser_pipeline(
    card_image: np.ndarray,
    sr_model: torch.nn.Module,
    denoise_model: torch.nn.Module,
    apply_denoiser: bool,  # CPU heavy
    width: int,
    height: int,
    device: torch.device,
) -> np.ndarray:
    """
    Run super-resolution and denoising nn models over the input image.
    """

    # Denoise
    if apply_denoiser:
        noisy_tensor = uint2tensor4(card_image).to(device)
        clean_tensor = denoise_model(noisy_tensor)
        card_image = tensor2uint(clean_tensor)

    # Super resolution
    low_res_tensor = to_tensor(card_image).unsqueeze(0).to(device)
    high_res_tensor = sr_model(low_res_tensor)
    high_res_image = np.asarray(
        to_pil_image(high_res_tensor.squeeze(0).clamp(0, 1)), dtype=np.uint8
    )

    # Resize to standard
    return cv2.resize(high_res_image, (width, height), interpolation=cv2.INTER_AREA)


def sync_with_remote(repo_path: str, verbose: bool = True) -> tuple:
    """
    Synchronize local branch with remote.
    """

    repo = Repo(repo_path)
    assert not repo.bare  # ensure the repo is not bare

    # get the current active branch
    active_branch = repo.active_branch

    # fetch the latest changes from the remote
    origin = repo.remotes.origin
    origin.fetch(verbose=verbose)

    # get the commit that the remote is at
    remote_commit = repo.commit(f"origin/{active_branch.name}")

    # get the commit that the local branch is at
    local_commit = repo.commit(active_branch.name)

    # calculate the difference in the number of commits
    num_commits_behind = len(
        [*repo.iter_commits(f"{local_commit.hexsha}..{remote_commit.hexsha}")]
    )

    print(
        f"[CARD-PROXY-PRINTER] Local branch is {num_commits_behind} commits behind remote branch."
    )

    # if the local branch is behind, pull the changes
    pull_response = "no"
    if num_commits_behind > 0:
        while True:
            pull_response = input(
                "[CARD-PROXY-PRINTER] Might want to fetch all latest changes. Enter yes/no to continue: "
            )
            if pull_response == "yes" or pull_response == "no":
                break

        if pull_response == "yes":
            print("[CARD-PROXY-PRINTER] Pulling changes...")
            origin.pull(verbose=verbose)
            print("[CARD-PROXY-PRINTER] Local branch code is now up to date.")
        else:
            print("[CARD-PROXY-PRINTER] Skipping code actualization.")
    else:
        print("[CARD-PROXY-PRINTER] Skipping code actualization.")

    return repo.commit(active_branch.name), pull_response == "yes"


def encode_name(name: str, separator: str = "-") -> str:
    """
    Encode name by eliminating all punctuation and replacing white spaces with separator.
    ex: Test's name.. -> tests name -> tests-name
    """

    # Need to add "…" to punctuation
    return (
        "".join(ch for ch in unidecode(name) if ch not in punctuation + "\u2026")
        .lower()
        .replace(" ", separator)
    )


def split_name_and_pitch(name_and_pitch: str, separator: str = "-") -> tuple:
    """
    Split name and pitch. Add pitch when non existent and encode the name.
    """

    encoded = encode_name(name_and_pitch)
    encoded_splits = encoded.split(separator)

    if encoded_splits[-1] in ["red", "yellow", "blue"]:
        return f"{separator}".join(encoded_splits[:-1]), encoded_splits[-1]
    return encoded, PITCHES[""]


def parse_decklist(path_to_decklist: str, card_games_alias: str) -> list:
    """
    Parse and process decklist to respect the encoded format (see above).
    """

    if not os.path.exists(path_to_decklist):
        raise CardProxyError(f"{path_to_decklist} does not exist.")

    if (decklist_file_path := get_ext_file(path_to_decklist, ext="txt")) is None:
        raise CardProxyError(f"No text decklist can be found at {path_to_decklist}.")

    decklist = []
    with open(decklist_file_path, mode="r", encoding="utf-8") as decklist_file:
        while line := decklist_file.readline():
            match card_games_alias:
                case "fab":
                    card_count, card_name = re.match(
                        r"(\d+)\s(.*)\s*", line.rstrip(), flags=re.VERBOSE
                    ).groups()
                    card_name, card_pitch = split_name_and_pitch(card_name)
                    decklist.append((int(card_count), card_name, card_pitch))
                case "mtg":
                    card_count, card_set_alias, card_set_collector_number = re.match(
                        r"(\d+)\s.*\(([a-zA-Z0-9]+)\)\s([a-zA-Z0-9-]+)",
                        line.rstrip(),
                        flags=re.VERBOSE,
                    ).groups()

                    if card_set_alias == "PLST":
                        card_set_alias, card_set_collector_number = (
                            card_set_alias.split("-")
                        )

                    decklist.append(
                        (
                            int(card_count),
                            card_set_alias.lower(),
                            card_set_collector_number,
                        )
                    )
                case _:
                    raise CardProxyError(
                        f"Card games alias '{card_games_alias}' not supported."
                    )

    return decklist


def create_fab_cards_collection(
    path_to_data_root: str,
    path_to_data_output: str,
) -> None:
    """
    Create FAB card collection snapshot based on the-fab-cube:
    https://github.com/the-fab-cube/flesh-and-blood-cards.
    """

    def __track_card_uuids(uuids_to_name: dict, card: CardModel) -> None:
        """
        Keep track of all unique identifiers.
        """

        uuids_to_name[card.uuid] = (
            f"{card.name}-{card.pitch}" if card.pitch != PITCHES[""] else card.name
        )
        uuids_to_name[card.printing_uuid] = (
            f"{card.name}-{card.pitch}" if card.pitch != PITCHES[""] else card.name
        )

    # Set repo and root of data collection
    if not os.path.exists(path_to_data_root):
        raise CardProxyError(f"{path_to_data_root} does not exist.")

    # Sync collection with latest changes
    repo_path = next(iglob(os.path.join(path_to_data_root, "*")))
    repo_commit, is_new_collection_available = sync_with_remote(repo_path=repo_path)

    root_path = next(
        iglob(
            os.path.join(
                repo_path,
                "**",
                "english",
            ),
            recursive=True,
        )
    )
    past_cards_collection_path = get_ext_file(path_to_data_output)

    if is_new_collection_available and past_cards_collection_path is not None:
        while True:
            overwrite_response = input(
                "[CARD-PROXY-PRINTER] Overwrite card collection? Enter yes/no to continue: "
            )
            if overwrite_response == "yes" or overwrite_response == "no":
                break

    if (
        is_new_collection_available and overwrite_response == "yes"
    ) or past_cards_collection_path is None:
        # FAB collection parsing, cleaning, and saving

        fab_cards_collection = {}
        uuids_to_name = {}

        if not os.path.exists(
            (
                card_flattened_input_json_path := os.path.join(
                    root_path, "card-flattened.json"
                )
            )
        ):
            raise CardProxyError(f"card-flattened.json cannot be found at {root_path}")

        cards_parser = Parser().load(card_flattened_input_json_path)
        with tqdm(
            cards_parser,
            total=len(cards_parser),
            ascii=True,
            desc="[CARD-PROXY-PRINTER] Creating new card collection",
        ) as pbar:
            for card_data in pbar:
                card = CardModel(
                    uuid=card_data.get("unique_id"),
                    printing_uuid=card_data.get("printing_unique_id"),
                    identifier=card_data.get("id"),
                    name=encode_name(card_data.get("name")),
                    foiling=card_data.get("foiling"),
                    pitch=PITCHES[card_data.get("pitch")],
                    is_hero="Hero" in card_data.get("types", []),
                    is_token="Token" in card_data.get("types", []),
                    image_url=card_data.get("image_url"),
                )

                if "metadata" not in fab_cards_collection:
                    fab_cards_collection["metadata"] = {
                        "author": "cgogu",
                        "datetime": datetime.now().strftime("%d/%m/%Y-%H:%M:%S"),
                        "hash": str(repo_commit),
                        "dpi": card.dpi,
                        "width_inch": card.width_inch,
                        "height_inch": card.height_inch,
                        "bleed_area_inch": card.bleed_area_inch,
                        "width_pixels": card.width_pixels,
                        "height_pixels": card.height_pixels,
                    }

                # Skip wrong format
                if card.image_url is not None:
                    lower_card_image_url = card.image_url.lower()
                    if (
                        "/eng/" in lower_card_image_url
                        or "/promos/" in lower_card_image_url
                        or "/en_out_" in lower_card_image_url
                        or "_v2" in lower_card_image_url  # alternate artwork (full art)
                        or (
                            card.is_hero and "_back" in lower_card_image_url
                        )  # alternate artwork (full art)
                    ):
                        __track_card_uuids(uuids_to_name, card)
                        continue

                # Keep only standard foiling cards and keep track of all uuids
                if (
                    fab_cards_collection.get(card.name, {}).get(card.pitch, None)
                    is not None
                ):
                    if card.foiling != "S":
                        __track_card_uuids(uuids_to_name, card)
                        continue

                # Keep only standard image url, skip modified request parameters, and keep track of all uuids
                # If only modified url exists, keep it
                if (
                    current_image_url := fab_cards_collection.get(card.name, {})
                    .get(card.pitch, {})
                    .get("image_url", None)
                ) is not None:
                    # Current image url exists and is as expected
                    if not ".width" in current_image_url:
                        __track_card_uuids(uuids_to_name, card)
                        continue

                # Get the back ids only for front cards that are double sided
                backside_cards = []
                if (
                    inpt_double_sided_cards := card_data.get(
                        "double_sided_card_info", None
                    )
                ) is not None:
                    for ds_card in inpt_double_sided_cards:
                        if ds_card["is_front"] and ds_card["is_DFC"]:
                            backside_cards.append(ds_card["other_face_unique_id"])

                if len(backside_cards) > 0:
                    card.backside = backside_cards

                # Get the reference ids cards that generate other cards (like tokens)
                token_cards = []
                if (
                    input_token_cards := card_data.get("referenced_cards", None)
                ) is not None:
                    for reference_card in input_token_cards:
                        token_cards.append(reference_card)

                if len(token_cards) > 0:
                    card.tokens = token_cards

                # Add same name, but different pitch card
                if "cards" not in fab_cards_collection:
                    fab_cards_collection["cards"] = {}
                if card.name in fab_cards_collection["cards"]:
                    fab_cards_collection["cards"][card.name][card.pitch] = (
                        card.model_dump(
                            exclude=["name", "width_pixels", "height_pixels"]
                        )
                    )
                else:
                    fab_cards_collection["cards"][card.name] = {
                        card.pitch: card.model_dump(
                            exclude=["name", "width_pixels", "height_pixels"]
                        )
                    }

                __track_card_uuids(uuids_to_name, card)

            # Change backsides and tokens uuids to names
            for cards in fab_cards_collection["cards"].values():
                for card in cards.values():
                    # Backsides
                    if card["backside"] is not None:
                        backsides = []
                        has_pitch = False

                        for backside_uuid in card["backside"]:
                            backside_name_splits = uuids_to_name[backside_uuid].split(
                                "-"
                            )

                            # Backsides can have pitch values
                            for pitch in PITCHES.values():
                                if pitch == "colorless":
                                    continue

                                if backside_name_splits[-1] == pitch:
                                    has_pitch = True

                            backsides.append(
                                "-".join(backside_name_splits[:-1])
                                + "_"
                                + backside_name_splits[-1]
                                if has_pitch
                                else "-".join(backside_name_splits)
                            )
                            has_pitch = False

                        card["backside"] = backsides

                    # Tokens
                    if card["tokens"] is not None:
                        token_names = (
                            uuids_to_name[token_uuid] for token_uuid in card["tokens"]
                        )
                        # Tokens are always colorless
                        tokens = [
                            *{
                                token_name
                                for token_name in token_names
                                if fab_cards_collection["cards"]
                                .get(token_name, {})
                                .get(PITCHES[""], {})
                                .get("is_token")
                            }
                        ]
                        card["tokens"] = tokens if len(tokens) > 0 else None

            # Save collection snapshot on disk
            if not os.path.exists(path_to_data_output):
                os.makedirs(path_to_data_output, exist_ok=True)

            if past_cards_collection_path is not None and overwrite_response == "yes":
                os.remove(past_cards_collection_path)

            with open(
                os.path.join(
                    path_to_data_output,
                    f"fab-cards-collection-commit-{repo_commit}.json",
                ),
                mode="w",
                encoding="utf-8",
            ) as cards_collection_file:
                json.dump(fab_cards_collection, cards_collection_file, indent=4)

            print("[CARD-PROXY-PRINTER] Saved and using new card collection.")
    else:
        print("[CARD-PROXY-PRINTER] Using current card collection.")


# entry = "1 Sea Gate Restoration // Sea Gate, Reborn (ZNR) 333 *F*"
# pattern = r"(\d+)\s.*\((\w+)\)\s(\d+)"
# match = re.search(pattern, entry)

# if match:
#     output = " ".join(match.groups())
#     print(output)  # prints: 1 ZNR 333
# else:
#     print("No match found.")

# In the regular expression (\d+)\s.*\((\w+)\)\s(\d+):

# (\d+) matches one or more digits, which is the quantity of the card.
# .* matches any character (except newline), which is used to skip the card name. If capture is used (.*), the name will be part of the groups.
# \((\w+)\) matches any word character (equal to [a-zA-Z0-9_]) between parentheses, which is the set code.
# (\d+) matches one or more digits, which is the card number.
