# MTG and FAB proxy cards dowload, right cornerns, color, and 2.5 x 3.5 inch standard size

import cv2
import requests
import numpy as np
from core import Canvas


def remove_transparency(image, card_game):
    bg_colour = [24, 20, 15] if card_game == "mtg" else [0, 0, 0]
    # Check if the image has an alpha channel
    if image.shape[2] == 4:
        # Split the image into B, G, R, A channels
        B, G, R, A = cv2.split(image)

        # Compute the alpha value between 0 and 1
        alpha = A / 255.0

        # Replace the alpha channel with the specified color, for example, white
        R = (bg_colour[0] * (1 - alpha) + R * alpha).astype(np.uint8)
        G = (bg_colour[1] * (1 - alpha) + G * alpha).astype(np.uint8)
        B = (bg_colour[2] * (1 - alpha) + B * alpha).astype(np.uint8)

        # Merge the channels back
        image = cv2.merge((B, G, R))

    return image


def main():
    canvas = Canvas(dpi=300)
    canvas.new_page(1, 12)

    # FAB
    card_name = "herald-of-tenacity-red"
    card_response = requests.get(f"https://api.fabdb.net/cards/{card_name}")
    if card_response is not None:
        card_data = card_response.json()
    card_image_url = card_data["image"].split("?")[0]
    image_response = requests.get(card_image_url)

    # MTG
    # set_alias = "woe"
    # collector_number = 3
    # card_response = requests.get(f"https://api.scryfall.com/cards/{set_alias}/{collector_number}")
    # if card_response is not None:
    #     card_data = card_response.json()
    # card_name = card_data["name"].lower().replace(" ", "-")
    # image_response = requests.get(card_data["image_uris"]["png"])

    image = cv2.imdecode(np.frombuffer(image_response.content, np.uint8), -1)
    image = remove_transparency(image, "fab")

    # standard width in inches = 2.5
    # standard height in inches = 3.5
    # dpi = 300
    # size for above setup is 750 x 1050 (2.5 x 3.5 at 300 dpi)
    dpi = 300
    image = cv2.resize(
        image, (int(2.5 * dpi), int(3.5 * dpi)), interpolation=cv2.INTER_CUBIC
    )

    cv2.imwrite(f"./data/output/{card_name}.png", image)

    if dpi == 300:
        a4_page_size = (3508, 2480)
    a4_page = np.full([*a4_page_size, 3], fill_value=255, dtype=np.uint8)

    x_start_ref = (a4_page.shape[1] - image.shape[1] * 3) // 2
    y_start_ref = (a4_page.shape[0] - image.shape[0] * 3) // 2

    # HWC
    # 115 left right
    # 179 up down

    # 1
    a4_page[
        y_start_ref : y_start_ref + image.shape[0],
        x_start_ref : x_start_ref + image.shape[1],
        :,
    ] = image

    # 2
    a4_page[
        y_start_ref : y_start_ref + image.shape[0],
        x_start_ref + image.shape[1] : x_start_ref + image.shape[1] * 2,
        :,
    ] = image

    # 3
    a4_page[
        y_start_ref : y_start_ref + image.shape[0],
        x_start_ref + image.shape[1] * 2 : x_start_ref + image.shape[1] * 3,
        :,
    ] = image

    # 5
    a4_page[
        y_start_ref + image.shape[0] : y_start_ref + image.shape[0] * 2,
        x_start_ref + image.shape[1] : x_start_ref + image.shape[1] * 2,
        :,
    ] = image

    cv2.imwrite(f"./data/output/a4_{card_name}.png", a4_page)


if __name__ == "__main__":
    main()
