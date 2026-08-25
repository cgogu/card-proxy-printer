import json
import os
from datetime import datetime
from glob import glob, iglob

from git import Repo
from simdjson import Parser
from tqdm import tqdm

from .constants import PITCHES
from .decklist import encode_name
from .errors import CardProxyError
from .git_sync import sync_with_remote
from .models import CardModel, CollectionMetadata


def create_fab_cards_collection(
    path_to_data_root: str,
    path_to_data_output: str,
    interactive: bool = True,
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

    if not os.path.exists(path_to_data_root):
        raise CardProxyError(f"{path_to_data_root} does not exist.")

    # Sync collection with latest changes
    repo_path = next(iglob(os.path.join(path_to_data_root, "*")))
    repo_commit, _ = sync_with_remote(repo_path=repo_path, interactive=interactive)

    root_path = next(
        iglob(
            os.path.join(
                repo_path,
                "json",
                "english",
            ),
            recursive=True,
        )
    )
    # Regenerate only when the on-disk snapshot's commit no longer matches HEAD.
    expected_collection_path = os.path.join(
        path_to_data_output,
        f"fab-cards-collection-commit-{repo_commit}.json",
    )

    if not os.path.exists(expected_collection_path):
        fab_cards_collection: dict = {"cards": {}}
        uuids_to_name: dict = {}

        if not os.path.exists(

                card_flattened_input_json_path := os.path.join(
                    root_path, "card-flattened.json"
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
                    art_variations=card_data.get("art_variations", []),
                )

                if "metadata" not in fab_cards_collection:
                    fab_cards_collection["metadata"] = CollectionMetadata(
                        datetime=datetime.now().isoformat().replace(":", "-"),
                        hash=str(repo_commit),
                        dpi=card.dpi,
                        width_inch=card.width_inch,
                        height_inch=card.height_inch,
                        width_pixels=card.width_pixels,
                        height_pixels=card.height_pixels,
                    ).model_dump()

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
                        or len(card.art_variations) > 0  # alternate artwork (full art)
                    ):
                        __track_card_uuids(uuids_to_name, card)
                        continue

                # Any existing entry we've already stored for this (name, pitch).
                existing_card = (
                    fab_cards_collection["cards"].get(card.name, {}).get(card.pitch)
                )

                # Skip anything that would downgrade the existing entry.
                if existing_card is not None:
                    if card.foiling != "S":
                        __track_card_uuids(uuids_to_name, card)
                        continue
                    existing_url = existing_card.get("image_url")
                    if existing_url is not None and ".width" not in existing_url:
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

                # Store keyed by card name, sub-keyed by pitch.
                dumped = card.model_dump(
                    exclude=["name", "width_pixels", "height_pixels"]
                )
                fab_cards_collection["cards"].setdefault(card.name, {})[card.pitch] = (
                    dumped
                )

                __track_card_uuids(uuids_to_name, card)

            # Resolve backside/token UUID references to name / name_pitch strings.
            for cards in fab_cards_collection["cards"].values():
                for card in cards.values():
                    if card["backside"] is not None:
                        backsides = []
                        for backside_uuid in card["backside"]:
                            if backside_uuid not in uuids_to_name:
                                continue
                            backside_name_splits = uuids_to_name[backside_uuid].split(
                                "-"
                            )

                            has_pitch = False
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
                        card["backside"] = backsides if backsides else None

                    if card["tokens"] is not None:
                        token_names = (
                            uuids_to_name[token_uuid]
                            for token_uuid in card["tokens"]
                            if token_uuid in uuids_to_name
                        )
                        # Tokens are always colorless.
                        tokens = list(
                            {
                                token_name
                                for token_name in token_names
                                if fab_cards_collection["cards"]
                                .get(token_name, {})
                                .get(PITCHES[""], {})
                                .get("is_token")
                            }
                        )
                        card["tokens"] = tokens if tokens else None

            # Save collection snapshot on disk. Write a temp file first, then
            # atomically rename to the final path so an interruption never
            # leaves the collection folder empty.
            if not os.path.exists(path_to_data_output):
                os.makedirs(path_to_data_output, exist_ok=True)

            tmp_collection_path = expected_collection_path + ".tmp"
            with open(
                tmp_collection_path,
                mode="w",
                encoding="utf-8",
            ) as cards_collection_file:
                json.dump(fab_cards_collection, cards_collection_file, indent=4)
            os.replace(tmp_collection_path, expected_collection_path)

            # Now that the fresh snapshot is on disk, prune older ones (both
            # pre-v2 and previous-commit v2 files).
            for stale_path in glob(
                os.path.join(path_to_data_output, "fab-cards-collection-*.json")
            ):
                if stale_path != expected_collection_path:
                    os.remove(stale_path)

            print("[CARD-PROXY-PRINTER] Saved and using new card collection.")
    else:
        print("[CARD-PROXY-PRINTER] Card collection is up to date.")


def is_fab_collection_outdated(
    collection_input_path: str,
    collection_output_path: str,
) -> tuple[bool, str]:
    """
    Fetch the FAB source repo (no pull) and check whether the on-disk
    collection snapshot lags behind the remote HEAD. Returns
    ``(is_outdated, remote_commit_sha)``. Returns ``(False, ...)`` when no
    on-disk snapshot exists yet (initial generation happens on first render).
    """

    repo_path = next(iglob(os.path.join(collection_input_path, "*")))
    repo = Repo(repo_path)
    assert not repo.bare

    active_branch = repo.active_branch
    repo.remotes.origin.fetch(verbose=False)
    remote_sha = str(repo.commit(f"origin/{active_branch.name}"))

    # No on-disk snapshot at all → needs to be built.
    if not glob(
        os.path.join(collection_output_path, "fab-cards-collection-commit-*.json")
    ):
        return True, remote_sha

    expected = os.path.join(
        collection_output_path,
        f"fab-cards-collection-commit-{remote_sha}.json",
    )
    return not os.path.exists(expected), remote_sha


def refresh_fab_collection(
    collection_input_path: str,
    collection_output_path: str,
) -> None:
    """
    Pull the FAB source repo and regenerate the collection non-interactively.
    """

    repo_path = next(iglob(os.path.join(collection_input_path, "*")))
    repo = Repo(repo_path)
    assert not repo.bare
    repo.remotes.origin.pull(verbose=False)
    create_fab_cards_collection(
        collection_input_path,
        collection_output_path,
        interactive=False,
    )
