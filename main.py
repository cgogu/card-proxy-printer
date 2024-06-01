import cv2
import requests
import numpy as np
from core import Canvas, FABProxifier, replace_alpha_with_solid


def main():
    canvas = Canvas(dpi=300)
    canvas.new_page(1, 12)

    proxifier = FABProxifier()
    card = proxifier.generate_card("herald-of-tenacity-red", 0)

    # MTG
    # set_alias = "woe"
    # collector_number = 3
    # card_response = requests.get(f"https://api.scryfall.com/cards/{set_alias}/{collector_number}")
    # if card_response is not None:
    #     card_data = card_response.json()
    # card_name = card_data["name"].lower().replace(" ", "-")
    # image_response = requests.get(card_data["image_uris"]["png"])

    # 1
    canvas.page[
        canvas.y_step : canvas.y_step + card["height"],
        canvas.x_step : canvas.x_step + card["width"],
        :,
    ] = card["image"]

    # 2
    canvas.page[
        canvas.y_step : canvas.y_step + card["height"],
        canvas.x_step + card["width"] : canvas.x_step + card["width"] * 2,
        :,
    ] = card["image"]

    # 3
    canvas.page[
        canvas.y_step : canvas.y_step + card["height"],
        canvas.x_step + card["width"] * 2 : canvas.x_step + card["width"] * 3,
        :,
    ] = card["image"]

    # 5
    canvas.page[
        canvas.y_step + card["height"] : canvas.y_step + card["height"] * 2,
        canvas.x_step + card["width"] : canvas.x_step + card["width"] * 2,
        :,
    ] = card["image"]

    canvas.save_page("/home/cgogu/projects/card-proxy-printer/data/output")

if __name__ == "__main__":
    main()
