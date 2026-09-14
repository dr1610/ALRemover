"""Editable, mutually exclusive ownership of the existing foreground alpha."""
from datetime import datetime
from pathlib import Path
import copy
import json
import uuid
import zipfile
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from .layers import normalize, multiply_alpha, adjust_mask
from .metadata import read_metadata, tagged_info
from .people_models import fingerprint

COLORS = ["#35a7ff", "#ff9635", "#ca6cff", "#38ce87", "#ff6097", "#dbcb30", "#00c8d7", "#bcbcbc"]
OUTPUTS = ["人物PNG", "人物マスク", "背景", "未割当", "選択人物を除いた画像"]
MAX_PIXELS = 24_000_000


def create(source, mask, mode):
    source = normalize(source)
    if source.width * source.height > MAX_PIXELS:
        raise ValueError("人物別編集は2400万画素まで対応しています。")
    return {"source": source, "mask": mask.copy(), "mode": mode, "metadata": read_metadata(source),
            "persons": [], "forced": np.full((source.height, source.width), -1, np.int16),
            "history": [], "revision": 0, "fingerprint": fingerprint(source)}


def remember(state):
    result = dict(state)
    frame = {"persons": copy.deepcopy(state["persons"]), "forced": state["forced"].copy(),
             "mask": state["mask"].copy()}
    result["history"] = (state["history"] + [frame])[-12:]
    result["persons"] = copy.deepcopy(state["persons"])
    result["forced"] = state["forced"].copy()
    result["revision"] = state["revision"] + 1
    return result


def undo(state):
    if not state["history"]:
        return state
    result = dict(state, **state["history"][-1])
    result["history"] = state["history"][:-1]
    result["revision"] = state["revision"] + 1
    return result


def add_person(state, point=None, box=None):
    used = {p["id"] for p in state["persons"]}
    number = next((i for i in range(1, 9) if i not in used), None)
    if number is None:
        raise ValueError("1枚につき最大8人です。")
    p = {"id": number, "name": "人物" + chr(64 + number), "box": box,
         "points": [tuple(point) + (1,)] if point else [], "mask": Image.new("L", state["source"].size),
         "expand": 0, "opacity": 100, "visible": True}
    state["persons"].append(p)
    return p


def auto_split(source, mask, mode, cancel=None, status=None):
    from .people_models import detect_people, segment_people
    state = create(source, mask, mode)
    if status:
        status("人物候補を検出中")
    for found in detect_people(source, cancel=cancel):
        box = found["box"]
        point = ((box[0] + box[2]) / 2, box[1] + (box[3] - box[1]) * 0.4)
        add_person(state, point, box)
    for p, prediction in zip(state["persons"], segment_people(source, state["persons"], cancel, status)):
        p["mask"] = prediction
    return state


def script_items(source, mask, mode, cancel=None, status=None):
    state = auto_split(source, mask, mode, cancel, status)
    owners, base, assigned = alpha_layers(state)
    yield "元画像", "元画像", "original", source
    for p in state["persons"]:
        suffix = chr(64 + p["id"])
        yield "キャラクター", p["name"], "character-" + suffix, rgba(source, assigned[p["id"]])
        yield "マスク", p["name"] + " マスク", "mask-" + suffix, Image.fromarray(assigned[p["id"]])
    remaining = np.where(owners == 0, base, 0).astype(np.uint8)
    if remaining.any():
        yield "キャラクター", "未割当", "unassigned", rgba(source, remaining)
        yield "マスク", "未割当 マスク", "mask-unassigned", Image.fromarray(remaining)
    yield "背景", "背景", "background", rgba(source, np.asarray(source.getchannel("A")).astype(np.int16) - base)


def person(state, number):
    return next((p for p in state["persons"] if p["id"] == int(number or 0)), None)


