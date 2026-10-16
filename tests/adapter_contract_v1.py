from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


def snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    items = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        items.append(
            (
                relative,
                "dir" if path.is_dir() else "file",
                None if path.is_dir() else path.read_bytes(),
            )
        )
    return tuple(items)


class AdapterV1ContractMixin(ABC):
    @abstractmethod
    def make_adapter(self):
        raise NotImplementedError

    @abstractmethod
    def make_detection_request(self):
        raise NotImplementedError

    @abstractmethod
    def make_unmatched_detection_request(self):
        raise NotImplementedError

    def test_contract_metadata_is_valid(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.metadata.contract_version, "hanengine.adapter/v1")
        self.assertTrue(adapter.metadata.adapter_id)
        self.assertTrue(adapter.metadata.capabilities)

    def test_detect_is_deterministic(self):
        adapter = self.make_adapter()
        request = self.make_detection_request()
        first = adapter.detect(request)
        second = adapter.detect(request)
        self.assertTrue(first.matched)
        self.assertEqual(first, second)

    def test_unmatched_detection_has_no_evidence(self):
        result = self.make_adapter().detect(self.make_unmatched_detection_request())
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence, ())
        self.assertIsNone(result.engine_name)
        self.assertIsNone(result.engine_version)

    def test_detect_does_not_modify_input_root(self):
        adapter = self.make_adapter()
        request = self.make_detection_request()
        before = snapshot_tree(request.input_root)
        adapter.detect(request)
        self.assertEqual(snapshot_tree(request.input_root), before)

    def test_recommended_operation_is_allowed_by_request(self):
        request = self.make_detection_request()
        result = self.make_adapter().detect(request)
        self.assertIn(result.recommended_operation, request.allowed_operations)
