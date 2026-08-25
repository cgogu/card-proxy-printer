import os
import re

from unidecode import unidecode

from .constants import CUSTOM_PUNCTUATION, PITCHES
from .errors import CardProxyError
from .models import DecklistEntry


def encode_name(name: str, separator: str = "-") -> str:
    """
    Encode name by eliminating all punctuation and replacing white spaces with separator.
    ex: Test's name.. -> tests name -> tests-name
    """

    return (
        "".join(ch for ch in unidecode(name) if ch not in CUSTOM_PUNCTUATION)
        .lower()
        .replace(" ", separator)
    )


_FAB_LINE_COUNT_RE = re.compile(r"^\s*(\d+)x?\s+(.+?)\s*$", re.IGNORECASE)
_FAB_PAREN_RE = re.compile(r"\s*\(([^)]+)\)")
# Fabrary/skeleton section headers: 'Deck (58):', 'Deck cards', 'Weapons:',
# 'Arena cards', 'Inventory (17)' ...
_FAB_SECTION_RE = re.compile(
    r"^(hero(?:es)?|weapons?|equipments?|deck|inventory|extras?|maybe|arena|tokens?)"
    r"(?:\s+cards?)?"
    r"(?:\s*\(\d+\))?\s*:?\s*$",
    re.IGNORECASE,
)
# 'Hero: Briar' → treat like '1x Briar'.
_FAB_HERO_RE = re.compile(r"^hero\s*:\s*(.+?)\s*$", re.IGNORECASE)
# Set identifier: uppercase alphanumeric with optional dashes, e.g. 'SEA082',
# 'SEA125-TP', 'U-ARC044', 'ARC000-CF'. Must contain at least one digit.
_FAB_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_FAB_PITCHES = frozenset(p for p in PITCHES.values() if p != PITCHES[""])


def _looks_like_fab_identifier(token: str) -> bool:
    return bool(_FAB_IDENTIFIER_RE.match(token)) and any(ch.isdigit() for ch in token)


def _parse_fab_line(line: str) -> DecklistEntry | None:
    """
    Parse one fabrary-style decklist line into a ``DecklistEntry``.

    ``first_part`` is either an upper-cased set identifier (e.g. ``SEA082``)
    when one is present in parentheses, or an ``encode_name``-encoded card
    name. Returns ``None`` for blank lines, comments (``#``, ``//``), and
    section headers (``Deck (58):``, ``Equipment``, ``Hero:``, ...).
    """

    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "//")):
        return None
    if _FAB_SECTION_RE.match(stripped):
        return None

    m = _FAB_LINE_COUNT_RE.match(stripped)
    if m:
        count = int(m.group(1))
        rest = m.group(2)
    else:
        hero_m = _FAB_HERO_RE.match(stripped)
        if not hero_m:
            return None
        count = 1
        rest = hero_m.group(1).strip()

    identifier: str | None = None
    pitch: str | None = None
    for paren_m in _FAB_PAREN_RE.finditer(rest):
        token = paren_m.group(1).strip()
        low = token.lower()
        if low in _FAB_PITCHES:
            pitch = low
        elif _looks_like_fab_identifier(token):
            identifier = token.upper()

    name = _FAB_PAREN_RE.sub("", rest).strip()
    resolved_pitch = pitch or PITCHES[""]
    return DecklistEntry(
        count=count,
        first_part=identifier if identifier else encode_name(name),
        second_part=resolved_pitch,
    )


def filter_fab_deck_lines(text: str) -> str:
    """
    Strip everything but card lines from a pasted fabrary/txt decklist.

    Section headers (``Arena cards``, ``Deck (58):``, ...), metadata
    (``Name:``, ``Format:``, ``Made with love ...``), footer URLs, blank
    lines and comments are dropped. ``Hero: <name>`` is rewritten as
    ``1 <name>`` so the surviving text is uniformly count-prefixed.
    """

    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if _FAB_SECTION_RE.match(stripped):
            continue
        if _FAB_LINE_COUNT_RE.match(stripped):
            kept.append(stripped)
            continue
        hero_m = _FAB_HERO_RE.match(stripped)
        if hero_m:
            kept.append(f"1x {hero_m.group(1).strip()}")
    return "\n".join(kept)


def split_name_and_pitch(
    name_and_pitch: str, decklist_pitch_format: list, separator: str = "-"
) -> tuple:
    """
    Split name and pitch. Add pitch when non existent and encode the name.
    """

    encoded = encode_name(name_and_pitch)
    encoded_splits = encoded.split(separator)

    if encoded_splits[-1] in decklist_pitch_format:
        return f"{separator}".join(encoded_splits[:-1]), encoded_splits[-1][1:-1]
    return encoded, PITCHES[""]


def parse_decklist(path_to_decklist: str, card_games_alias: str) -> list[DecklistEntry]:
    """
    Parse a text decklist file into a list of ``DecklistEntry``.
    """

    from .utils import get_ext_file  # local import to keep utils.py minimal

    if not os.path.exists(path_to_decklist):
        raise CardProxyError(f"{path_to_decklist} does not exist.")

    if (decklist_file_path := get_ext_file(path_to_decklist, ext="txt")) is None:
        raise CardProxyError(f"No text decklist can be found at {path_to_decklist}.")

    decklist: list[DecklistEntry] = []
    with open(decklist_file_path, encoding="utf-8") as decklist_file:
        while line := decklist_file.readline():
            match card_games_alias:
                case "fab":
                    entry = _parse_fab_line(line)
                    if entry is not None:
                        decklist.append(entry)
                case "mtg":
                    card_count, card_set_alias, card_set_collector_number = re.match(
                        r"(\d+)\s.*\(([a-zA-Z0-9]+)\)\s([a-zA-Z0-9-]+)",
                        line.rstrip(),
                        flags=re.VERBOSE,
                    ).groups()

                    if card_set_alias == "PLST":
                        card_set_alias, card_set_collector_number = (
                            card_set_collector_number.split("-")
                        )

                    decklist.append(
                        DecklistEntry(
                            count=int(card_count),
                            first_part=card_set_alias.lower(),
                            second_part=card_set_collector_number,
                        )
                    )
                case _:
                    raise CardProxyError(
                        f"Card games alias '{card_games_alias}' not supported."
                    )

    return decklist
