"""ComfyUI adapters for extraction, local mask correction and RGBA output."""
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from .alr_neo import engine


def matching_mask(mask, shape, device):
    """Match a Comfy MASK to B,H,W; only broadcast a single-image batch."""
    mask = mask.to(device=device, dtype=torch.float32)
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    if mask.ndim != 3:
        raise ValueError("MASK must have shape [B,H,W] or [H,W].")
    if mask.shape[0] == 1 and shape[0] != 1:
        mask = mask.expand(shape[0], -1, -1)
    if mask.shape[0] != shape[0]:
        raise ValueError("The image and mask batch sizes differ.")
    if tuple(mask.shape[1:]) != tuple(shape[1:]):
        # Load Image emits a 64x64 zero mask when the source has no alpha.
        if tuple(mask.shape[1:]) == (64, 64) and not torch.count_nonzero(mask):
            mask = torch.zeros(shape, device=device, dtype=torch.float32)
        else:
            raise ValueError("Use a mask with the same width and height as the source image.")
    if not torch.isfinite(mask).all():
        raise ValueError("The mask contains non-finite values.")
    return mask.clamp(0, 1)


def source_alpha(images, input_transparency=None):
    if images.ndim != 4 or images.shape[-1] not in (3, 4):
        raise ValueError("IMAGE must have shape [B,H,W,3] or [B,H,W,4].")
    if input_transparency is not None:
        # Load Image and Split Image with Alpha output inverse alpha.
        return 1 - matching_mask(input_transparency, images.shape[:3], images.device)
    if images.shape[-1] == 4:
        return images[..., 3].float().clamp(0, 1)
    return torch.ones(images.shape[:3], device=images.device, dtype=torch.float32)


class ALRemoverCutout:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "mode": (engine.MODES, {"default": engine.DEFAULT_MODE}),
            "expand": ("INT", {"default": 0, "min": -8, "max": 8}),
        }, "optional": {
            "input_transparency": ("MASK", {"tooltip": "Connect Load Image's MASK to preserve existing transparency. White means transparent."}),
        }}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("foreground_mask",)
    FUNCTION = "cutout"
    CATEGORY = "ALRemover"
    DESCRIPTION = "Extract a foreground mask with BEN2 or ToonOut. White keeps the character. Downloads the chosen model on first execution."

    def cutout(self, images, mode=engine.DEFAULT_MODE, expand=0, input_transparency=None):
        import folder_paths
        import comfy.model_management as memory
        from comfy.utils import ProgressBar

        alpha = source_alpha(images, input_transparency).cpu().numpy()
        rgb = images[..., :3].detach().float().cpu().numpy()
        directory = Path(folder_paths.models_dir) / "ALRemover"
        device = memory.get_torch_device()
        progress = ProgressBar(len(images))

        def cancelled():
            memory.throw_exception_if_processing_interrupted()
            return False

        masks = []
        try:
            cancelled()
            if device.type != "cpu":
                memory.free_memory(4.5 * 2**30, device)
            for index in range(len(images)):
                rgba = np.concatenate((rgb[index], alpha[index, ..., None]), axis=-1)
                source = Image.fromarray(np.rint(np.clip(rgba, 0, 1) * 255).astype(np.uint8))
                mask = engine.extract(source, mode, expand, directory=directory,
                                      cancel=cancelled, device=device)
                masks.append(torch.from_numpy(np.array(mask, dtype=np.float32) / 255))
                progress.update(1)
        finally:
            # Comfy caches node outputs; no independent persistent model cache is needed.
            engine.release_models()
        return (torch.stack(masks),)


class ALRemoverCorrectMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"foreground_mask": ("MASK",),
                             "enabled": ("BOOLEAN", {"default": True})}, "optional": {
            "keep": ("MASK", {"tooltip": "White restores the foreground; black leaves the original mask unchanged."}),
            "erase": ("MASK", {"tooltip": "White removes the foreground. Erase takes priority where both correction masks overlap."}),
        }}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("foreground_mask",)
    FUNCTION = "correct"
    CATEGORY = "ALRemover"
    DESCRIPTION = "Apply local keep/erase masks without rerunning the cutout model. Use ComfyUI's Mask Editor on separate copies of the source image."

    def correct(self, foreground_mask, enabled=True, keep=None, erase=None):
        shape = foreground_mask.shape if foreground_mask.ndim == 3 else (1, *foreground_mask.shape)
        mask = matching_mask(foreground_mask, shape, foreground_mask.device)
        if not enabled:
            return (mask,)
        if keep is not None:
            keep = matching_mask(keep, shape, mask.device)
            mask = mask + (1 - mask) * keep
        if erase is not None:
            mask = mask * (1 - matching_mask(erase, shape, mask.device))
        return (mask,)


class ALRemoverLayers:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "foreground_mask": ("MASK",)}, "optional": {
            "input_transparency": ("MASK", {"tooltip": "Connect the original Load Image MASK here too, before drawing correction masks."}),
        }}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK")
    RETURN_NAMES = ("character_rgba", "background_rgba", "character_alpha")
    FUNCTION = "make_layers"
    CATEGORY = "ALRemover"
    DESCRIPTION = "Create transparent character/background images for standard Preview Image or Save Image nodes. Original RGB is preserved. Background has a transparent character-shaped hole."

    def make_layers(self, images, foreground_mask, input_transparency=None):
        alpha = source_alpha(images, input_transparency)
        mask = matching_mask(foreground_mask, images.shape[:3], images.device)
        # Partition in PNG's 8-bit domain, matching the Neo layer exporter.
        alpha_bytes = torch.round(alpha * 255)
        mask_bytes = torch.round(mask * 255)
        foreground = torch.floor((alpha_bytes * mask_bytes + 127) / 255) / 255
        background = (alpha_bytes - torch.round(foreground * 255)) / 255
        rgb = images[..., :3].float()
        return (torch.cat((rgb, foreground.unsqueeze(-1)), dim=-1),
                torch.cat((rgb, background.unsqueeze(-1)), dim=-1), foreground)


NODE_CLASS_MAPPINGS = {
    "ALRemoverCutout": ALRemoverCutout,
    "ALRemoverCorrectMask": ALRemoverCorrectMask,
    "ALRemoverLayers": ALRemoverLayers,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ALRemoverCutout": "ALRemover 切り抜き / Cutout",
    "ALRemoverCorrectMask": "ALRemover 部分修正 / Correct Mask",
    "ALRemoverLayers": "ALRemover キャラクター・背景 / Layers",
}
