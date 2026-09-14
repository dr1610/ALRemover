"""Forge Neo UI: normal Script integration plus full-resolution local correction."""
from datetime import datetime
from pathlib import Path
import uuid
import gradio as gr
from PIL import Image, PngImagePlugin
from .engine import MODES, MODE_IDS, DEFAULT_MODE, extract, release_models
from .layers import KINDS, SLUGS, normalize, layers, paint_mask
from .metadata import read_metadata, tagged_info, provenance

DISPLAY_DEFAULT = ["キャラクター", "背景"]
BRUSH_MODES = {"緑：残す": "#00ff00", "赤：消す": "#ff0000"}


def tab_brush_mode(mode):
    # Some Gradio 4.40 frontends reset palette selection to default_color.
    # Update the actual default explicitly; omit value so existing strokes stay.
    color = BRUSH_MODES[mode]
    return gr.ImageEditor(brush=gr.Brush(colors=[color], default_color=color, color_mode="fixed"))


def _preview(session, kinds):
    if not session:
        return []
    results = layers(session["source"], session["mask"])
    return [(results[kind], kind) for kind in (kinds or []) if kind in results]


def _editor_value(source):
    return {"background": source.copy(), "layers": [], "composite": source.copy()}


def tab_extract(source, mode, expand, display):
    if source is None:
        raise gr.Error("元画像を選択してください。")
    source = normalize(source)
    from modules import shared
    shared.state.begin(job="ALRemover")
    try:
        mask = extract(source, mode, expand, cancel=lambda: shared.state.interrupted,
                       status=lambda text: setattr(shared.state, "textinfo", text))
    except InterruptedError as exc:
        raise gr.Error(str(exc)) from exc
    finally:
        shared.state.end()
    session = {"source": source, "base_mask": mask, "mask": mask.copy(),
               "metadata": read_metadata(source), "mode": mode,
               "expand": int(expand), "edited": False}
    return session, _editor_value(source), _preview(session, display), "切り抜き完了。必要なら緑・赤で塗り、［修正を反映］を押してください。", []


def tab_apply(session, editor, display):
    if not session:
        raise gr.Error("先に［切り抜く］を押してください。")
    background = (editor or {}).get("background")
    if background is None or background.size != session["source"].size:
        raise gr.Error("修正画面が変わっています。［修正をリセット］を押してください。")
    try:
        mask = paint_mask(session["base_mask"], editor)
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    session = dict(session, mask=mask, edited=True)
    return session, _preview(session, display), "修正を反映しました。", []


def tab_reset(session, display):
    if not session:
        return None, None, [], "元画像を選択してください。", []
    session = dict(session, mask=session["base_mask"].copy(), edited=False)
    return session, _editor_value(session["source"]), _preview(session, display), "修正をリセットしました。", []


def tab_save(session, kinds):
    if not session:
        raise gr.Error("先に［切り抜く］を押してください。")
    if not kinds:
        raise gr.Error("保存する画像を選択してください。")
    from modules.paths_internal import data_path
    # Independent from diffusion checkpoint filename patterns; no model load on save.
    directory = Path(data_path) / "outputs" / "ALRemover" / datetime.now().strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now().strftime("%H%M%S-%f") + "-" + uuid.uuid4().hex[:8]
    files = []
    results = layers(session["source"], session["mask"])
    for kind in kinds:
        if kind not in results:
            continue
        seed = session["metadata"]["seed"]
        filename = directory / f"{prefix}-{seed}-{MODE_IDS[session['mode']]}-{SLUGS[kind]}.png"
        info = PngImagePlugin.PngInfo()
        info.add_text("parameters", tagged_info(session["metadata"], session["mode"], kind,
                                                session["expand"], session["edited"]))
        info.add_text("ALRemover", provenance(session["mode"], kind, session["expand"], session["edited"]))
        results[kind].save(filename, pnginfo=info)
        files.append(str(filename))
    return files, f"{len(files)} 枚を保存しました。保存先: {directory}"


