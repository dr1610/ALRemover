"""Image operations independent of WebUI and model loading."""
import numpy as np
from PIL import Image, ImageFilter

KINDS = ["元画像", "キャラクター", "背景", "マスク"]
SLUGS = dict(zip(KINDS, ["original", "character", "background", "mask"]))


def normalize(image):
    result = image.convert("RGBA")
    result.info = image.info.copy()
    return result


def multiply_alpha(left, right):
    a = np.asarray(left.convert("L"), dtype=np.uint32)
    b = np.asarray(right.convert("L"), dtype=np.uint32)
    if a.shape != b.shape:
        raise ValueError("マスクと画像の大きさが異なります。")
    return Image.fromarray(((a * b + 127) // 255).astype(np.uint8))


def layers(source, mask):
    source = normalize(source)
    if source.size != mask.size:
        raise ValueError("マスクと画像の大きさが異なります。")
    # Partition the existing alpha budget, including semi-transparent input.
    fg_alpha = multiply_alpha(source.getchannel("A"), mask)
    bg_alpha = Image.fromarray(
        (np.asarray(source.getchannel("A"), dtype=np.int16)
         - np.asarray(fg_alpha, dtype=np.int16)).astype(np.uint8))
    fg, bg = source.copy(), source.copy()
    fg.putalpha(fg_alpha)
    bg.putalpha(bg_alpha)
    return {"元画像": source, "キャラクター": fg, "背景": bg, "マスク": fg_alpha}


def adjust_mask(mask, expand=0):
    amount = int(expand)
    if not -8 <= amount <= 8:
        raise ValueError("輪郭の調整は -8～8 px です。")
    if amount > 0:
        return mask.filter(ImageFilter.MaxFilter(2 * amount + 1))
    if amount < 0:
        return mask.filter(ImageFilter.MinFilter(2 * -amount + 1))
    return mask.copy()


def paint_mask(base_mask, editor):
    """Replay all strokes from the immutable base, so eraser/undo works."""
    result = np.asarray(base_mask.convert("L"), dtype=np.float32).copy()
    if not editor:
        return base_mask.copy()
    for layer in editor.get("layers") or []:
        if not isinstance(layer, Image.Image) or layer.size != base_mask.size:
            raise ValueError("修正レイヤーの大きさが変わっています。再度切り抜いてください。")
        rgba = np.asarray(layer.convert("RGBA"), dtype=np.float32)
        red, green, blue, alpha = (rgba[..., i] for i in range(4))
        keep = (green > red + 20) & (green > blue + 20)
        erase = (red > green + 20) & (red > blue + 20)
        strength = alpha / 255
        result = np.where(keep, result * (1 - strength) + 255 * strength, result)
        result = np.where(erase, result * (1 - strength), result)
    return Image.fromarray(np.clip(np.rint(result), 0, 255).astype(np.uint8))
