import sys
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alr_neo.layers import layers, multiply_alpha, paint_mask, adjust_mask


class LayerTests(unittest.TestCase):
    def test_rgb_unchanged_and_existing_alpha_partitioned(self):
        pixels = np.array([[[21, 44, 199, 255], [255, 242, 221, 127], [40, 90, 12, 0]]], dtype=np.uint8)
        source = Image.fromarray(pixels)
        result = layers(source, Image.fromarray(np.array([[0, 128, 255]], dtype=np.uint8)))
        fg, bg = np.asarray(result["キャラクター"]), np.asarray(result["背景"])
        np.testing.assert_array_equal(fg[..., :3], pixels[..., :3])
        np.testing.assert_array_equal(bg[..., :3], pixels[..., :3])
        np.testing.assert_array_equal(fg[..., 3].astype(int) + bg[..., 3], pixels[..., 3])
        self.assertEqual(fg[0, 2, 3], 0)

    def test_alpha_endpoints_and_rounding(self):
        a = Image.fromarray(np.array([[255, 255, 127, 0]], dtype=np.uint8))
        b = Image.fromarray(np.array([[255, 0, 127, 255]], dtype=np.uint8))
        self.assertEqual(list(multiply_alpha(a, b).getdata()), [255, 0, 63, 0])

    def test_correction_preserves_unpainted_and_eraser_restores_base(self):
        base = Image.new("L", (4, 1), 128)
        strokes = Image.fromarray(np.array([[
            [0, 255, 0, 255], [255, 0, 0, 255], [0, 255, 0, 0], [0, 255, 0, 128]]], dtype=np.uint8))
        self.assertEqual(list(paint_mask(base, {"layers": [strokes]}).getdata()), [255, 0, 128, 192])
        self.assertEqual(list(paint_mask(base, {"layers": []}).getdata()), [128] * 4)
        self.assertEqual(list(base.getdata()), [128] * 4)

    def test_last_stroke_wins(self):
        base = Image.new("L", (1, 1), 100)
        green = Image.new("RGBA", (1, 1), (0, 255, 0, 255))
        red = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        self.assertEqual(paint_mask(base, {"layers": [green, red]}).getpixel((0, 0)), 0)

    def test_reject_size_mismatch(self):
        with self.assertRaises(ValueError):
            paint_mask(Image.new("L", (1, 1)), {"layers": [Image.new("RGBA", (2, 2))]})
        with self.assertRaises(ValueError):
            layers(Image.new("RGB", (1, 1)), Image.new("L", (2, 2)))

    def test_no_default_blur_and_optional_expand(self):
        base = Image.new("L", (5, 5))
        base.putpixel((2, 2), 255)
        self.assertEqual(adjust_mask(base).tobytes(), base.tobytes())
        self.assertEqual(np.asarray(adjust_mask(base, 1)).sum(), 255 * 9)
        self.assertEqual(np.asarray(adjust_mask(base, -1)).sum(), 0)


if __name__ == "__main__":
    unittest.main()
