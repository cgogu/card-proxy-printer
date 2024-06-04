from itertools import batched

from core import Canvas, MTGProxifier, FABProxifier, get_cfg, CardProxyError

def main():
    config = get_cfg()

    canvas = Canvas(dpi=300)
    canvas.new_page(1, 12)

    match config.card_game_alias:
        case "fab":
            proxifier = FABProxifier(
                sr_weights_path=config.path_to_sr_weights,
                denoise_weights_path=config.path_to_denoise_weights,
                collection_input_path=config.collection_input_path,
                collection_output_path=config.collection_output_path,
            )
        case "mtg":
            proxifier = MTGProxifier(
                sr_weights_path=config.path_to_sr_weights,
                denoise_weights_path=config.path_to_denoise_weights,
            )
        case _:
            raise CardProxyError(
                f"{config.card_game_alias} not available. Only 'mtg' or 'fab' supported."
            )

    card = proxifier.generate_card("herald-of-tenacity-red")

    lc = [card for _ in range(30)]

    for cards in batched(
        lc, canvas.num_cards_per_page_width * canvas.num_cards_per_page_height
    ):
        canvas.fill_page(cards)
        canvas.save_page("/home/cgogu/projects/card-proxy-printer/data/output")

if __name__ == "__main__":
    main()
