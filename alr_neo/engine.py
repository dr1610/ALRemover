"""Lazy inference, pinned weights, sequential GPU use, no generation RNG changes."""
from contextlib import contextmanager
from pathlib import Path
import gc
import random
import threading
import numpy as np
from PIL import Image
from .layers import multiply_alpha, normalize, adjust_mask

MODES = ["ToonOut → BEN2（灰色背景）", "ToonOut", "BEN2", "BEN2 → ToonOut（灰色背景）"]
DEFAULT_MODE = "BEN2"
MODE_IDS = dict(zip(MODES, ["toonout-ben2-gray", "toonout", "ben2", "ben2-toonout-gray"]))
CASCADE_STAGES = {
    "toonout-ben2-gray": ("toonout", "ben2"),
    "ben2-toonout-gray": ("ben2", "toonout"),
}
SPECS = {
    "toonout": ("joelseytre/toonout", "cbf720eca394edcde66b861a8a8c20fbabe9c748",
                "birefnet_finetuned_toonout.pth", 885046394),
    "ben2": ("PramaLLC/BEN2", "e48a20765fb421d19dcdb0bf3cc61e802ca5ec8f",
             "model.safetensors", 380577976),
}
_LOCK = threading.RLock()
_MODELS = {}


@contextmanager
def preserve_runtime():
    import torch
    py_state, np_state = random.getstate(), np.random.get_state()
    deterministic = torch.backends.cudnn.deterministic
    benchmark = torch.backends.cudnn.benchmark
    precision = torch.get_float32_matmul_precision()
    # BEN2 seeds every CUDA device, so save every device's generator.
    devices = list(range(torch.cuda.device_count())) if torch.cuda.is_available() else []
    try:
        with torch.random.fork_rng(devices=devices):
            yield
    finally:
        random.setstate(py_state)
        np.random.set_state(np_state)
        torch.backends.cudnn.deterministic = deterministic
        torch.backends.cudnn.benchmark = benchmark
        torch.set_float32_matmul_precision(precision)


def model_directory():
    try:
        from modules.paths_internal import models_path
        return Path(models_path) / "AnimeLayerRemoverNeo"
    except ImportError:
        return Path(__file__).resolve().parents[1] / "models"


def weight_path(name, directory=None):
    directory = Path(directory) if directory else model_directory()
    repo, revision, filename, size = SPECS[name]
    target = directory / name / filename
    if target.is_file():
        if target.stat().st_size != size:
            raise RuntimeError(f"モデルファイルが不完全です: {target}")
        return target
    from huggingface_hub import hf_hub_download
    print(f"[ALRemover] Downloading {name} ({size / 2**20:.0f} MiB)")
    path = Path(hf_hub_download(repo_id=repo, filename=filename, revision=revision,
                               local_dir=str(directory / name)))
    if path.stat().st_size != size:
        raise RuntimeError(f"モデルのダウンロードを確認してください: {path}")
    return path


def _load(name, directory=None):
    import torch
    path = weight_path(name, directory)
    key = (name, str(path.resolve()))
    if key in _MODELS:
        return _MODELS[key]
    print(f"[ALRemover] Loading {name}")
    if name == "toonout":
        from .vendor.birefnet import BiRefNet
        model = BiRefNet(bb_pretrained=False)
        state = torch.load(path, map_location="cpu", weights_only=True)
        clean = {}
        for key_name, value in state.items():
            while key_name.startswith(("module.", "_orig_mod.")):
                key_name = key_name.split(".", 1)[1]
            clean[key_name] = value
        model.load_state_dict(clean, strict=True)
    else:
        from .vendor.ben2 import BEN_Base
        from safetensors.torch import load_file
        model = BEN_Base()
        model.load_state_dict(load_file(str(path), device="cpu"), strict=True)
    model.eval()
    _MODELS[key] = model
    return model


def _check(cancel):
    if cancel and cancel():
        raise InterruptedError("切り抜きを中断しました。")


def _infer(name, rgb, directory, cancel, status):
    import torch
    _check(cancel)
    status(f"{name}: モデルを準備")
    model = _load(name, directory)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        try:
            from backend import memory_management
        except ImportError:
            pass
        else:
            # Cooperate with Forge's model manager; do not evict untracked models.
            memory_management.free_memory(4.5 * 2**30, memory_management.get_torch_device())
    try:
        model.to(device=device, dtype=torch.float32)
        _check(cancel)
        status(f"{name}: 切り抜き中")
        with torch.inference_mode():
            if name == "toonout":
                from torchvision import transforms
                transform = transforms.Compose([
                    transforms.Resize((1024, 1024)), transforms.ToTensor(),
                    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
                x = transform(rgb).unsqueeze(0).to(device)
                prediction = model(x)[-1].sigmoid().float().cpu()
                if not torch.isfinite(prediction).all():
                    raise RuntimeError("ToonOut のマスクに不正な値が含まれています。")
                alpha = transforms.ToPILImage()(prediction[0].squeeze()).resize(
                    rgb.size, Image.Resampling.BICUBIC)
                del x, prediction
            else:
                alpha = model.inference(rgb.copy(), refine_foreground=False).getchannel("A")
        _check(cancel)
        return alpha
    finally:
        model.cpu()
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()


def extract(source, mode=DEFAULT_MODE, expand=0, directory=None, cancel=None, status=None):
    if mode not in MODES:
        raise ValueError("切り抜き方式を選択してください。")
    source = normalize(source)
    # Transparent input RGB must not be interpreted as visible content.
    gray = Image.new("RGBA", source.size, (128, 128, 128, 255))
    rgb = Image.alpha_composite(gray, source).convert("RGB")
    report = status or (lambda text: print("[ALRemover] " + text))
    with _LOCK, preserve_runtime():
        stages = CASCADE_STAGES.get(MODE_IDS[mode])
        if stages:
            first = _infer(stages[0], rgb, directory, cancel, report)
            intermediate = rgb.copy()
            intermediate.putalpha(multiply_alpha(source.getchannel("A"), first))
            composite = Image.alpha_composite(gray, intermediate).convert("RGB")
            second = _infer(stages[1], composite, directory, cancel, report)
            mask = multiply_alpha(first, second)
        else:
            mask = _infer(MODE_IDS[mode], rgb, directory, cancel, report)
        return adjust_mask(mask, expand)


def release_models():
    with _LOCK:
        _MODELS.clear()
        gc.collect()
