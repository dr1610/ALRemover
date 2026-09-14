"""Selectable txt2img/img2img Script. Models are never loaded at import time."""
from pathlib import Path
import copy
import sys
import uuid
import gradio as gr

EXTENSION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTENSION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTENSION_ROOT))

from modules import scripts, images, shared
from modules.processing import process_images, Processed
from alr_neo.engine import MODES, MODE_IDS, DEFAULT_MODE, extract
from alr_neo.layers import KINDS, SLUGS, normalize, layers
from alr_neo.metadata import read_metadata, tagged_info, provenance


def _at(values, index, default=None):
    return values[index] if values and index < len(values) else default


def generated_samples(proc):
    # all_seeds is indexed by sample, while images/infotexts may start with a grid.
    start = proc.index_of_first_image
    count = len(proc.all_seeds)
    for i, image in enumerate(proc.images[start:start + count]):
        yield normalize(image), {
            "seed": _at(proc.all_seeds, i, proc.seed),
            "subseed": _at(proc.all_subseeds, i, proc.subseed),
            "prompt": _at(proc.all_prompts, i, proc.prompt),
            "negative_prompt": _at(proc.all_negative_prompts, i, proc.negative_prompt),
            "info": _at(proc.infotexts, start + i, proc.info)}


def direct_samples(p):
    seen = set()
    for image in p.init_images:
        # WebUI batch mode repeats a single input reference batch_size times.
        if id(image) not in seen:
            seen.add(id(image))
            yield normalize(image), read_metadata(image)


class Script(scripts.Script):
    def title(self):
        return "ALRemover"

    def show(self, is_img2img):
        return True

    def ui(self, is_img2img):
        mode = gr.Dropdown(MODES, value=DEFAULT_MODE, label="切り抜き方式")
        with gr.Row():
            display = gr.CheckboxGroup(KINDS, value=["キャラクター", "背景"], label="表示する画像")
            save = gr.CheckboxGroup(KINDS, value=["キャラクター", "背景"], label="自動保存する画像")
        direct = gr.Checkbox(value=True, visible=is_img2img,
                            label="入力画像をそのまま切り抜く（再生成しない）")
        with gr.Accordion("輪郭の調整・使い方", open=False):
            expand = gr.Slider(-8, 8, value=0, step=1, label="輪郭の調整（px／＋で広げる・−で縮める）")
            gr.Markdown("背景は人物部分が透明なPNGです。両方にチェックすると両方を出力します。\n"
                        "表示と自動保存は独立です。自動保存のチェックを全て外すと保存しません。\n"
                        "元の色を保持し、輪郭の調整は初期値0です。")
        return [mode, display, save, direct, expand]

    def run(self, p, mode, display, save, direct, expand):
        if not display and not save:
            raise gr.Error("表示または保存する画像を選択してください。")
        display, save = display or [], save or []
        direct = bool(direct and getattr(p, "init_images", None))
        if direct:
            samples = list(direct_samples(p))
            proc = None
        else:
            old_samples, old_grid = p.do_not_save_samples, p.do_not_save_grid
            try:
                # This Script's explicit output selections govern all saving.
                p.do_not_save_samples = p.do_not_save_grid = True
                proc = process_images(p)
            finally:
                p.do_not_save_samples, p.do_not_save_grid = old_samples, old_grid
            samples = list(generated_samples(proc))
        shown, metadata, infos = [], [], []
        token = uuid.uuid4().hex[:10]
        interrupted = False
        old_text = shared.state.textinfo
        try:
            for i, (source, meta) in enumerate(samples):
                if shared.state.interrupted:
                    interrupted = True
                    break
                try:
                    mask = extract(source, mode, expand,
                                   cancel=lambda: shared.state.interrupted,
                                   status=lambda text: setattr(shared.state, "textinfo",
                                                               f"ALRemover {i+1}/{len(samples)}: {text}"))
                except InterruptedError:
                    interrupted = True
                    break
                results = layers(source, mask)
                items = [(kind, kind, SLUGS[kind], results[kind]) for kind in KINDS]
                for kind, label, slug, result in items:
                    if kind not in display and kind not in save:
                        continue
                    info = tagged_info(meta, mode, label, expand)
                    result.info["parameters"] = info
                    result.info["ALRemover"] = provenance(mode, label, expand)
                    if kind in save:
                        # Unique suffix also prevents overwrite when WebUI numbering is disabled.
                        images.save_image(
                            result, p.outpath_samples, "", seed=meta["seed"], prompt=meta["prompt"],
                            extension="png", info=info, p=p, existing_info={"ALRemover": result.info["ALRemover"]},
                            suffix=f"-alremover-{token}-{i+1}-{MODE_IDS[mode]}-{slug}")
                    if kind in display:
                        shown.append(result)
                        metadata.append(meta)
                        infos.append(info)
        finally:
            shared.state.textinfo = old_text
        if proc is None:
            proc = Processed(p, [], seed=-1)
        else:
            proc = copy.copy(proc)
        fallback = samples[0][1] if samples else {"seed": -1, "subseed": -1, "prompt": "", "negative_prompt": ""}
        alignment = metadata or [fallback]
        proc.images, proc.infotexts, proc.index_of_first_image = shown, infos, 0
        proc.all_seeds = [m["seed"] for m in alignment]
        proc.all_subseeds = [m["subseed"] for m in alignment]
        proc.all_prompts = [m["prompt"] for m in alignment]
        proc.all_negative_prompts = [m["negative_prompt"] for m in alignment]
        proc.seed, proc.subseed = proc.all_seeds[0], proc.all_subseeds[0]
        proc.prompt, proc.negative_prompt = proc.all_prompts[0], proc.all_negative_prompts[0]
        proc.info = infos[0] if infos else ""
        if interrupted:
            proc.comments += "\nALRemover: 中断しました。完了済みの画像のみ表示・保存しています。"
        if direct and samples:
            proc.width, proc.height = samples[0][0].size
        return proc
