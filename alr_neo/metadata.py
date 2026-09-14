"""Keep source generation metadata attached to each sample and output."""
import json
from . import __version__
from .engine import MODE_IDS


def read_metadata(image):
    info = str(image.info.get("parameters", ""))
    try:
        from modules.images import read_info_from_image
        info = read_info_from_image(image)[0] or info
        from modules.infotext_utils import parse_generation_parameters
        params = parse_generation_parameters(info) if info else {}
    except ImportError:
        # Standalone usage: preserve the text verbatim, parse only an actual Seed field.
        import re
        match = re.search(r"(?:^|, )Seed: (-?\d+)(?:,|$)", info, re.MULTILINE)
        params = {"Seed": match.group(1)} if match else {}
    try:
        seed = int(params.get("Seed", -1))
    except (ValueError, TypeError):
        seed = -1
    return {"info": info, "seed": seed, "prompt": params.get("Prompt", ""),
            "negative_prompt": params.get("Negative prompt", ""), "subseed": -1}


def tagged_info(metadata, mode, kind, expand=0, edited=False):
    info = metadata.get("info", "")
    suffix = (f"ALRemover: {__version__}, ALR Mode: {MODE_IDS[mode]}, "
              f"ALR Layer: {kind}, ALR Expand: {int(expand)}, ALR Edited: {edited}")
    return info + (", " if info else "") + suffix


def provenance(mode, kind, expand=0, edited=False):
    return json.dumps({"version": __version__, "mode": MODE_IDS[mode], "layer": kind,
                       "expand_px": int(expand), "edited": bool(edited),
                       "rgb": "original", "background": "transparent character hole"},
                      ensure_ascii=False)