def ownership(state):
    """SAM supplies membership, never another multiplier on hair transparency."""
    height, width = state["forced"].shape
    winner = np.zeros((height, width), np.int16)
    confidence = np.full((height, width), 127, np.uint8)
    for p in state["persons"]:
        candidate = np.asarray(adjust_mask(p["mask"], p["expand"]))
        take = candidate > confidence
        winner[take] = p["id"]
        confidence[take] = candidate[take]
    # Recover a narrow fringe outside SAM's hard boundary, still limited by the base matte.
    # Nearby memberships are copied, never used as another soft alpha.
    if winner.any():
        import cv2
        unknown = (winner == 0).astype(np.uint8)
        distance, nearest = cv2.distanceTransformWithLabels(unknown, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        table = np.zeros(int(nearest.max()) + 1, np.int16)
        known = winner != 0
        table[nearest[known]] = winner[known]
        fringe = (winner == 0) & (distance <= 8)
        winner[fringe] = table[nearest[fringe]]
    force = state["forced"]
    winner[force >= 0] = force[force >= 0]
    winner[np.asarray(state["mask"]) == 0] = 0
    return winner


def alpha_layers(state):
    owners = ownership(state)
    base = np.asarray(multiply_alpha(state["source"].getchannel("A"), state["mask"]))
    return owners, base, {p["id"]: np.where(owners == p["id"], base, 0).astype(np.uint8) for p in state["persons"]}


def rgba(source, alpha):
    result = source.copy()
    result.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    return result


def preview(state, selected=None):
    owners, base, assigned = alpha_layers(state)
    source = state["source"]
    gray = Image.new("RGBA", source.size, (42, 46, 54, 255))
    display_alpha = np.zeros(base.shape, np.uint16)
    previews = []
    for p in state["persons"]:
        alpha = np.rint(assigned[p["id"]].astype(np.float32) * p["opacity"] / 100).astype(np.uint8)
        previews.append((rgba(source, alpha), f"{p['name']}（{'表示' if p['visible'] else '非表示'}）"))
        if p["visible"]:
            display_alpha += alpha
    remainder = np.where(owners == 0, base, 0).astype(np.uint8)
    combined = rgba(source, display_alpha + remainder)
    composite = Image.alpha_composite(gray, combined)
    overlay = np.asarray(Image.alpha_composite(gray, source).convert("RGB")).copy()
    for p in state["persons"]:
        color = np.array(tuple(bytes.fromhex(COLORS[p["id"] - 1][1:])), dtype=np.float32)
        mask = (owners == p["id"]) & (base > 0)
        overlay[mask] = np.rint(overlay[mask] * 0.62 + color * 0.38).astype(np.uint8)
    unassigned = (owners == 0) & (base > 32)
    overlay[unassigned] = np.rint(overlay[unassigned] * 0.5 + np.array([255, 255, 255]) * 0.5).astype(np.uint8)
    overlay = Image.fromarray(overlay)
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=max(14, source.width // 45))
    for p in state["persons"]:
        for x, y, label in p["points"]:
            radius = max(4, source.width // 180)
            draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                         fill=COLORS[p["id"]-1] if label else "#ff3030", outline="white", width=2)
        ys, xs = np.where(owners == p["id"])
        if xs.size:
            x, y = int(xs.mean()), max(0, int(ys.min()) - 28)
            draw.text((x, y), chr(64+p["id"]), fill=COLORS[p["id"]-1], stroke_fill="black", stroke_width=2, font=font)
    previews.append((rgba(source, remainder), "未割当"))
    percent = float(remainder.sum(dtype=np.uint64)) / max(int(base.sum(dtype=np.uint64)), 1) * 100
    return overlay, composite, previews, percent


def apply_brush(state, editor, erase=False, restore=False):
    for layer in (editor or {}).get("layers") or []:
        if not isinstance(layer, Image.Image) or layer.size != state["source"].size:
            raise ValueError("修正画像の大きさが違います。")
        pixels = np.asarray(layer.convert("RGBA"))
        painted = pixels[..., 3] > 127
        if erase:
            state["forced"][painted] = -1
            continue
        colors = np.array([tuple(bytes.fromhex(c[1:])) for c in COLORS] + [(255, 255, 255), (0, 0, 0)], dtype=np.int16)
        # White is unassigned; black explicitly removes a pixel from the whole foreground.
        best = np.zeros(painted.shape, np.int16)
        distance = np.full(painted.shape, 1e9, np.float32)
        for index, color in enumerate(colors):
            d = ((pixels[..., :3].astype(np.float32) - color) ** 2).sum(axis=-1)
            take = d < distance
            best[take], distance[take] = index + 1 if index < 8 else (0 if index == 8 else -2), d[take]
        valid_ids = [-2, 0] + [p["id"] for p in state["persons"]]
        if np.any(painted & ~np.isin(best, valid_ids) & (distance < 6000)):
            raise ValueError("その色の人物はまだ登録されていません。人物を追加してから塗ってください。")
        accepted = painted & np.isin(best, valid_ids) & (distance < 6000)
        state["forced"][accepted] = np.maximum(best[accepted], 0)
        matte = np.asarray(state["mask"]).copy()
        matte[accepted & (best == -2)] = 0
        if restore:
            matte[accepted & (best > 0)] = 255
        state["mask"] = Image.fromarray(matte)


def export(state, selected, kinds, directory):
    if not kinds:
        raise ValueError("保存する種類を選んでください。")
    selected = {int(x) for x in selected or []}
    if any(k in kinds for k in ("人物PNG", "人物マスク", "選択人物を除いた画像")) and not selected:
        raise ValueError("保存対象の人物を選んでください。")
    owners, base, assigned = alpha_layers(state)
    source = state["source"]
    prefix = datetime.now().strftime("%H%M%S-%f") + "-" + uuid.uuid4().hex[:8] + "-" + str(state["metadata"]["seed"])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files, rows = [], []
    chosen_alpha = np.zeros(base.shape, np.uint16)
    items = []
    for p in state["persons"]:
        if p["id"] not in selected:
            continue
        alpha = np.rint(assigned[p["id"]].astype(np.float32) * p["opacity"] / 100).astype(np.uint8)
        chosen_alpha += alpha
        slug = chr(64+p["id"])
        if "人物PNG" in kinds:
            items.append((f"person-{slug}", rgba(source, alpha), p["name"]))
        if "人物マスク" in kinds:
            items.append((f"mask-{slug}", Image.fromarray(alpha), p["name"] + " マスク"))
        rows.append({k: p[k] for k in ("id", "name", "points", "box", "expand", "opacity", "visible")})
    input_alpha = np.asarray(source.getchannel("A"))
    if "背景" in kinds:
        items.append(("background", rgba(source, input_alpha.astype(np.int16) - base), "背景"))
    if "未割当" in kinds:
        items.append(("unassigned", rgba(source, np.where(owners == 0, base, 0)), "未割当"))
    if "選択人物を除いた画像" in kinds:
        items.append(("without-selected", rgba(source, input_alpha.astype(np.int32) - chosen_alpha), "選択人物を除いた画像"))
    for slug, image, name in items:
        path = directory / f"{prefix}-{slug}.png"
        info = PngImagePlugin.PngInfo()
        info.add_text("parameters", tagged_info(state["metadata"], state["mode"], name, edited=True))
        info.add_text("ALR People", json.dumps({"name": name, "people": rows, "source": state["fingerprint"]}, ensure_ascii=False))
        image.save(path, pnginfo=info)
        files.append(str(path))
    manifest = directory / f"{prefix}-layers.json"
    manifest.write_text(json.dumps({"size": source.size, "seed": state["metadata"]["seed"], "people": rows,
                                    "files": [Path(p).name for p in files]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return files + [str(manifest)]


def save_project(state, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (datetime.now().strftime("%H%M%S-%f") + "-" + uuid.uuid4().hex[:8] + ".alrneo.zip")
    document = {"format": "alr-people-1", "mode": state["mode"], "metadata": state["metadata"],
                "export_ids": state.get("export_ids"),
                "persons": [{k: v for k, v in p.items() if k != "mask"} for p in state["persons"]]}
    images = {"source.png": state["source"], "foreground.png": state["mask"],
              "assignments.png": Image.fromarray((state["forced"] + 1).astype(np.uint8))}
    images.update({f"person-{p['id']}.png": p["mask"] for p in state["persons"]})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(document, ensure_ascii=False))
        for name, image in images.items():
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            archive.writestr(name, buffer.getvalue())
    return str(path)


def load_project(path):
    from .engine import MODES
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 16 or sum(e.file_size for e in entries) > 512 * 2**20:
            raise ValueError("プロジェクトが大きすぎます。")
        doc = json.loads(archive.read("project.json"))
        if doc.get("format") != "alr-people-1" or doc.get("mode") not in MODES or len(doc["persons"]) > 8:
            raise ValueError("対応していないプロジェクトです。")
        def read_image(name, mode):
            with Image.open(io.BytesIO(archive.read(name))) as im:
                if im.width * im.height > MAX_PIXELS:
                    raise ValueError("画像が大きすぎます。")
                return im.convert(mode)
        source = read_image("source.png", "RGBA")
        source.info["parameters"] = doc["metadata"].get("info", "")
        state = create(source, read_image("foreground.png", "L"), doc["mode"])
        if state["mask"].size != source.size:
            raise ValueError("画像とマスクのサイズが違います。")
        state["metadata"] = doc["metadata"]
        state["export_ids"] = doc.get("export_ids")
        state["forced"] = np.asarray(read_image("assignments.png", "L")).astype(np.int16) - 1
        seen = set()
        for saved in doc["persons"]:
            number = int(saved["id"])
            if number < 1 or number > 8 or number in seen:
                raise ValueError("人物IDが不正です。")
            seen.add(number)
            p = {"id": number, "name": str(saved["name"])[:60],
                 "box": saved.get("box"), "points": saved.get("points", []),
                 "expand": int(saved["expand"]), "opacity": int(saved["opacity"]), "visible": bool(saved["visible"]),
                 "mask": read_image(f"person-{number}.png", "L")}
            if p["mask"].size != source.size or not -8 <= p["expand"] <= 8 or not 0 <= p["opacity"] <= 100:
                raise ValueError("人物の設定が不正です。")
            for x, y, label in p["points"]:
                if not (0 <= x < source.width and 0 <= y < source.height and label in (0, 1)):
                    raise ValueError("指定点が画像の外です。")
            if p["box"] is not None and (len(p["box"]) != 4 or not all(np.isfinite(p["box"]))):
                raise ValueError("人物の枠が不正です。")
            state["persons"].append(p)
        if state["forced"].shape != (source.height, source.width) or not np.isin(state["forced"], [-1, 0] + list(seen)).all():
            raise ValueError("所属マスクが不正です。")
    return state
