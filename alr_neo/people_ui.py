"""Instance editor UI. Every mutating event shares one Gradio concurrency group."""
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
import gradio as gr
from . import people as P
from .engine import MODES, DEFAULT_MODE, extract
from .people_models import detect_people, segment_people, release_people_models

ADD = "新しい人物を追加"
INCLUDE = "この人物に含める"
EXCLUDE = "この人物から除外"
SELECT = "人物を選ぶ"


def output_dir():
    from modules.paths_internal import data_path
    return Path(data_path) / "outputs" / "ALRemover" / datetime.now().strftime("%Y-%m-%d") / "people"


@contextmanager
def job():
    from modules import shared
    shared.state.begin(job="ALRemover 人物別（実験）")
    try:
        yield lambda: shared.state.interrupted, lambda text: setattr(shared.state, "textinfo", text)
    except (ValueError, InterruptedError) as exc:
        raise gr.Error(str(exc)) from exc
    finally:
        shared.state.end()


def require(state):
    if not state:
        raise gr.Error("画像を選んで、自動人物分けか手動指定で始めてください。")


def run_masks(state, cancel, status):
    for p, mask in zip(state["persons"], segment_people(state["source"], state["persons"], cancel, status)):
        p["mask"] = mask


def prepare(source, mode, automatic):
    if source is None:
        raise gr.Error("元画像を選択してください。")
    if source.width * source.height > P.MAX_PIXELS:
        raise gr.Error("人物別編集は2400万画素まで対応しています。")
    with job() as (cancel, status):
        mask = extract(source, mode, cancel=cancel, status=status)
        state = P.auto_split(source, mask, mode, cancel, status) if automatic else P.create(source, mask, mode)
    return state


def render(state, selected=None, message=""):
    if not state:
        return (None, None, None, [], gr.update(choices=[], value=None), "", 0, 100, True,
                gr.update(choices=[], value=[]), "元画像を選んでください。", None, [], ADD)
    selected = int(selected) if selected is not None else None
    current = P.person(state, selected)
    if current is None and state["persons"]:
        current = state["persons"][0]
    selected = current["id"] if current else None
    overlay, composite, gallery, remainder = P.preview(state, selected)
    options = [(p["name"] + " [" + chr(64+p["id"]) + "]", p["id"]) for p in state["persons"]]
    status = f"{message}\n\n{len(state['persons'])} 人 ／ 未割当 {remainder:.1f}%（全体のアルファ量に対する割合）"
    if not state["persons"]:
        status += "\n\n人物を追加モードで、胴体をクリックしてください。"
    editor = {"background": overlay.copy(), "layers": [], "composite": overlay.copy()}
    return (state, overlay, composite, gallery, gr.update(choices=options, value=selected),
            current["name"] if current else "", current["expand"] if current else 0,
            current["opacity"] if current else 100, current["visible"] if current else True,
            gr.update(choices=options, value=[p["id"] for p in state["persons"]
                                             if state.get("export_ids") is None or p["id"] in state["export_ids"]]), status, editor, [],
            SELECT if current else ADD)


def auto_start(source, mode):
    state = prepare(source, mode, True)
    return render(state, message="自動候補を作りました。色分けを確認し、必要なら点やブラシで所属を直してください。")


def manual_start(source, mode):
    return render(prepare(source, mode, False), message="背景の分離ができました。人物ごとに胴体をクリックして追加してください。")


def click_core(state, selected, action, xy):
    require(state)
    x, y = map(int, xy)
    if not (0 <= x < state["source"].width and 0 <= y < state["source"].height):
        raise gr.Error("画像内をクリックしてください。")
    if action == SELECT:
        selected = int(P.ownership(state)[y, x])
        return render(state, selected or None, "人物を選択しました。" if selected else "未割当の部分です。")
    result = P.remember(state)
    if action == ADD:
        current = P.add_person(result, (x, y))
        selected = current["id"]
    else:
        current = P.person(result, selected)
        if current is None:
            raise gr.Error("調整する人物を選んでください。")
        if len(current["points"]) >= 64:
            raise gr.Error("指定点は1人につき64点までです。")
        current["points"].append((x, y, 1 if action == INCLUDE else 0))
        if action == INCLUDE and current["box"]:
            a, b, c, d = current["box"]
            current["box"] = [max(0, min(a, x-8)), max(0, min(b, y-8)),
                              min(state["source"].width-1, max(c, x+8)),
                              min(state["source"].height-1, max(d, y+8))]
    with job() as (cancel, status):
        run_masks(result, cancel, status)
    outputs = list(render(result, selected, "指定点から人物の所属を更新しました。"))
    outputs[-1] = action
    return tuple(outputs)


