import cv2
import numpy as np


def replace_alpha_with_solid(
    image: np.ndarray,
    solid_color: list = [0, 0, 0],
    is_rgb: bool = False,
) -> np.ndarray:
    # Check if the image has an alpha channel
    if image.shape[2] == 4:
        # Split the image into channels
        if is_rgb:
            red_ch, green_ch, blue_ch, alpha_ch = cv2.split(image)
        else:
            blue_ch, green_ch, red_ch, alpha_ch = cv2.split(image)

        # Compute the alpha value between 0-1
        alpha = alpha_ch / 255.0

        # Replace the alpha channel with the specified color
        chs = [
            (solid_color[0 if is_rgb else 2] * (1.0 - alpha) + red_ch * alpha).astype(
                np.uint8
            ),
            (solid_color[1] * (1.0 - alpha) + green_ch * alpha).astype(np.uint8),
            (solid_color[2 if is_rgb else 0] * (1.0 - alpha) + blue_ch * alpha).astype(
                np.uint8
            ),
        ]

        # Merge the channels back
        image = cv2.merge(chs if is_rgb else chs[::-1]).astype(np.uint8)

    return image
