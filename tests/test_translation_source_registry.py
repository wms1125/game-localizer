from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "translation-sources.json"


class TranslationSourceRegistryTests(unittest.TestCase):
    def test_registry_is_machine_readable_and_keeps_provenance_only(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual(registry["registry_id"], "hanengine-translation-sources-v1")
        self.assertGreaterEqual(len(registry["sources"]), 1)

        forbidden_keys = {"source_text", "target_text", "entries", "dictionary"}
        for source in registry["sources"]:
            with self.subTest(source=source["id"]):
                self.assertNotIn(source["authority_tier"], {"translation-quality", "certified"})
                self.assertRegex(source["source"]["upstream_reference"], r"^[0-9a-f]{7,40}$")
                self.assertRegex(source["source"]["license_file_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(source["source"]["release_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(source["local_artifact"]["source_tree_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(source["source"]["release_url"].startswith("https://"))
                self.assertTrue(source["source"]["upstream_repository"].startswith("https://"))
                self.assertTrue(source["use_for"])
                self.assertTrue(source["do_not_use_for"])
                self.assertTrue(forbidden_keys.isdisjoint(source))
                for relative_path, digest in source["local_artifact"]["translation_files"].items():
                    self.assertFalse(Path(relative_path).is_absolute())
                    self.assertNotIn("..", Path(relative_path).parts)
                    if digest is not None:
                        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_policy_explicitly_separates_provenance_from_quality(self):
        policy = (ROOT / "docs" / "translation-source-policy.md").read_text(encoding="utf-8")
        self.assertIn("不是**中文翻译质量认证", policy)
        self.assertIn("只登记来源和哈希", policy)
        self.assertIn("机械占位符字典", policy)
        self.assertIsNotNone(re.search(r"8\.5\.3\.26051504.*3baa108", policy))


if __name__ == "__main__":
    unittest.main()
