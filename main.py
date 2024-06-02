from itertools import batched

from core import Canvas, FABProxifier


def main():
    canvas = Canvas(dpi=300)
    canvas.new_page(1, 12)

    proxifier = FABProxifier()
    card = proxifier.generate_card("herald-of-tenacity-red", 0)

    lc = [card for _ in range(30)]

    for cards in batched(
        lc, canvas.num_cards_per_page_width * canvas.num_cards_per_page_height
    ):
        canvas.fill_page(cards)
        canvas.save_page("/home/cgogu/projects/card-proxy-printer/data/output")

if __name__ == "__main__":
    main()
