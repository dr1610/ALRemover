"""Exercise a running local Neo through its real Gradio queue; saves test PNGs."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw
from gradio_client import Client, handle_file


def local_path(value):
    return Path(value['path'] if isinstance(value, dict) else value)


def verify(url, image_path, output):
    output.mkdir(parents=True, exist_ok=True)
    original_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    source = Image.open(image_path).convert('RGBA')
    pixels = np.asarray(source)
    if min(source.size) < 32:
        raise ValueError('Choose an image of at least 32 x 32 pixels.')
    client = Client(url, verbose=False)
    started = time.perf_counter()
    result = client.predict(handle_file(str(image_path.resolve())), 'BEN2', 0,
                            ['キャラクター', '背景'], api_name='/alr_neo_extract')
    elapsed = time.perf_counter() - started
    assert len(result[1]) == 2 and '切り抜き完了' in result[2], result[2]
    paths, _ = client.predict(['元画像', 'キャラクター', '背景', 'マスク'], api_name='/alr_neo_save')
    assert len(paths) == 4
    saved = [Image.open(local_path(p)) for p in paths]
    baseline = np.asarray(saved[1]).copy()
    background = np.asarray(saved[2])
    assert saved[1].mode == saved[2].mode == 'RGBA'
    assert saved[1].size == saved[2].size == source.size
    np.testing.assert_array_equal(np.asarray(saved[0]), pixels)
    np.testing.assert_array_equal(baseline[..., :3], pixels[..., :3])
    np.testing.assert_array_equal(background[..., :3], pixels[..., :3])
    np.testing.assert_array_equal(baseline[..., 3].astype(np.uint16) + background[..., 3], pixels[..., 3])
    np.testing.assert_array_equal(np.asarray(saved[3]), baseline[..., 3])
    assert 'ALR Mode: ben2' in saved[1].info['parameters']
    assert 'ALR Edited: False' in saved[1].info['parameters']
    provenance = json.loads(saved[1].info['ALRemover'])
    assert provenance['rgb'] == 'original'
    # Keep the unedited output for inspecting model quality separately from workflow correctness.
    saved[1].save(output/'baseline-character.png')
    saved[2].save(output/'baseline-background.png')
    saved[3].save(output/'baseline-mask.png')

    width, height = source.size
    stroke = Image.new('RGBA', source.size)
    draw = ImageDraw.Draw(stroke)
    green_box = (width//4, height//3, width//4 + 5, height//3 + 5)
    red_box = (3*width//4, 2*height//3, 3*width//4 + 5, 2*height//3 + 5)
    draw.rectangle(green_box, fill=(0,255,0,255))
    draw.rectangle(red_box, fill=(255,0,0,255))
    stroke_path = output/'test-brush.png'
    stroke.save(stroke_path)
    editor = {'background': handle_file(str(image_path.resolve())),
              'layers': [handle_file(str(stroke_path.resolve()))],
              'composite': handle_file(str(image_path.resolve()))}
    changed = client.predict(editor, ['キャラクター','背景'], api_name='/tab_apply')
    assert '修正を反映' in changed[1]
    edited_paths, _ = client.predict(['キャラクター','背景'], api_name='/alr_neo_save')
    edited_fg, edited_bg = [Image.open(local_path(p)) for p in edited_paths]
    edited = np.asarray(edited_fg)
    marked = np.asarray(stroke)[...,3] > 0
    np.testing.assert_array_equal(edited[~marked], baseline[~marked])
    np.testing.assert_array_equal(edited[..., :3], pixels[..., :3])
    gx, gy = green_box[:2]
    rx, ry = red_box[:2]
    assert edited[gy,gx,3] == pixels[gy,gx,3]
    assert edited[ry,rx,3] == 0
    np.testing.assert_array_equal(edited[...,3].astype(np.uint16) + np.asarray(edited_bg)[...,3], pixels[...,3])
    assert 'ALR Edited: True' in edited_fg.info['parameters']

    # Removing strokes restores the base. Display selection must not constrain saved kinds.
    editor['layers'] = []
    client.predict(editor, ['キャラクター'], api_name='/tab_apply')
    restored, _ = client.predict(['キャラクター','背景'], api_name='/alr_neo_save')
    assert len(restored) == 2
    np.testing.assert_array_equal(np.asarray(Image.open(local_path(restored[0]))), baseline)
    reset = client.predict(['キャラクター'], api_name='/tab_reset')
    assert 'リセット' in reset[2]
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == original_hash
    result = {'extract_seconds_including_model_setup': round(elapsed, 3),
              'input_size': list(source.size), 'input_unchanged': True,
              'original_rgb_exact': True, 'existing_alpha_preserved': True,
              'character_background_mask_saved': True, 'keep_erase_brush': True,
              'unpainted_pixels_unchanged': True, 'empty_strokes_restore_base': True,
              'display_save_independent': True, 'metadata': True, 'reset': True,
              'version': provenance['version'],
              'quality_note': 'Workflow checks; no ground-truth segmentation accuracy is measured.'}
    (output/'single-person-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:7860')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'test-results/single-person')
    args = parser.parse_args()
    verify(args.url, args.image, args.output)