def click_image(state, selected, action, evt: gr.SelectData):
    return click_core(state, selected, action, evt.index)


def settings(state, selected, name, expand, opacity, visible):
    require(state)
    if not P.person(state, selected):
        raise gr.Error("調整する人物を選んでください。")
    result = P.remember(state)
    p = P.person(result, selected)
    p.update(name=(name.strip() or p["name"])[:60], expand=int(expand), opacity=int(opacity), visible=bool(visible))
    return render(result, selected, "この人物の調整を反映しました。")


def remove(state, selected):
    require(state)
    result = P.remember(state)
    result["persons"] = [p for p in result["persons"] if p["id"] != int(selected or 0)]
    result["forced"][result["forced"] == int(selected or 0)] = -1
    return render(result, message="人物の登録を解除しました。元の画像は保持されています。")


def brush(state, selected, editor, restore=False):
    require(state)
    background = (editor or {}).get("background")
    if background is None or background.size != state["source"].size:
        raise gr.Error("修正画面を更新してから塗り直してください。")
    result = P.remember(state)
    try:
        P.apply_brush(result, editor, restore=restore)
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    return render(result, selected, "塗った部分を更新しました。白は未割当、黒は背景です。戻すには［ひとつ戻す］を使用してください。")


def assign_remainder(state, selected):
    require(state)
    if not P.person(state, selected):
        raise gr.Error("人物を選んでください。")
    result = P.remember(state)
    owners = P.ownership(result)
    result["forced"][owners == 0] = int(selected)
    return render(result, selected, "未割当をこの人物に割り当てました。")


def save_outputs(state, selected, kinds):
    require(state)
    try:
        files = P.export(state, selected, kinds, output_dir())
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    return files, f"{len(files)} ファイルを保存しました。保存先: {output_dir()}"


def save_project(state):
    require(state)
    path = P.save_project(state, output_dir())
    return [path], "人物・指定点・調整・元画像を保存しました。このプロジェクトを開くと同じ画像の編集を再開できます。"


def open_project(file):
    if not file:
        raise gr.Error("保存した .alrneo.zip を選んでください。")
    try:
        state = P.load_project(file)
        return (*render(state, message="プロジェクトを読み込みました。"), state["source"])
    except Exception as exc:
        raise gr.Error(f"プロジェクトを開けませんでした: {exc}") from exc


