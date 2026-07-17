import sys
import unittest
from pathlib import Path


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

import source_visualization


class SourceVisualizationConfigurationTests(unittest.TestCase):
    def test_missing_visualization_config_uses_peak_selection(self):
        self.assertEqual(
            source_visualization._source_visualization_selections({}),
            [{"mode": "peak"}],
        )

    def test_defaults_are_merged_and_numeric_vertex_is_not_exposed(self):
        selections = source_visualization._source_visualization_selections(
            {
                "visualization": {
                    "time": 0.12,
                    "hemis": "left",
                    "vertex": 42,
                    "selections": [{"name": "auditory", "roi": "auditory"}],
                }
            }
        )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]["mode"], "label")
        self.assertEqual(selections[0]["time"], 0.12)
        self.assertEqual(selections[0]["hemis"], "left")
        self.assertNotIn("vertex", selections[0])

    def test_hemisphere_aliases_have_stable_order(self):
        self.assertEqual(
            source_visualization._normalize_hemi_list(["right", "left"]),
            ["lh", "rh"],
        )

    def test_surface_view_is_inferred_from_anatomical_label(self):
        self.assertEqual(source_visualization._default_surface_view("fusiform-lh"), "ventral")
        self.assertEqual(source_visualization._default_surface_view("precuneus-rh"), "medial")
        self.assertEqual(source_visualization._default_surface_view("postcentral-lh"), "lateral")

    def test_output_slug_is_filesystem_safe(self):
        self.assertEqual(
            source_visualization._safe_slug(" Auditory ROI / 120 ms "),
            "Auditory_ROI_120_ms",
        )


if __name__ == "__main__":
    unittest.main()
