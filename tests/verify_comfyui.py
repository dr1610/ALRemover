"""Test a running local ComfyUI: real extraction, correction, cache reuse and PNG saving."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import uuid

import numpy as np
from PIL import Image, ImageDraw
import requests


def verify(url, image_path, output, mode='BEN2'):
    output.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:10]
    original_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    source = Image.open(image_path).convert('RGBA')
    pixels = np.asarray(source)
    api = requests.Session()

    def upload(image, name):
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        response = api.post(url + '/upload/image', files={'image': (name, stream.getvalue(), 'image/png')}, timeout=30)
        response.raise_for_status()
        value = response.json()
        return '/'.join(p for p in (value.get('subfolder', ''), value['name']) if p)

    def run(graph):
        response = api.post(url + '/prompt', json={'prompt': graph, 'client_id': token}, timeout=30)
        response.raise_for_status()
        prompt_id = response.json()['prompt_id']
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            response = api.get(url + '/history/' + prompt_id, timeout=15)
            response.raise_for_status()
            history = response.json().get(prompt_id)
            if history:
                assert history['status']['status_str'] == 'success', history['status']
                return history
            time.sleep(0.5)
        raise TimeoutError('ComfyUI did not finish within 300 seconds.')

    def saved(history, node):
        entry = history['outputs'][node]['images'][0]
        response = api.get(url + '/view', params=entry, timeout=30)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))

    info = api.get(url + '/object_info', timeout=30).json()
    for name in ('ALRemoverCutout', 'ALRemoverCorrectMask', 'ALRemoverLayers'):
        assert name in info, name
    assert info['ALRemoverCutout']['input']['required']['mode'][1]['default'] == 'BEN2'
    name = upload(source, 'alremover-verification-' + token + '.png')
    graph = {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': name}},
        '2': {'class_type': 'ALRemoverCutout', 'inputs': {'images': ['1', 0], 'input_transparency': ['1', 1], 'mode': mode, 'expand': 0}},
        '3': {'class_type': 'ALRemoverLayers', 'inputs': {'images': ['1', 0], 'input_transparency': ['1', 1], 'foreground_mask': ['2', 0]}},
        '4': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0], 'filename_prefix': 'ALRemover-test/' + token + '-character'}},
        '5': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 1], 'filename_prefix': 'ALRemover-test/' + token + '-background'}},
    }
    started = time.perf_counter()
    baseline_history = run(graph)
    elapsed = time.perf_counter() - started
    fg, bg = saved(baseline_history, '4'), saved(baseline_history, '5')
    assert fg.mode == bg.mode == 'RGBA'
    assert fg.size == bg.size == source.size
    base = np.asarray(fg)
    np.testing.assert_array_equal(base[..., :3], pixels[..., :3])
    np.testing.assert_array_equal(np.asarray(bg)[..., :3], pixels[..., :3])
    np.testing.assert_array_equal(base[..., 3].astype(int) + np.asarray(bg)[..., 3], pixels[..., 3])
    fg.save(output / 'baseline-character.png')
    bg.save(output / 'baseline-background.png')
    assert 'prompt' in fg.info

    # Pick locations where both operations must make a visible change.
    green_candidates = np.argwhere((base[..., 3] < 64) & (pixels[..., 3] > 224))
    red_candidates = np.argwhere(base[..., 3] > 224)
    if not len(green_candidates) or not len(red_candidates):
        raise ValueError('Choose an image with both an opaque foreground and a removed background.')
    width, height = source.size
    strokes = []
    for candidates in (green_candidates, red_candidates):
        y, x = candidates[len(candidates) // 2]
        stroke = Image.new('L', source.size, 0)
        ImageDraw.Draw(stroke).rectangle((int(x), int(y), min(width-1, int(x)+5), min(height-1, int(y)+5)), fill=255)
        strokes.append(stroke)
    for node_id, stroke, label in zip(('6', '7'), strokes, ('keep', 'erase')):
        edited_source = source.convert('RGB').convert('RGBA')
        edited_source.putalpha(Image.fromarray(255 - np.asarray(stroke)))
        image_name = upload(edited_source, 'alremover-' + label + '-' + token + '.png')
        graph[node_id] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
    graph['8'] = {'class_type': 'ALRemoverCorrectMask', 'inputs': {
        'foreground_mask': ['2', 0], 'enabled': True, 'keep': ['6', 1], 'erase': ['7', 1]}}
    graph['3']['inputs']['foreground_mask'] = ['8', 0]
    corrected_history = run(graph)
    corrected_fg, corrected_bg = saved(corrected_history, '4'), saved(corrected_history, '5')
    corrected = np.asarray(corrected_fg)
    changed = (np.asarray(strokes[0]) > 0) | (np.asarray(strokes[1]) > 0)
    np.testing.assert_array_equal(corrected[~changed], base[~changed])
    np.testing.assert_array_equal(corrected[..., :3], pixels[..., :3])
    np.testing.assert_array_equal(corrected[..., 3].astype(int) + np.asarray(corrected_bg)[..., 3], pixels[..., 3])
    assert np.any(corrected[..., 3] > base[..., 3])
    assert np.any(corrected[..., 3] < base[..., 3])
    cached = {node for kind, data in corrected_history['status']['messages'] if kind == 'execution_cached' for node in data['nodes']}
    assert '2' in cached, 'Correction unexpectedly reran extraction.'
    corrected_fg.save(output / 'corrected-character.png')
    graph['8']['inputs']['enabled'] = False
    reset_history = run(graph)
    np.testing.assert_array_equal(np.asarray(saved(reset_history, '4')), base)
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == original_hash
    report = {'mode': mode, 'first_extract_seconds': round(elapsed, 3), 'input_size': list(source.size),
              'original_rgb_exact': True, 'alpha_partition_exact': True, 'rgba_saved': True,
              'keep_erase_changes_verified': True, 'unpainted_pixels_unchanged': True,
              'correction_reuses_extraction_cache': True, 'disable_correction_restores_base': True,
              'source_file_unchanged': True, 'comfy_prompt_metadata': True}
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--mode', default='BEN2')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'test-results/comfyui')
    args = parser.parse_args()
    verify(args.url.rstrip('/'), args.image, args.output, args.mode)