def build_tab():
    from modules.call_queue import wrap_queued_call
    common = dict(concurrency_id="alr_people_edit", concurrency_limit=1)
    with gr.Blocks(analytics_enabled=False) as tab:
        gr.Markdown("## ALRemover · 人物別編集（実験）\n画像内の人物を色分けし、A・Bごとに調整・保存できます。接触する腕・手・髪の所属を誤ることがあります。一人の切り抜きには［ALRemover］タブを使ってください。")
        state = gr.State(None)
        with gr.Row():
            with gr.Column(scale=1):
                source = gr.Image(label="人物別の元画像", type="pil", image_mode="RGBA", format="png",
                                  height=280, sources=["upload", "clipboard"], elem_id="alr_people_source")
                mode = gr.Dropdown(MODES, value=DEFAULT_MODE, label="全体の背景を分離する方式")
                with gr.Row():
                    auto = gr.Button("自動で人物分け", variant="primary")
                    manual = gr.Button("手動指定で始める")
                active = gr.Dropdown([], label="調整する人物", type="value", elem_id="alr_people_active")
                action = gr.Radio([SELECT, ADD, INCLUDE, EXCLUDE], value=ADD, label="クリック操作",
                                  elem_id="alr_people_action")
                name = gr.Textbox(label="人物の名前")
                expand = gr.Slider(-8, 8, value=0, step=1, label="所属範囲を広げる・縮める（px）")
                opacity = gr.Slider(0, 100, value=100, step=1, label="この人物の不透明度（%）")
                visible = gr.Checkbox(True, label="合成プレビューにこの人物を表示")
                apply = gr.Button("この人物の調整を反映")
                with gr.Row():
                    back = gr.Button("ひとつ戻す")
                    delete = gr.Button("人物の登録を解除")
                remainder = gr.Button("未割当をこの人物へ")
                gr.Markdown("同じ人物の腕・手は［この人物に含める］で指定します。隠れている体の補完は行いません。")
            with gr.Column(scale=2):
                canvas = gr.Image(label="人物をクリック（色は所属／白っぽい部分は未割当）",
                                  type="pil", image_mode="RGB", interactive=False, format="png",
                                  height=640, elem_id="alr_people_canvas")
                composite = gr.Image(label="表示する人物の合成プレビュー", type="pil", interactive=False,
                                     format="png", height=380)
        status = gr.Markdown("元画像を選んでください。", elem_id="alr_people_status")
        gallery = gr.Gallery(label="人物別の結果と未割当", columns=4, height=400, format="png", preview=False)
        with gr.Accordion("ブラシで所属を修正", open=False):
            gr.Markdown("A=青／B=オレンジ／C=紫／D=緑／E=ピンク／F=黄／G=水色／H=灰。白は未割当、黒は背景に戻す。塗ってから反映してください。")
            restore_edge = gr.Checkbox(False, label="人物色で塗った所の抜け・半透明も復元する")
            editor = gr.ImageEditor(label="所属の塗り分け", type="pil", image_mode="RGBA", format="png",
                                    sources=[], transforms=[], height=650,
                                    brush=gr.Brush(colors=P.COLORS+["#ffffff", "#000000"], default_color=P.COLORS[0], color_mode="fixed"))
            paint = gr.Button("所属の塗り分けを反映", variant="primary")
        with gr.Row():
            selected = gr.CheckboxGroup([], label="保存する人物")
            kinds = gr.CheckboxGroup(P.OUTPUTS, value=["人物PNG", "背景", "未割当"], label="保存する種類")
        save = gr.Button("選択した人物・画像を PNG 保存", variant="primary")
        gr.Markdown("PNGはすべて元画像と同じ大きさ・位置です。背景と［選択人物を除いた画像］は、除去部分が透明になります。非表示の人物も保存対象に選べます。")
        with gr.Accordion("編集を保存・再開", open=False):
            project = gr.Button("人物別プロジェクトを保存")
            project_file = gr.File(label="人物別プロジェクト（.alrneo.zip）", type="filepath", file_types=[".zip"])
            restore = gr.Button("このプロジェクトを開く")
        files = gr.Files(label="保存したファイル", interactive=False)
        release = gr.Button("人物分けモデルをメモリから解放")
        outputs = [state, canvas, composite, gallery, active, name, expand, opacity, visible,
                   selected, status, editor, files, action]
        source.input(lambda: render(None), outputs=outputs, **common)
        auto.click(wrap_queued_call(auto_start), [source, mode], outputs, api_name="alr_people_auto", **common)
        manual.click(wrap_queued_call(manual_start), [source, mode], outputs, api_name="alr_people_manual", **common)
        queued_click = wraps(click_image)(wrap_queued_call(click_image))
        canvas.select(queued_click, [state, active, action], outputs, api_name="alr_people_click", **common)
        active.input(lambda s, a: render(s, a), [state, active], outputs, **common)
        apply.click(settings, [state, active, name, expand, opacity, visible], outputs, api_name="alr_people_adjust", **common)
        back.click(lambda s, a: render(P.undo(s), a, "ひとつ前の状態に戻しました。") if s else render(None),
                   [state, active], outputs, api_name="alr_people_undo", **common)
        delete.click(remove, [state, active], outputs, **common)
        remainder.click(assign_remainder, [state, active], outputs, **common)
        paint.click(brush, [state, active, editor, restore_edge], outputs, api_name="alr_people_brush", **common)
        save.click(save_outputs, [state, selected, kinds], [files, status], api_name="alr_people_save", **common)
        selected.input(lambda s, ids: dict(s, export_ids=ids) if s else None, [state, selected], state, **common)
        project.click(save_project, state, [files, status], api_name="alr_people_project_save", **common)
        restore.click(open_project, project_file, outputs + [source], api_name="alr_people_project_open", **common)
        release.click(wrap_queued_call(lambda: (release_people_models(), "人物分けモデルを解放しました。")[1]),
                      outputs=status, **common)
    return tab
