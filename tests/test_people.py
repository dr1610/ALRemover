import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alr_neo import people as P


def sample():
    source = Image.new("RGBA", (40, 20), (232, 198, 139, 255))
    source.putpixel((0, 0), (232, 198, 139, 0))
    base = Image.new("L", source.size, 191)
    state = P.create(source, base, "BEN2")
    a, b = P.add_person(state), P.add_person(state)
    left = np.zeros((20, 40), np.uint8)
    left[:, :23] = 220
    right = np.zeros_like(left)
    right[:, 19:] = 240
    a["mask"], b["mask"] = Image.fromarray(left), Image.fromarray(right)
    return state


class PeopleTests(unittest.TestCase):
    def test_shared_boundary_exclusive_and_outer_alpha_preserved(self):
        state = sample()
        owners, base, layers = P.alpha_layers(state)
        self.assertEqual(layers[1][10, 8], 191)  # never 191 * SAM confidence
        self.assertEqual(layers[2][10, 21], 191)
        self.assertEqual(layers[1][10, 21], 0)
        total = sum(a.astype(int) for a in layers.values()) + np.where(owners == 0, base, 0)
        np.testing.assert_array_equal(total, base)
        self.assertEqual(base[0, 0], 0)

    def test_unassigned_is_preserved_when_no_people_detected(self):
        state = sample()
        state["persons"] = []
        owners, base, assigned = P.alpha_layers(state)
        self.assertFalse(owners.any())
        self.assertEqual(assigned, {})
        self.assertEqual(base[10, 10], 191)

    def test_manual_arm_assignment_overrides_other_person(self):
        state = sample()
        layer = Image.new("RGBA", state["source"].size)
        layer.putpixel((25, 10), (*bytes.fromhex(P.COLORS[0][1:]), 255))
        P.apply_brush(state, {"layers": [layer]})
        self.assertEqual(P.ownership(state)[10, 25], 1)
        self.assertEqual(P.ownership(state)[10, 26], 2)

    def test_white_brush_marks_unassigned_without_deleting_matte(self):
        state = sample()
        layer = Image.new("RGBA", state["source"].size)
        layer.putpixel((10, 10), (255, 255, 255, 255))
        P.apply_brush(state, {"layers": [layer]})
        owners, base, _ = P.alpha_layers(state)
        self.assertEqual(owners[10, 10], 0)
        self.assertEqual(base[10, 10], 191)

    def test_unknown_person_color_rejected(self):
        state = sample()
        layer = Image.new("RGBA", state["source"].size, (*bytes.fromhex(P.COLORS[2][1:]), 255))
        with self.assertRaises(ValueError):
            P.apply_brush(state, {"layers": [layer]})

    def test_black_brush_removes_background_spill_and_undo_restores_alpha(self):
        before = sample()
        state = P.remember(before)
        layer = Image.new("RGBA", state["source"].size)
        layer.putpixel((10, 10), (0, 0, 0, 255))
        P.apply_brush(state, {"layers": [layer]})
        self.assertEqual(P.alpha_layers(state)[1][10, 10], 0)
        restored = P.undo(state)
        np.testing.assert_array_equal(restored["mask"], before["mask"])
        np.testing.assert_array_equal(P.ownership(restored), P.ownership(before))

    def test_optional_brush_restore_repairs_missing_foreground_without_changing_rgb(self):
        state = sample()
        state["mask"].putpixel((25, 10), 0)
        layer = Image.new("RGBA", state["source"].size)
        layer.putpixel((25, 10), (*bytes.fromhex(P.COLORS[0][1:]), 255))
        layer.putpixel((0, 0), (*bytes.fromhex(P.COLORS[0][1:]), 255))
        P.apply_brush(state, {"layers": [layer]}, restore=True)
        owners, base, layers = P.alpha_layers(state)
        self.assertEqual(owners[10, 25], 1)
        self.assertEqual(base[10, 25], 255)
        self.assertEqual(base[0, 0], 0)  # original source transparency is still respected
        np.testing.assert_array_equal(np.asarray(P.rgba(state["source"], layers[1]))[..., :3],
                                      np.asarray(state["source"])[..., :3])

    def test_undo_restores_masks_settings_and_assignments(self):
        before = sample()
        after = P.remember(before)
        after["persons"][0]["opacity"] = 20
        after["persons"][0]["mask"] = Image.new("L", (40, 20))
        after["forced"][5, 5] = 2
        restored = P.undo(after)
        self.assertEqual(restored["persons"][0]["opacity"], 100)
        np.testing.assert_array_equal(P.ownership(restored), P.ownership(before))
        self.assertEqual(before["forced"][5, 5], -1)

    def test_export_selection_opacity_and_remaining_image(self):
        state = sample()
        state["persons"][0]["opacity"] = 50
        with tempfile.TemporaryDirectory() as d:
            paths = P.export(state, [1], ["人物PNG", "人物マスク", "背景", "未割当", "選択人物を除いた画像"], d)
            self.assertFalse(any("person-B" in path for path in paths))
            with Image.open(next(path for path in paths if "person-A.png" in path)) as fg, \
                 Image.open(next(path for path in paths if "without-selected.png" in path)) as rest:
                a, b = np.asarray(fg), np.asarray(rest)
                self.assertEqual(a[10, 8, 3], 96)
                np.testing.assert_array_equal(a[..., 3].astype(int) + b[..., 3], np.asarray(state["source"])[..., 3])
                np.testing.assert_array_equal(a[..., :3], np.asarray(state["source"])[..., :3])

    def test_project_roundtrip_exact(self):
        state = sample()
        state["persons"][0].update(name="主人公", points=[(8, 10, 1)], opacity=83, visible=False)
        state["forced"][8, 28] = 1
        with tempfile.TemporaryDirectory() as d:
            loaded = P.load_project(P.save_project(state, d))
        np.testing.assert_array_equal(loaded["source"], state["source"])
        np.testing.assert_array_equal(P.ownership(loaded), P.ownership(state))
        self.assertEqual(loaded["persons"][0]["name"], "主人公")
        self.assertEqual(loaded["persons"][0]["opacity"], 83)
        self.assertFalse(loaded["persons"][0]["visible"])


if __name__ == "__main__":
    unittest.main()
