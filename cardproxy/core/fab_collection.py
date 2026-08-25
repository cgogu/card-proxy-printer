import json
import os
import re
from datetime import datetime
from glob import glob, iglob

from git import Repo
from simdjson import Parser
from tqdm import tqdm

from .constants import PITCHES
from .decklist import encode_name
from .errors import CardProxyError
from .fab_db import DB_FILENAME, FabCollectionDB
from .git_sync import sync_with_remote
from .models import CardModel, CollectionMetadata

_LEGACY_JSON_GLOB = "fab-cards-collection-commit-*.json"
_LEGACY_HASH_RE = re.compile(r"fab-cards-collection-commit-([0-9a-fA-F]+)\.json$")


def create_fab_cards_collection(
    path_to_data_root: str,
    path_to_data_output: str,
    interactive: bool = True,
) -> None:
    """
    Ensure the SQLite FAB card collection at
    ``<path_to_data_output>/fab-cards-collection.sqlite3`` is populated and
    aligned with the-fab-cube source repo:
    https://github.com/the-fab-cube/flesh-and-blood-cards.

    Only brand-new ``(name, pitch)`` rows are inserted. Existing rows are
    preserved untouched, so hand-curated entries and cards already imported
    at an older commit are never clobbered by a refresh. On first launch
    after the JSON→SQLite migration the legacy
    ``fab-cards-collection-commit-*.json`` snapshot is seeded into the DB
    once and then deleted.
    """

    if not os.path.exists(path_to_data_root):
        raise CardProxyError(f"{path_to_data_root} does not exist.")

    repo_path = next(iglob(os.path.join(path_to_data_root, "*")))
    repo_commit, _ = sync_with_remote(repo_path=repo_path, interactive=interactive)
    repo_commit = str(repo_commit)

    os.makedirs(path_to_data_output, exist_ok=True)
    db_path = os.path.join(path_to_data_output, DB_FILENAME)

    with FabCollectionDB(db_path) as db:
        _migrate_legacy_json_snapshot(db, path_to_data_output)

        if not db.is_empty() and db.get_commit_hash() == repo_commit:
            print("[CARD-PROXY-PRINTER] Card collection is up to date.")
            return

        pending, metadata = _scan_fab_cube_repo(repo_path, repo_commit)
        inserted = db.insert_cards_if_absent(pending.values())
        if metadata is not None:
            db.upsert_metadata(metadata)

        if inserted:
            print(
                f"[CARD-PROXY-PRINTER] Card collection updated: "
                f"{inserted} new entries inserted."
            )
        else:
            print(
                "[CARD-PROXY-PRINTER] Card collection: no new entries "
                "(commit hash updated)."
            )


def is_fab_collection_outdated(
    collection_input_path: str,
    collection_output_path: str,
) -> tuple[bool, str]:
    """
    Fetch the FAB source repo (no pull) and check whether the local
    collection lags behind the remote HEAD. Returns
    ``(is_outdated, remote_commit_sha)``.
    """

    repo_path = next(iglob(os.path.join(collection_input_path, "*")))
    repo = Repo(repo_path)
    assert not repo.bare

    active_branch = repo.active_branch
    repo.remotes.origin.fetch(verbose=False)
    remote_sha = str(repo.commit(f"origin/{active_branch.name}"))

    db_path = os.path.join(collection_output_path, DB_FILENAME)
    if os.path.exists(db_path):
        with FabCollectionDB(db_path) as db:
            has_data = not db.is_empty()
            current_hash = db.get_commit_hash()
        if has_data and current_hash == remote_sha:
            return False, remote_sha
        return True, remote_sha

    # No DB yet: fall back to the legacy JSON hash so users don't see a
    # spurious "outdated" prompt right after upgrading — the migration will
    # run on the next render regardless.
    legacy_hash = _peek_legacy_json_hash(collection_output_path)
    if legacy_hash is not None:
        return legacy_hash != remote_sha, remote_sha

    return True, remote_sha


