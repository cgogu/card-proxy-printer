import cv2
import numpy as np
import torch
from torchvision.transforms.functional import to_pil_image, to_tensor

from cardproxy.helper_repos.denoise.scunet.utils.utils_image import (
    tensor2uint,
    uint2tensor4,
)


def replace_alpha_with_solid(
    image: np.ndarray,
    solid_color: list | None = None,
    is_rgb: bool = False,
) -> np.ndarray:
    """
    Replace the alpha channel from an image with a solid color.
    """

    if solid_color is None:
        solid_color = [0, 0, 0]

    if image.shape[2] == 4:
        if is_rgb:
            red_ch, green_ch, blue_ch, alpha_ch = cv2.split(image)
        else:
            blue_ch, green_ch, red_ch, alpha_ch = cv2.split(image)

        alpha = alpha_ch / 255.0
        chs = [
            (solid_color[0 if is_rgb else 2] * (1.0 - alpha) + red_ch * alpha).astype(
                np.uint8
            ),
            (solid_color[1] * (1.0 - alpha) + green_ch * alpha).astype(np.uint8),
            (solid_color[2 if is_rgb else 0] * (1.0 - alpha) + blue_ch * alpha).astype(
                np.uint8
            ),
        ]
        image = cv2.merge(chs if is_rgb else chs[::-1]).astype(np.uint8)

    return image


def convert_16bit_to_8bit(image: np.ndarray) -> np.ndarray:
    """
    Convert image from 16-bit to 8-bit.
    """

    if image.dtype == np.uint8:
        return image
    return (image / 256).astype(np.uint8)


def superes_and_denoiser_pipeline(
    card_image: np.ndarray,
    sr_model: torch.nn.Module,
    denoise_model: torch.nn.Module,
    apply_denoiser: bool,  # CPU heavy
    width: int,
    height: int,
    device: torch.device,
    apply_sr: bool = True,
) -> np.ndarray:
    """
    Run super-resolution and denoising nn models over the input image.
    """

    if apply_denoiser:
        noisy_tensor = uint2tensor4(card_image).to(device)
        clean_tensor = denoise_model(noisy_tensor)
        card_image = tensor2uint(clean_tensor)

    if apply_sr:
        low_res_tensor = to_tensor(card_image).unsqueeze(0).to(device)
        high_res_tensor = sr_model(low_res_tensor)
        card_image = np.asarray(
            to_pil_image(high_res_tensor.squeeze(0).clamp(0, 1)), dtype=np.uint8
        )

    return cv2.resize(card_image, (width, height), interpolation=cv2.INTER_AREA)
