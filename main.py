from itertools import batched

from core import Canvas, MTGProxifier, FABProxifier, get_cfg

def main():
    config = get_cfg()

    canvas = Canvas(dpi=300)
    canvas.new_page(1, 12)

    match config.card_game_alias.upper():
        case "FAB":
            proxifier = FABProxifier(
                sr_weights_path=config.path_to_sr_weights,
                denoise_weights_path=config.path_to_denoise_weights,
            )
        case "MTG":
            proxifier = MTGProxifier(
                sr_weights_path=config.path_to_sr_weights,
                denoise_weights_path=config.path_to_denoise_weights,
            )
        case _:
            raise ValueError(
                f"{config.card_game_alias} not supported. Only MTG or FAB."
            )

    card = proxifier.generate_card("herald-of-tenacity-red", 0)

    lc = [card for _ in range(30)]

    for cards in batched(
        lc, canvas.num_cards_per_page_width * canvas.num_cards_per_page_height
    ):
        canvas.fill_page(cards)
        canvas.save_page("/home/cgogu/projects/card-proxy-printer/data/output")

if __name__ == "__main__":
    main()
