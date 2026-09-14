import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image
import torch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alremover_comfy_tests", ROOT / "__init__.py",
                                           submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
nodes = sys.modules[spec.name + ".comfy_nodes"]
from alremover_comfy_tests.alr_neo.layers import layers


class ComfyNodeTests(unittest.TestCase):
    def test_rgba_matches_neo_and_preserves_rgb(self):
        source = np.array([[[20, 40, 190, 255], [240, 229, 15, 127], [60, 80, 12, 0]]], dtype=np.uint8)
        mask = np.array([[128, 128, 255]], dtype=np.uint8)
        image = torch.from_numpy(source.astype(np.float32) / 255).unsqueeze(0)
        fg, bg, alpha = nodes.ALRemoverLayers().make_layers(image, torch.from_numpy(mask / 255))
        expected = layers(Image.fromarray(source), Image.fromarray(mask))
        np.testing.assert_array_equal(torch.round(fg[0] * 255).numpy(), np.asarray(expected['キャラクター']))
        np.testing.assert_array_equal(torch.round(bg[0] * 255).numpy(), np.asarray(expected['背景']))
        torch.testing.assert_close(fg[..., :3], image[..., :3], rtol=0, atol=0)
        torch.testing.assert_close(alpha, fg[..., 3], rtol=0, atol=0)

    def test_load_image_mask_is_inverse_alpha_and_applied_once(self):
        image = torch.full((1, 3, 2, 3), 0.6)
        transparency = torch.full((1, 3, 2), 128 / 255)
        fg, bg, _ = nodes.ALRemoverLayers().make_layers(image, torch.ones((1, 3, 2)), transparency)
        torch.testing.assert_close(fg[..., 3], 1 - transparency)
        self.assertEqual(bg[..., 3].count_nonzero(), 0)

    def test_load_image_without_alpha_has_zero_64_square_mask(self):
        image = torch.zeros((2, 100, 90, 3))
        fg, bg, _ = nodes.ALRemoverLayers().make_layers(image, torch.ones((1, 100, 90)), torch.zeros((1, 64, 64)))
        self.assertEqual(fg.shape, (2, 100, 90, 4))
        self.assertTrue(torch.all(fg[..., 3] == 1))
        self.assertTrue(torch.all(bg[..., 3] == 0))

    def test_soft_corrections_are_local_and_do_not_modify_base(self):
        base = torch.tensor([[[0.2, 0.3, 0.4, 0.5]]])
        original = base.clone()
        keep = torch.tensor([[0., 1., 0.5, 0.]])
        erase = torch.tensor([[0., 1., 0., 0.5]])
        result, = nodes.ALRemoverCorrectMask().correct(base, keep=keep, erase=erase)
        torch.testing.assert_close(result, torch.tensor([[[0.2, 0., 0.7, 0.25]]]))
        torch.testing.assert_close(base, original, rtol=0, atol=0)
        reset, = nodes.ALRemoverCorrectMask().correct(base)
        torch.testing.assert_close(reset, original, rtol=0, atol=0)
        disabled, = nodes.ALRemoverCorrectMask().correct(base, enabled=False, keep=keep, erase=erase)
        torch.testing.assert_close(disabled, original, rtol=0, atol=0)

    def test_batch_masks_are_independent(self):
        image = torch.rand((2, 2, 3, 3))
        mask = torch.stack((torch.zeros((2, 3)), torch.ones((2, 3))))
        fg, bg, _ = nodes.ALRemoverLayers().make_layers(image, mask)
        torch.testing.assert_close(fg[..., :3], image, rtol=0, atol=0)
        self.assertTrue(torch.all(fg[0, ..., 3] == 0))
        self.assertTrue(torch.all(fg[1, ..., 3] == 1))
        self.assertTrue(torch.all(bg[0, ..., 3] == 1))

    def test_wrong_mask_size_cannot_silently_shift_corrections(self):
        with self.assertRaisesRegex(ValueError, 'same width'):
            nodes.ALRemoverCorrectMask().correct(torch.zeros((1, 100, 90)), keep=torch.ones((1, 64, 64)))
        with self.assertRaisesRegex(ValueError, 'batch sizes'):
            nodes.ALRemoverLayers().make_layers(torch.zeros((2, 10, 10, 3)), torch.zeros((3, 10, 10)))


if __name__ == '__main__':
    unittest.main()
