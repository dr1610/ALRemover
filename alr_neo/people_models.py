"""Local person proposals and point-prompted instance masks; no alpha matting here."""
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
import gc
import hashlib
import json
import numpy as np
from PIL import Image
from .engine import _LOCK, preserve_runtime, model_directory, _check

SPECS = {
    "sam2": ("facebook/sam2.1-hiera-large", "665f8e2ad61cf5f53d65644ff27c8ee525124610"),
    "grounding_dino": ("IDEA-Research/grounding-dino-tiny", "a2bb814dd30d776dcf7e30523b00659f4f141c71"),
}
_MODELS = {}
_FEATURES = OrderedDict()


def rgb_image(source):
    rgba = source.convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", source.size, (128, 128, 128, 255)), rgba).convert("RGB")


def fingerprint(source):
    return hashlib.sha256(str(source.size).encode() + source.tobytes()).hexdigest()


def _directory(name):
    directory = model_directory() / name
    required = ["config.json", "model.safetensors", "preprocessor_config.json"]
    if name == "sam2":
        required.append("processor_config.json")
    else:
        required += ["tokenizer.json", "tokenizer_config.json", "vocab.txt", "special_tokens_map.json", "added_tokens.json"]
    if not all((directory / f).is_file() for f in required):
        from huggingface_hub import snapshot_download
        repo, revision = SPECS[name]
        snapshot_download(repo_id=repo, revision=revision, local_dir=str(directory),
                          allow_patterns=required + ["README.md"])
    return directory


def _load(name):
    if name not in _MODELS:
        path = _directory(name)
        if name == "sam2":
            from transformers import Sam2Model, Sam2Processor, Sam2Config
            # Meta packages the image and video configuration together. Use its image
            # architecture explicitly; video memory/tracking is not part of this editor.
            config = json.loads((path / "config.json").read_text(encoding="utf-8"))
            config["model_type"], config["architectures"] = "sam2", ["Sam2Model"]
            model = Sam2Model.from_pretrained(path, config=Sam2Config.from_dict(config),
                                             local_files_only=True, use_safetensors=True)
            processor = Sam2Processor.from_pretrained(path, local_files_only=True)
        else:
            from transformers import GroundingDinoForObjectDetection, AutoProcessor
            model = GroundingDinoForObjectDetection.from_pretrained(path, local_files_only=True, use_safetensors=True)
            processor = AutoProcessor.from_pretrained(path, local_files_only=True)
        _MODELS[name] = (model.eval(), processor)
    return _MODELS[name]


@contextmanager
def _on_device(name, cancel):
    import torch
    _check(cancel)
    model, processor = _load(name)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        try:
            from backend import memory_management
        except ImportError:
            pass
        else:
            memory_management.free_memory(4.5 * 2**30, memory_management.get_torch_device())
    try:
        model.to(device)
        _check(cancel)
        with torch.inference_mode():
            yield model, processor, device
        _check(cancel)
    finally:
        model.cpu()
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()


def detect_people(source, threshold=0.25, cancel=None):
    rgb = rgb_image(source)
    with _LOCK, preserve_runtime(), _on_device("grounding_dino", cancel) as (model, processor, device):
        inputs = processor(images=rgb, text="a person. an anime character.", return_tensors="pt").to(device)
        output = model(**inputs)
        result = processor.post_process_grounded_object_detection(
            output, inputs.input_ids, threshold=threshold, text_threshold=0.25,
            target_sizes=[(rgb.height, rgb.width)])[0]
        found = []
        candidates = sorted(zip(result["boxes"], result["scores"]), key=lambda item: float(item[1]), reverse=True)
        for box, score in candidates:
            x1, y1, x2, y2 = box.detach().float().cpu().tolist()
            box = [max(0, x1), max(0, y1), min(rgb.width - 1, x2), min(rgb.height - 1, y2)]
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            if any(_iou(box, p["box"]) > 0.65 for p in found):
                continue
            found.append({"box": box, "score": round(float(score), 3)})
        return sorted(found[:8], key=lambda p: (p["box"][0] + p["box"][2]) / 2)


def _iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / max(union, 1)


def segment_people(source, persons, cancel=None, status=None):
    """Each instance has its own positive/negative query; positives are never merged across people."""
    import torch
    if not persons:
        return []
    rgb = rgb_image(source)
    key = fingerprint(rgb)
    result = []
    with _LOCK, preserve_runtime(), _on_device("sam2", cancel) as (model, processor, device):
        cached = _FEATURES.get(key)
        embeddings = [tensor.to(device) for tensor in cached] if cached is not None else None
        for person in persons:
            _check(cancel)
            if status:
                status(f"{person['name']}: 領域を判定中")
            positive = [p for p in person["points"] if p[2] == 1]
            points = list(person["points"])
            # Other instances' explicit anchors are negative only for this query.
            for other in persons:
                if other["id"] != person["id"]:
                    anchor = next((p for p in other["points"] if p[2] == 1), None)
                    if anchor and not any(abs(anchor[0]-p[0]) < 3 and abs(anchor[1]-p[1]) < 3 for p in positive):
                        points.append((anchor[0], anchor[1], 0))
            kwargs = {}
            if points:
                kwargs.update(input_points=[[[[p[0], p[1]] for p in points]]],
                              input_labels=[[[int(p[2]) for p in points]]])
            if person.get("box"):
                kwargs["input_boxes"] = [[person["box"]]]
            if not points and not person.get("box"):
                result.append(Image.new("L", source.size))
                continue
            inputs = processor(images=rgb, return_tensors="pt", **kwargs).to(device)
            original_sizes = inputs.pop("original_sizes")
            if embeddings is not None:
                inputs.pop("pixel_values", None)
                inputs["image_embeddings"] = embeddings
            output = model(**inputs, multimask_output=True)
            if embeddings is None:
                embeddings = output.image_embeddings
                _FEATURES[key] = [tensor.detach().cpu() for tensor in embeddings]
                while len(_FEATURES) > 2:
                    _FEATURES.popitem(last=False)
            logits = processor.post_process_masks(output.pred_masks.float().cpu(),
                                                   original_sizes, binarize=False)[0][0]
            quality = output.iou_scores[0, 0].detach().float().cpu().numpy()
            candidates = logits.numpy()
            valid = []
            for index, values in enumerate(candidates):
                honors = all((values[min(source.height-1, int(y)), min(source.width-1, int(x))] > 0) == bool(label)
                             for x, y, label in points)
                if honors and quality[index] >= quality.max() - 0.15:
                    valid.append(index)
            # Single-point prompts are ambiguous (face, torso, whole body). Prefer the complete
            # instance among similarly scored masks that honor all inclusion/exclusion points.
            chosen = max(valid, key=lambda i: int((candidates[i] > 0).sum())) if valid else int(quality.argmax())
            probabilities = torch.sigmoid(logits[chosen]).numpy()
            result.append(Image.fromarray(np.rint(probabilities * 255).astype(np.uint8)))
        if key in _FEATURES:
            _FEATURES.move_to_end(key)
        del embeddings
    return result


def release_people_models():
    with _LOCK:
        _FEATURES.clear()
        _MODELS.clear()
        gc.collect()
