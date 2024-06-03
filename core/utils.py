import argparse

import torch
import cv2
import numpy as np
from torchvision.transforms.functional import to_pil_image, to_tensor
from helper_repos.denoise.scunet.utils.utils_image import uint2tensor4, tensor2uint


def get_cfg() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument(
        "--card-game-alias",
        type=str,
        required=True,
        help="The card game alias (MTG or FAB)",
    )
    parser.add_argument(
        "--path-to-decklist",
        type=str,
        required=True,
        help="Path to decklist to be proxied",
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
    return parser.parse_args()


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


def apply_superes_and_denoiser_pipeline(
    card_image: np.ndarray,
    sr_model: torch.nn.Module,
    denoise_model: torch.nn.Module,
    width: int,
    height: int,
    device: torch.device,
) -> np.ndarray:
    # SR
    low_res_tensor = to_tensor(card_image).unsqueeze(0).to(device)
    high_res_tensor = sr_model(low_res_tensor)
    high_res_image = np.asarray(
        to_pil_image(high_res_tensor.squeeze(0).clamp(0, 1)), dtype=np.uint8
    )

    # Resize to standard 2.5 x 3.5
    high_res_image = cv2.resize(
        high_res_image, (width, height), interpolation=cv2.INTER_AREA
    )

    # Denoise
    noisy_tensor = uint2tensor4(high_res_image).to(device)
    clean_tensor = denoise_model(noisy_tensor)
    return tensor2uint(clean_tensor)


# import re

# entry = "1 Sea Gate Restoration // Sea Gate, Reborn (ZNR) 333 *F*"
# pattern = r"(\d+)\s.*\((\w+)\)\s(\d+)"
# match = re.search(pattern, entry)

# if match:
#     output = " ".join(match.groups())
#     print(output)  # prints: 1 ZNR 333
# else:
#     print("No match found.")

# In the regular expression (\d+)\s.*\((\w+)\)\s(\d+):

# (\d+) matches one or more digits, which is the quantity of the card.
# .* matches any character (except newline), which is used to skip the card name. If capture is used (.*), the name will be part of the groups.
# \((\w+)\) matches any word character (equal to [a-zA-Z0-9_]) between parentheses, which is the set code.
# (\d+) matches one or more digits, which is the card number.
