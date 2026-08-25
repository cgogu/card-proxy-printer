import argparse
import os

from yaml import safe_load

from .constants import CARDPROXY_ROOT
from .errors import CardProxyError
from .models import AppConfig

_CONFIG_PATH_KEYS = (
    "path_to_database",
    "path_to_collection_input",
    "path_to_sr_weights",
    "path_to_denoise_weights",
)


def normalize_config_paths(cfg: dict) -> dict:
    """
    Resolve any relative ``path_to_*`` entries against the cardproxy package
    root, so YAML configs can ship with relative paths.
    """

    for key in _CONFIG_PATH_KEYS:
        value = cfg.get(key)
        if value and not os.path.isabs(value):
            cfg[key] = os.path.join(CARDPROXY_ROOT, value)
    return cfg


def get_cfg() -> argparse.Namespace:
    """
    CLI argument parser for the card-proxy runner.
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


def parse_config(config: argparse.Namespace) -> AppConfig:
    """
    Reads either a YAML file (via ``--config``) or the direct CLI flags and
    returns a validated ``AppConfig``.
    """

    if getattr(config, "config", None):
        with open(config.config, encoding="utf-8") as config_file:
            config_data = safe_load(config_file) or {}

        normalize_config_paths(config_data)

        if (
            config_data.get("path_to_database") is None
            or config_data.get("card_game_alias") is None
        ):
            raise CardProxyError(
                "Need to provide the database path and card game alias"
            )

        if config_data.get("path_to_collection_input"):
            config_data["path_to_collection_input"] = os.path.join(
                config_data["path_to_collection_input"],
                config_data["card_game_alias"],
            )

        for path, dirname in [
            ["path_to_decklist", "input"],
            ["path_to_output", "output"],
            ["path_to_collection_output", "collection"],
        ]:
            config_data[path] = os.path.join(
                config_data["path_to_database"],
                config_data["card_game_alias"],
                dirname,
            )

        return AppConfig.model_validate(config_data)

    # CLI-only mode: promote the argparse namespace into an AppConfig.
    cli_data = {k: v for k, v in vars(config).items() if v is not None}
    if any(
        cli_data.get(k) is None
        for k in ("path_to_decklist", "path_to_output", "path_to_collection_output")
    ):
        raise CardProxyError(
            "Need to provide the run configuration file or full cli arguments."
        )
    return AppConfig.model_validate(cli_data)
