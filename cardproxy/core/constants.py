import os
from string import punctuation

from .models import MM_PER_INCH

# Re-export so callers can grab everything from a single constants module.
__all__ = ("MM_PER_INCH", "PITCHES", "CUSTOM_PUNCTUATION", "CARDPROXY_ROOT")

# Package root (…/cardproxy). Used to resolve relative paths from configs.
CARDPROXY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PITCHES = {
    "": "colorless",  # empty pitch (heroes, arms, equipment, etc.)
    "1": "red",
    "2": "yellow",
    "3": "blue",
}

# Need to keep "()" (used as pitch/set delimiters) and to add "…" to punctuation
CUSTOM_PUNCTUATION = punctuation.replace("()", "") + "\u2026"
