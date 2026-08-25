"""
Generic filesystem/string helpers plus a back-compat surface for the
pre-split ``cardproxy.core.utils`` module. Prefer importing the focused
modules (``config``, ``decklist``, ``image_ops``, ``fab_collection``,
``git_sync``, ``constants``, ``errors``) directly in new code.
"""

import os
from glob import glob

from .config import (  # noqa: F401
    get_cfg,
    normalize_config_paths,
    parse_config,
)

# --- Back-compat re-exports ------------------------------------------------
# Kept so external callers can still write ``from cardproxy.core.utils
# import <anything>`` after the split.
from .constants import (  # noqa: F401
    CARDPROXY_ROOT,
    CUSTOM_PUNCTUATION,
    PITCHES,
)
from .decklist import (  # noqa: F401
    encode_name,
    filter_fab_deck_lines,
    parse_decklist,
    split_name_and_pitch,
)
from .errors import CardProxyError  # noqa: F401
from .fab_collection import (  # noqa: F401
    create_fab_cards_collection,
    is_fab_collection_outdated,
    refresh_fab_collection,
)
from .git_sync import sync_with_remote  # noqa: F401
from .image_ops import (  # noqa: F401
    convert_16bit_to_8bit,
    replace_alpha_with_solid,
    superes_and_denoiser_pipeline,
)


def get_ext_file(input_path: str, ext: str = "json") -> str | None:
    """
    Return the first file with the given extension inside ``input_path``, or
    ``None`` when the directory doesn't exist or no such file is present.
    """

    if not os.path.exists(input_path):
        return None

    matches = glob(os.path.join(input_path, f"*.{ext}"))
    if not matches:
        return None

    return matches[0]
