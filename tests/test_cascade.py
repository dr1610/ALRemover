import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alr_neo import engine


class CascadeTests(unittest.TestCase):
    def test_reverse_uses_ben2_mask_before_toonout(self):
        source = Image.new("RGB", (3, 1), (255, 0, 0))
        first = Image.frombytes("L", (3, 1), bytes([128, 0, 255]))
        second = Image.frombytes("L", (3, 1), bytes([128, 255, 255]))
        calls = []

        def infer(name, image, *args):
            calls.append((name, image.copy()))
            return first if len(calls) == 1 else second

        with patch.object(engine, "_infer", side_effect=infer), patch.object(engine, "preserve_runtime", nullcontext):
            result = engine.extract(source, "BEN2 → ToonOut（灰色背景）")
        self.assertEqual([name for name, _ in calls], ["ben2", "toonout"])
        self.assertEqual(calls[0][1].tobytes(), source.tobytes())
        self.assertEqual(calls[1][1].getpixel((0, 0)), (192, 64, 64))
        self.assertEqual(calls[1][1].getpixel((1, 0)), (128, 128, 128))
        self.assertEqual(calls[1][1].getpixel((2, 0)), (255, 0, 0))
        self.assertEqual(result.tobytes(), bytes([64, 0, 255]))

    def test_forward_still_uses_original_order(self):
        with patch.object(engine, "_infer", return_value=Image.new("L", (1, 1), 255)) as infer, \
             patch.object(engine, "preserve_runtime", nullcontext):
            engine.extract(Image.new("RGB", (1, 1)), "ToonOut → BEN2（灰色背景）")
        self.assertEqual([call.args[0] for call in infer.call_args_list], ["toonout", "ben2"])

    def test_default_runs_ben2_once(self):
        with patch.object(engine, "_infer", return_value=Image.new("L", (1, 1), 255)) as infer, \
             patch.object(engine, "preserve_runtime", nullcontext):
            engine.extract(Image.new("RGB", (1, 1)))
        self.assertEqual([call.args[0] for call in infer.call_args_list], ["ben2"])


if __name__ == "__main__":
    unittest.main()
