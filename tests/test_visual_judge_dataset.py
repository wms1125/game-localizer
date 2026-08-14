from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.benchmark_visual_judges import load_dataset
from tools.generate_visual_judge_dataset import CATEGORIES, CHROME_TEXT, build_dataset


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "visual_judge_controlled"


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ControlledVisualJudgeDatasetTests(unittest.TestCase):
    def test_candidate_chrome_has_localized_title_and_slot_label(self):
        self.assertEqual(CHROME_TEXT["zh"]["title"], "月光档案")
        self.assertEqual(CHROME_TEXT["zh"]["slot"], "存档")
        self.assertNotEqual(CHROME_TEXT["zh"]["title"], CHROME_TEXT["en"]["title"])
        self.assertNotEqual(CHROME_TEXT["zh"]["slot"], CHROME_TEXT["en"]["slot"])

    def test_manifest_has_36_balanced_scenes_and_valid_images(self):
        payload = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "hanengine.visual-judge-benchmark/v1")
        self.assertEqual(payload["dataset"]["sample_count"], 36)
        self.assertEqual(payload["dataset"]["category_count"], 9)
        self.assertEqual(len(payload["samples"]), 36)
        self.assertEqual(sum(not item["expected_defect"] for item in payload["samples"]), 4)
        for category, issue_code in CATEGORIES:
            scenes = [item for item in payload["samples"] if item["sample_id"].startswith(f"{category}-")]
            self.assertEqual(len(scenes), 4)
            for scene in scenes:
                self.assertEqual(scene["expected_issue_codes"], [] if issue_code is None else [issue_code])
                for key in ("reference_image", "candidate_image"):
                    with Image.open(DATASET / scene[key]) as image:
                        self.assertEqual(image.size, (960, 540))
                        self.assertEqual(image.mode, "RGB")

    def test_dataset_is_accepted_by_the_benchmark_runner(self):
        samples = load_dataset(DATASET / "manifest.json")
        self.assertEqual(len(samples), 36)
        self.assertEqual(sum(sample.expected_defect for sample in samples), 32)

    def test_generation_is_byte_deterministic(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            build_dataset(Path(first))
            build_dataset(Path(second))
            self.assertEqual(_snapshot(Path(first)), _snapshot(Path(second)))

    def test_committed_dataset_matches_generator(self):
        with TemporaryDirectory() as directory:
            generated = Path(directory)
            build_dataset(generated)
            self.assertEqual(_snapshot(generated), _snapshot(DATASET))


if __name__ == "__main__":
    unittest.main()