def on_ui_tabs():
    from modules.call_queue import wrap_queued_call
    from modules import shared
    # On a fresh Neo install its configured preview directory may not exist yet.
    # Forge's PIL serializer expects it to exist when temp_dir is non-empty.
    if shared.opts.temp_dir:
        Path(shared.opts.temp_dir).mkdir(parents=True, exist_ok=True)
    with gr.Blocks(analytics_enabled=False) as tab:
        gr.Markdown("## ALRemover\nキャラクターを切り抜き、必要な所だけ直して保存します。背景は人物部分が透明なPNGです。")
        session = gr.State(None)
        with gr.Row():
            with gr.Column():
                source = gr.Image(label="元画像", type="pil", image_mode="RGBA", format="png",
                                  sources=["upload", "clipboard"], height=450)
                mode = gr.Dropdown(MODES, value=DEFAULT_MODE, label="切り抜き方式")
                gr.Markdown("まずはBEN2で切り抜いてください。順送り・逆送りは比較用で、細い髪が薄くなる場合があります。")
                expand = gr.Slider(-8, 8, value=0, step=1, label="輪郭の調整（px／＋で広げる・−で縮める）")
                run = gr.Button("切り抜く", variant="primary")
            with gr.Column():
                display = gr.CheckboxGroup(KINDS, value=DISPLAY_DEFAULT, label="表示する画像")
                gallery = gr.Gallery(label="結果", columns=2, height=520, format="png",
                                     object_fit="contain", preview=True)
                save_kinds = gr.CheckboxGroup(KINDS, value=DISPLAY_DEFAULT, label="保存する画像")
                save = gr.Button("選択した画像を PNG 保存")
                files = gr.Files(label="保存した PNG", interactive=False)
        status = gr.Markdown("元画像を選択してください。")
        with gr.Accordion("部分修正（緑＝残す／赤＝消す）", open=False):
            gr.Markdown("消しゴムで塗りを戻せます。塗った範囲だけが変わります。修正を反映してから保存してください。")
            brush_mode = gr.Radio(list(BRUSH_MODES), value="緑：残す", label="修正ブラシ")
            editor = gr.ImageEditor(
                label="部分修正", type="pil", image_mode="RGBA", format="png",
                sources=[], transforms=[], height=700, layers=True,
                brush=gr.Brush(colors=["#00ff00"], default_color="#00ff00", color_mode="fixed"))
            with gr.Row():
                apply = gr.Button("修正を反映", variant="primary")
                reset = gr.Button("修正をリセット")
        with gr.Accordion("メモリ", open=False):
            gr.Markdown("処理後はモデルをGPUから退避します。CPUメモリからも解放したい場合に使用してください。")
            release = gr.Button("切り抜きモデルをメモリから解放")
        source.change(lambda: (None, None, [], "元画像を変更しました。［切り抜く］を押してください。", []),
                      outputs=[session, editor, gallery, status, files], show_progress="hidden")
        run.click(wrap_queued_call(tab_extract), [source, mode, expand, display],
                  [session, editor, gallery, status, files], api_name="alr_neo_extract")
        display.change(_preview, [session, display], gallery, show_progress="hidden")
        brush_mode.change(tab_brush_mode, brush_mode, editor, api_name="alr_neo_brush_color", show_progress="hidden")
        apply.click(tab_apply, [session, editor, display], [session, gallery, status, files])
        reset.click(tab_reset, [session, display], [session, editor, gallery, status, files])
        save.click(tab_save, [session, save_kinds], [files, status], api_name="alr_neo_save")
        release.click(wrap_queued_call(lambda: (release_models(), "切り抜きモデルをメモリから解放しました。")[1]),
                      outputs=status)
    from .people_ui import build_tab
    return [(tab, "ALRemover", "anime_layer_remover_neo"),
            (build_tab(), "ALRemover 人物別（実験）", "alr_people")]