def refresh_fab_collection(
    collection_input_path: str,
    collection_output_path: str,
) -> None:
    """
    Pull the FAB source repo and (re-)build the collection non-interactively.
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


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------


def _peek_legacy_json_hash(collection_output_path: str) -> str | None:
    for path in glob(os.path.join(collection_output_path, _LEGACY_JSON_GLOB)):
        match = _LEGACY_HASH_RE.search(os.path.basename(path))
        if match is not None:
            return match.group(1).lower()
    return None


def _migrate_legacy_json_snapshot(
    db: FabCollectionDB, collection_output_path: str
) -> None:
    """
    One-shot migration: seed the DB from the most recent legacy JSON snapshot
    (if any) then delete every legacy JSON file. Seeding is skipped once the
    DB already holds rows so a re-migration can never overwrite curated data.
    """

    legacy_files = sorted(glob(os.path.join(collection_output_path, _LEGACY_JSON_GLOB)))
    if not legacy_files:
        return

    if db.is_empty():
        newest = legacy_files[-1]
        try:
            with open(newest, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise CardProxyError(
                f"Failed to migrate legacy collection snapshot {newest}: {exc}"
            ) from exc

        metadata_dict = payload.get("metadata")
        if metadata_dict is not None:
            try:
                db.upsert_metadata(CollectionMetadata.model_validate(metadata_dict))
            except Exception:
                # Metadata migration failures shouldn't block card data.
                pass

        pending: list[dict] = []
        for name, pitches in (payload.get("cards") or {}).items():
            for pitch, entry in (pitches or {}).items():
                entry = entry or {}
                pending.append(
                    {
                        "name": name,
                        "pitch": pitch,
                        "uuid": entry.get("uuid"),
                        "printing_uuid": entry.get("printing_uuid"),
                        "identifier": entry.get("identifier"),
                        "image_url": entry.get("image_url"),
                        "is_hero": entry.get("is_hero", False),
                        "is_token": entry.get("is_token", False),
                        "tokens": entry.get("tokens"),
                        "backside": entry.get("backside"),
                    }
                )
        inserted = db.insert_cards_if_absent(pending)
        print(
            f"[CARD-PROXY-PRINTER] Migrated {inserted} entries "
            "from legacy JSON snapshot."
        )

    for path in legacy_files:
        try:
            os.remove(path)
        except OSError:
            pass


def _scan_fab_cube_repo(
    repo_path: str,
    repo_commit: str,
) -> tuple[dict[tuple[str, str], dict], CollectionMetadata | None]:
    """
    Parse ``card-flattened.json`` from the fab-cube repo checkout, apply the
    "best variant per (name, pitch)" filter, and resolve backside / token
    UUID references to name-or-``name_pitch`` strings. Returns the pending
    insert dict plus a metadata block derived from the first accepted card.
    """

    root_path = next(iglob(os.path.join(repo_path, "json", "english"), recursive=True))
    card_flattened_input_json_path = os.path.join(root_path, "card-flattened.json")
    if not os.path.exists(card_flattened_input_json_path):
        raise CardProxyError(f"card-flattened.json cannot be found at {root_path}")

    pending: dict[tuple[str, str], dict] = {}
    uuids_to_name: dict[str, str] = {}
    metadata: CollectionMetadata | None = None

    def track(card: CardModel) -> None:
        label = f"{card.name}-{card.pitch}" if card.pitch != PITCHES[""] else card.name
        uuids_to_name[card.uuid] = label
        uuids_to_name[card.printing_uuid] = label

    cards_parser = Parser().load(card_flattened_input_json_path)
    with tqdm(
        cards_parser,
        total=len(cards_parser),
        ascii=True,
        desc="[CARD-PROXY-PRINTER] Scanning fab-cube card catalog",
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

            if metadata is None:
                metadata = CollectionMetadata(
                    datetime=datetime.now().isoformat().replace(":", "-"),
                    hash=repo_commit,
                    dpi=card.dpi,
                    width_inch=card.width_inch,
                    height_inch=card.height_inch,
                    width_pixels=card.width_pixels,
                    height_pixels=card.height_pixels,
                )

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
                    track(card)
                    continue

            # Best-variant filter within this scan (existing DB rows are
            # skipped later by INSERT OR IGNORE).
            existing = pending.get((card.name, card.pitch))
            if existing is not None:
                if card.foiling != "S":
                    track(card)
                    continue
                existing_url = existing.get("image_url")
                if existing_url is not None and ".width" not in existing_url:
                    track(card)
                    continue

            backside_cards: list = []
            if (
                inpt_double_sided_cards := card_data.get("double_sided_card_info", None)
            ) is not None:
                for ds_card in inpt_double_sided_cards:
                    if ds_card["is_front"] and ds_card["is_DFC"]:
                        backside_cards.append(ds_card["other_face_unique_id"])
            if backside_cards:
                card.backside = backside_cards

            token_cards: list = []
            if (
                input_token_cards := card_data.get("referenced_cards", None)
            ) is not None:
                for reference_card in input_token_cards:
                    token_cards.append(reference_card)
            if token_cards:
                card.tokens = token_cards

            dumped = card.model_dump(exclude=["width_pixels", "height_pixels"])
            # ``pitch`` is excluded on the model but the DB row needs it.
            dumped["pitch"] = card.pitch
            pending[(card.name, card.pitch)] = dumped
            track(card)

    _resolve_references(pending, uuids_to_name)
    return pending, metadata


def _resolve_references(
    pending: dict[tuple[str, str], dict],
    uuids_to_name: dict[str, str],
) -> None:
    """
    Rewrite backside/token UUID references into ``name`` / ``name_pitch``
    strings using the UUID map built during scanning.
    """

    colorless = PITCHES[""]
    non_colorless_pitches = frozenset(p for p in PITCHES.values() if p != colorless)

    for card in pending.values():
        if card.get("backside"):
            backsides: list[str] = []
            for backside_uuid in card["backside"]:
                mapped = uuids_to_name.get(backside_uuid)
                if mapped is None:
                    continue
                parts = mapped.split("-")
                has_pitch = parts[-1] in non_colorless_pitches
                backsides.append(
                    "-".join(parts[:-1]) + "_" + parts[-1]
                    if has_pitch
                    else "-".join(parts)
                )
            card["backside"] = backsides or None

        if card.get("tokens"):
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
                    if _is_token(pending, token_name, colorless)
                }
            )
            card["tokens"] = tokens or None


def _is_token(pending: dict[tuple[str, str], dict], name: str, colorless: str) -> bool:
    entry = pending.get((name, colorless))
    return bool(entry and entry.get("is_token"))
