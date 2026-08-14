from __future__ import annotations

import dataclasses
import math
import os
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

import game_localizer.adapters.contract as contract
from game_localizer.adapters.contract import (
    AdapterCapability,
    AdapterError,
    AdapterErrorCode,
    AdapterMaturity,
    AdapterMetadata,
    AdapterV1,
    ArtifactKind,
    BuildManifestEntry,
    BuildRequest,
    BuildResult,
    DeclaredMode,
    DetectionRequest,
    DetectionResult,
    Evidence,
    EvidenceSource,
    ExtractRequest,
    ExtractResult,
    IssueSeverity,
    Operation,
    RollbackRequest,
    RollbackResult,
    ValidationIssue,
    ValidationRequest,
    ValidationResult,
    VerificationCheck,
    VerifyRequest,
    VerifyResult,
    adapter_operations_for_route,
)
from game_localizer.hanengine.routing import (
    EvaluationStatus,
    RiskLevel,
    RouteOperation,
    RoutePhase,
    RoutePlan,
)
from game_localizer.hanengine.segments import Segment, SegmentDraft, SourceLocation
from game_localizer.hanengine.tasks import (
    Artifact,
    ArtifactKind as TaskArtifactKind,
    EventType,
    StepResult,
    TaskContext,
    TaskControl,
    TaskPlan,
    TaskRunner,
    TaskState,
    TaskStep,
)
from tests.adapter_contract_v1 import AdapterV1ContractMixin, snapshot_tree


ALL_ROUTE_OPERATIONS = frozenset(RouteOperation)


def make_context() -> TaskContext:
    return TaskContext(
        "task-contract",
        "detect",
        TaskControl(),
        lambda *args: None,
    )


def make_metadata(**changes: object) -> AdapterMetadata:
    values: dict[str, object] = {
        "adapter_id": "hanengine.synthetic",
        "contract_version": "hanengine.adapter/v1",
        "adapter_version": "1.2.3",
        "engine_name": "Synthetic Engine",
        "supported_engine_versions": ("1.x",),
        "capabilities": frozenset({AdapterCapability.DETECT}),
        "maturity": AdapterMaturity.DETECT_ONLY,
        "platforms": ("windows",),
        "known_limitations": ("test-only",),
    }
    values.update(changes)
    return AdapterMetadata(**values)


def make_evidence(**changes: object) -> Evidence:
    values: dict[str, object] = {
        "code": "synthetic_marker",
        "source": EvidenceSource.ENGINE_MARKER,
        "value": "matched.marker",
        "weight": 0.9,
        "description": "Synthetic marker found",
    }
    values.update(changes)
    return Evidence(**values)


def make_draft(relative_path: str = "game/script.rpy") -> SegmentDraft:
    return SegmentDraft(
        segment_id="segment-1",
        source_text="Hello",
        source_language="en",
        speaker=None,
        context_before=(),
        context_after=(),
        placeholders=(),
        tags=(),
        constraints=(),
        source_location=SourceLocation(relative_path=relative_path),
        source_fingerprint="source-fingerprint",
        ocr_confidence=None,
        region_confidence=None,
    )


def make_segment(relative_path: str = "game/script.rpy") -> Segment:
    return Segment.from_draft("project-a", "zh-Hans", make_draft(relative_path))


def make_manifest(relative_path: str = "output/game.dat") -> BuildManifestEntry:
    return BuildManifestEntry(relative_path, "modified", "abc123")


def make_issue(**changes: object) -> ValidationIssue:
    values: dict[str, object] = {
        "code": "placeholder_mismatch",
        "severity": IssueSeverity.ERROR,
        "segment_id": "segment-1",
        "source_location": SourceLocation(relative_path="game/script.rpy"),
        "message": "Placeholder mismatch",
        "automatically_recoverable": False,
        "suggested_action": "Restore the placeholder",
    }
    values.update(changes)
    return ValidationIssue(**values)


def make_artifact() -> Artifact:
    return Artifact(
        artifact_id="artifact-1",
        task_id="task-contract",
        step_id="build",
        kind=ArtifactKind.PATCH,
        relative_path="output/patch.zip",
        sha256="abc123",
    )


class FakeAdapter:
    metadata = make_metadata()

    @staticmethod
    def _unavailable(operation: Operation) -> AdapterError:
        return AdapterError(
            code=AdapterErrorCode.UNSUPPORTED_INPUT,
            operation=operation,
            message="Operation is unavailable for this detect-only adapter",
            recoverable=False,
            details={"adapter": "synthetic"},
        )

    def detect(self, request: DetectionRequest) -> DetectionResult | AdapterError:
        request.context.progress(1, 1, current_item="matched.marker")
        request.context.log("synthetic detection completed", {"matched": True})
        matched = (request.input_root / "matched.marker").is_file()
        return DetectionResult(
            matched=matched,
            engine_name="Synthetic Engine" if matched else None,
            engine_version="1.0.0" if matched else None,
            confidence=0.9 if matched else 0.0,
            evidence=(make_evidence(),) if matched else (),
            maturity=self.metadata.maturity,
            capabilities=self.metadata.capabilities,
            limitations=self.metadata.known_limitations,
            recommended_operation=Operation.DETECT,
        )

    def extract(self, request: ExtractRequest) -> ExtractResult | AdapterError:
        return self._unavailable(Operation.EXTRACT)

    def validate(self, request: ValidationRequest) -> ValidationResult | AdapterError:
        return self._unavailable(Operation.VALIDATE)

    def build(self, request: BuildRequest) -> BuildResult | AdapterError:
        return self._unavailable(Operation.BUILD)

    def verify(self, request: VerifyRequest) -> VerifyResult | AdapterError:
        return self._unavailable(Operation.VERIFY)

    def rollback(self, request: RollbackRequest) -> RollbackResult | AdapterError:
        return self._unavailable(Operation.ROLLBACK)


class EnumAndSchemaTests(unittest.TestCase):
    def test_enum_values_are_exact(self):
        expected = {
            AdapterMaturity: ["detect_only", "extract_ready", "build_ready", "verified"],
            AdapterCapability: ["detect", "extract", "validate", "build", "verify", "rollback"],
            Operation: ["detect", "extract", "validate", "build", "verify", "rollback"],
            IssueSeverity: ["info", "warning", "error", "critical"],
            EvidenceSource: [
                "filesystem",
                "project_manifest",
                "engine_marker",
                "user_declaration",
                "hanguard_signal",
            ],
            DeclaredMode: ["player", "studio"],
            AdapterErrorCode: [
                "UNSUPPORTED_INPUT",
                "ENGINE_NOT_DETECTED",
                "UNSUPPORTED_VERSION",
                "RISK_POLICY_BLOCKED",
                "READ_FAILED",
                "DECODE_FAILED",
                "PARSE_FAILED",
                "EXTRACT_PARTIAL",
                "VALIDATION_FAILED",
                "STAGING_ESCAPE_BLOCKED",
                "BUILD_FAILED",
                "VERIFY_FAILED",
                "BACKUP_FAILED",
                "ROLLBACK_FAILED",
                "CANCELLED",
                "INTERNAL_ERROR",
            ],
        }
        for enum_type, values in expected.items():
            with self.subTest(enum_type=enum_type.__name__):
                self.assertEqual([item.value for item in enum_type], values)

    def test_artifact_kind_is_the_canonical_task_enum(self):
        self.assertIs(ArtifactKind, TaskArtifactKind)
        self.assertIs(contract.ArtifactKind, TaskArtifactKind)

    def test_dataclass_fields_are_exact(self):
        expected = {
            AdapterMetadata: ("adapter_id", "contract_version", "adapter_version", "engine_name", "supported_engine_versions", "capabilities", "maturity", "platforms", "known_limitations"),
            Evidence: ("code", "source", "value", "weight", "description"),
            AdapterError: ("code", "operation", "message", "recoverable", "segment_id", "relative_path", "evidence", "details", "cause_type"),
            DetectionRequest: ("input_root", "declared_mode", "project_id", "risk_level", "allowed_operations", "context"),
            DetectionResult: ("matched", "engine_name", "engine_version", "confidence", "evidence", "maturity", "capabilities", "limitations", "recommended_operation"),
            ExtractRequest: ("source_root", "working_root", "candidate_encodings", "filters", "project_id", "context"),
            ExtractResult: ("segments", "source_tree_fingerprint", "read_files", "skipped_files", "warnings", "statistics"),
            ValidationIssue: ("code", "severity", "segment_id", "source_location", "message", "automatically_recoverable", "suggested_action"),
            ValidationRequest: ("source_tree_fingerprint", "original_segments", "translated_segments", "target_encoding", "project_rules", "context"),
            ValidationResult: ("valid", "issues", "automatic_fixes", "blocking_issue_count", "warning_count"),
            BuildRequest: ("source_root", "staging_root", "validated_segments", "source_tree_fingerprint", "output_options", "context"),
            BuildManifestEntry: ("relative_path", "change_kind", "sha256"),
            BuildResult: ("generated_files", "added_files", "modified_files", "deleted_files", "manifest", "artifacts", "candidate_fingerprint", "warnings", "statistics"),
            VerifyRequest: ("source_tree_fingerprint", "staging_root", "manifest", "verification_level", "context"),
            VerificationCheck: ("code", "passed", "message"),
            VerifyResult: ("passed", "checks", "syntax_passed", "encoding_passed", "artifact_hashes", "smoke_test_passed", "issues"),
            RollbackRequest: ("project_id", "install_manifest", "backup_manifest", "target_root", "expected_original_hashes", "context"),
            RollbackResult: ("restored_files", "unchanged_files", "failed_files", "hash_verification_passed", "issues"),
        }
        for model, fields in expected.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(tuple(field.name for field in dataclasses.fields(model)), fields)

    def test_requests_only_expose_runner_created_task_context(self):
        request_types = (
            DetectionRequest,
            ExtractRequest,
            ValidationRequest,
            BuildRequest,
            VerifyRequest,
            RollbackRequest,
        )
        for request_type in request_types:
            with self.subTest(request_type=request_type.__name__):
                names = {field.name for field in dataclasses.fields(request_type)}
                self.assertIn("context", names)
                self.assertTrue({"event_sink", "cancellation_token"}.isdisjoint(names))


class MetadataAndEvidenceTests(unittest.TestCase):
    def test_metadata_normalizes_ordered_fields_and_is_frozen(self):
        versions = ["1.x"]
        platforms = ["windows"]
        limitations = ["detect-only"]
        metadata = make_metadata(
            supported_engine_versions=versions,
            platforms=platforms,
            known_limitations=limitations,
        )
        versions.append("2.x")
        platforms.append("linux")
        limitations.append("mutated")
        self.assertEqual(metadata.supported_engine_versions, ("1.x",))
        self.assertEqual(metadata.platforms, ("windows",))
        self.assertEqual(metadata.known_limitations, ("detect-only",))
        with self.assertRaises(FrozenInstanceError):
            metadata.adapter_id = "other"

    def test_metadata_requires_exact_contract_id_reverse_domain_id_and_semver(self):
        invalid_changes = (
            {"contract_version": "hanengine.adapter/v2"},
            {"adapter_id": "hanengine"},
            {"adapter_id": "HanEngine.synthetic"},
            {"adapter_id": "hanengine.synthetic_adapter"},
            {"adapter_id": "hanengine..synthetic"},
            {"adapter_version": "1.2"},
            {"adapter_version": "v1.2.3"},
            {"adapter_version": "01.2.3"},
            {"adapter_version": "1.2.3.4"},
            {"adapter_version": "-1.2.3"},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_metadata(**changes)

    def test_metadata_requires_nonempty_ordered_versions_and_platforms(self):
        for changes in (
            {"engine_name": ""},
            {"supported_engine_versions": ()},
            {"supported_engine_versions": {"1.x"}},
            {"supported_engine_versions": ("",)},
            {"platforms": ()},
            {"platforms": {"windows"}},
            {"known_limitations": {"unordered"}},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_metadata(**changes)

    def test_maturity_capability_gates_are_cumulative(self):
        required = {
            AdapterMaturity.DETECT_ONLY: {AdapterCapability.DETECT},
            AdapterMaturity.EXTRACT_READY: {AdapterCapability.DETECT, AdapterCapability.EXTRACT},
            AdapterMaturity.BUILD_READY: {
                AdapterCapability.DETECT,
                AdapterCapability.EXTRACT,
                AdapterCapability.VALIDATE,
                AdapterCapability.BUILD,
                AdapterCapability.VERIFY,
            },
            AdapterMaturity.VERIFIED: set(AdapterCapability),
        }
        for maturity, capabilities in required.items():
            with self.subTest(maturity=maturity):
                metadata = make_metadata(maturity=maturity, capabilities=capabilities)
                self.assertEqual(metadata.capabilities, frozenset(capabilities))
                for missing in capabilities:
                    with self.subTest(maturity=maturity, missing=missing), self.assertRaises(ValueError):
                        make_metadata(maturity=maturity, capabilities=capabilities - {missing})
        with self.assertRaises(TypeError):
            make_metadata(capabilities={"detect"})
        with self.assertRaises(TypeError):
            make_metadata(maturity="detect_only")

    def test_evidence_requires_approved_source_finite_weight_and_audit_fields(self):
        for value in (0.0, 1.0, 0.5):
            self.assertEqual(make_evidence(weight=value).weight, float(value))
        for changes in (
            {"source": "filesystem"},
            {"weight": -0.01},
            {"weight": 1.01},
            {"weight": math.nan},
            {"weight": math.inf},
            {"weight": True},
            {"code": ""},
            {"value": ""},
            {"description": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                make_evidence(**changes)


class AdapterErrorTests(unittest.TestCase):
    def make_error(self, **changes: object) -> AdapterError:
        values: dict[str, object] = {
            "code": AdapterErrorCode.READ_FAILED,
            "operation": Operation.EXTRACT,
            "message": "Could not read the source file",
            "recoverable": True,
            "segment_id": None,
            "relative_path": "game\\script.rpy",
            "evidence": [make_evidence()],
            "details": {"attempt": 1, "nested": {"paths": ["game/script.rpy"]}},
            "cause_type": "PermissionError",
        }
        values.update(changes)
        return AdapterError(**values)

    def test_error_normalizes_path_evidence_and_snapshots_details(self):
        details = {"nested": {"items": [1]}}
        evidence = [make_evidence()]
        error = self.make_error(details=details, evidence=evidence)
        details["nested"]["items"].append(2)
        evidence.clear()
        self.assertEqual(error.relative_path, "game/script.rpy")
        self.assertEqual(error.evidence, (make_evidence(),))
        self.assertEqual(error.details, {"nested": {"items": [1]}})
        with self.assertRaises(FrozenInstanceError):
            error.message = "changed"

    def test_error_requires_exact_enums_bools_and_sanitized_strings(self):
        for changes in (
            {"code": "read_failed"},
            {"operation": "extract"},
            {"recoverable": 1},
            {"message": ""},
            {"message": "api_key=secret"},
            {"segment_id": ""},
            {"cause_type": "RuntimeError: token=secret"},
            {"evidence": {make_evidence()}},
            {"evidence": ("bad",)},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                self.make_error(**changes)

    def test_error_details_match_task_event_json_protection(self):
        invalid = (
            {"nested": [{"ToKeN": "secret"}]},
            {"bad": math.nan},
            {"bad": object()},
            {"bad": RuntimeError("raw")},
            {"bad": lambda: None},
            {1: "non-string key"},
            {"bad": ("not", "json")},
        )
        for details in invalid:
            with self.subTest(details=details), self.assertRaises((TypeError, ValueError)):
                self.make_error(details=details)

    def test_error_rejects_unsafe_relative_paths(self):
        for value in ("../escape", "C:\\escape", "/absolute", "safe\\mixed/path"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.make_error(relative_path=value)


class DetectionResultTests(unittest.TestCase):
    def make_result(self, **changes: object) -> DetectionResult:
        values: dict[str, object] = {
            "matched": True,
            "engine_name": "Synthetic Engine",
            "engine_version": "1.0.0",
            "confidence": 0.9,
            "evidence": [make_evidence()],
            "maturity": AdapterMaturity.DETECT_ONLY,
            "capabilities": {AdapterCapability.DETECT},
            "limitations": ["detect-only"],
            "recommended_operation": Operation.DETECT,
        }
        values.update(changes)
        return DetectionResult(**values)

    def test_matched_and_unmatched_invariants_are_exact(self):
        self.assertTrue(self.make_result().matched)
        unmatched = self.make_result(
            matched=False,
            engine_name=None,
            engine_version=None,
            confidence=0.0,
            evidence=(),
        )
        self.assertEqual(unmatched.evidence, ())
        invalid = (
            {"evidence": ()},
            {"engine_name": None},
            {"engine_version": None},
            {"matched": False, "engine_name": "Synthetic", "engine_version": None, "evidence": ()},
            {"matched": False, "engine_name": None, "engine_version": "1", "evidence": ()},
            {"matched": False, "engine_name": None, "engine_version": None, "evidence": (make_evidence(),)},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                self.make_result(**changes)

    def test_confidence_capabilities_and_recommendation_are_validated(self):
        for confidence in (-0.1, 1.1, math.nan, math.inf, True):
            with self.subTest(confidence=confidence), self.assertRaises((TypeError, ValueError)):
                self.make_result(confidence=confidence)
        for changes in (
            {"maturity": "detect_only"},
            {"capabilities": {"detect"}},
            {"capabilities": frozenset()},
            {"recommended_operation": "detect"},
            {"recommended_operation": Operation.BUILD},
            {
                "maturity": AdapterMaturity.VERIFIED,
                "capabilities": frozenset(AdapterCapability),
                "recommended_operation": Operation.BUILD,
            },
            {"limitations": {"unordered"}},
        ):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                self.make_result(**changes)


class RouteBridgeTests(unittest.TestCase):
    def make_route(self, allowed: frozenset[RouteOperation], *, provisional: bool = False) -> RoutePlan:
        return RoutePlan(
            project_id="project-a",
            phase=RoutePhase.PROVISIONAL if provisional else RoutePhase.FINAL,
            risk_before=RiskLevel.H0_PROJECT,
            risk_after=RiskLevel.H0_PROJECT,
            allowed_operations=allowed,
            blocked_operations=ALL_ROUTE_OPERATIONS - allowed,
            matches=(),
            evaluation_status=EvaluationStatus.COMPLETE,
            unknown_evidence=False,
            decision_reasons=("test route",),
        )

    def test_mapping_has_exact_six_enum_identity_pairs(self):
        expected = {
            RouteOperation.DETECT: Operation.DETECT,
            RouteOperation.EXTRACT: Operation.EXTRACT,
            RouteOperation.VALIDATE: Operation.VALIDATE,
            RouteOperation.BUILD: Operation.BUILD,
            RouteOperation.VERIFY: Operation.VERIFY,
            RouteOperation.ROLLBACK: Operation.ROLLBACK,
        }
        self.assertEqual(contract._ROUTE_TO_ADAPTER_OPERATION, expected)
        self.assertEqual(len(contract._ROUTE_TO_ADAPTER_OPERATION), 6)
        for route_operation, adapter_operation in contract._ROUTE_TO_ADAPTER_OPERATION.items():
            self.assertIsInstance(route_operation, RouteOperation)
            self.assertIsInstance(adapter_operation, Operation)

    def test_policy_only_operations_are_omitted(self):
        route = self.make_route(ALL_ROUTE_OPERATIONS)
        self.assertEqual(adapter_operations_for_route(route), frozenset(Operation))
        for operation in (
            RouteOperation.INSTALL_PATCH,
            RouteOperation.CAPTURE,
            RouteOperation.OCR,
            RouteOperation.VISUAL_REPLACE,
        ):
            self.assertNotIn(operation.value, {item.value for item in adapter_operations_for_route(route)})

    def test_provisional_route_maps_to_detect_only(self):
        route = self.make_route(frozenset({RouteOperation.DETECT}), provisional=True)
        self.assertEqual(adapter_operations_for_route(route), frozenset({Operation.DETECT}))
        with self.assertRaises(TypeError):
            adapter_operations_for_route(object())


class RequestValidationTests(unittest.TestCase):
    def test_detection_request_requires_resolved_root_and_exact_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = DetectionRequest(
                root,
                DeclaredMode.PLAYER,
                "project-a",
                RiskLevel.H0_PROJECT,
                {Operation.DETECT},
                make_context(),
            )
            self.assertEqual(request.allowed_operations, frozenset({Operation.DETECT}))
            for operations in (frozenset(), {Operation.DETECT, Operation.EXTRACT}, {"detect"}):
                with self.subTest(operations=operations), self.assertRaises((TypeError, ValueError)):
                    replace(request, allowed_operations=operations)
            for changes in (
                {"input_root": str(root)},
                {"input_root": root / "child" / ".."},
                {"declared_mode": "player"},
                {"project_id": ""},
                {"risk_level": 0},
                {"context": object()},
            ):
                with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                    replace(request, **changes)

    def test_source_working_and_source_staging_roots_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = (root / "source").resolve()
            work = (root / "work").resolve()
            staging = (root / "staging").resolve()
            source.mkdir()
            work.mkdir()
            staging.mkdir()
            ExtractRequest(source, work, ["utf-8"], ["*.rpy"], "project-a", make_context())
            BuildRequest(source, staging, [make_segment()], "fingerprint", {"mode": "safe"}, make_context())
            for first, second, builder in (
                (source, source, lambda a, b: ExtractRequest(a, b, (), (), "project-a", make_context())),
                (source, source / "nested", lambda a, b: ExtractRequest(a, b, (), (), "project-a", make_context())),
                (source / "nested", source, lambda a, b: ExtractRequest(a, b, (), (), "project-a", make_context())),
                (source, source, lambda a, b: BuildRequest(a, b, (), "fingerprint", {}, make_context())),
                (source, source / "nested", lambda a, b: BuildRequest(a, b, (), "fingerprint", {}, make_context())),
                (source / "nested", source, lambda a, b: BuildRequest(a, b, (), "fingerprint", {}, make_context())),
            ):
                with self.subTest(first=first, second=second, builder=builder), self.assertRaises(ValueError):
                    builder(first, second)

    def test_all_requests_require_the_exact_task_context_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            other = root / "other"
            source.mkdir()
            other.mkdir()
            requests = (
                DetectionRequest(source, DeclaredMode.PLAYER, "project", RiskLevel.H0_PROJECT, {Operation.DETECT}, make_context()),
                ExtractRequest(source, other, (), (), "project", make_context()),
                ValidationRequest("fp", (), (), "utf-8", {}, make_context()),
                BuildRequest(source, other, (), "fp", {}, make_context()),
                VerifyRequest("fp", other, (), "full", make_context()),
                RollbackRequest("project", (), (), source, {}, make_context()),
            )
            for request in requests:
                with self.subTest(request=type(request).__name__), self.assertRaises(TypeError):
                    replace(request, context=object())

    def test_every_request_root_requires_an_absolute_resolved_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            other = root / "other"
            source.mkdir()
            other.mkdir()
            cases = (
                (DetectionRequest(source, DeclaredMode.PLAYER, "project", RiskLevel.H0_PROJECT, {Operation.DETECT}, make_context()), "input_root"),
                (ExtractRequest(source, other, (), (), "project", make_context()), "source_root"),
                (ExtractRequest(source, other, (), (), "project", make_context()), "working_root"),
                (BuildRequest(source, other, (), "fp", {}, make_context()), "source_root"),
                (BuildRequest(source, other, (), "fp", {}, make_context()), "staging_root"),
                (VerifyRequest("fp", other, (), "full", make_context()), "staging_root"),
                (RollbackRequest("project", (), (), source, {}, make_context()), "target_root"),
            )
            for request, field_name in cases:
                with self.subTest(request=type(request).__name__, field=field_name):
                    with self.assertRaises((TypeError, ValueError)):
                        replace(request, **{field_name: "relative"})
                    unresolved = root / "child" / ".."
                    with self.assertRaises(ValueError):
                        replace(request, **{field_name: unresolved})

    def test_mocked_resolved_identity_rejects_aliases_platform_neutrally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            alias = root / "alias"
            with patch("game_localizer.adapters.contract._resolved_identity", return_value=root):
                with self.assertRaisesRegex(ValueError, "resolved"):
                    DetectionRequest(
                        alias,
                        DeclaredMode.PLAYER,
                        "project-a",
                        RiskLevel.H0_PROJECT,
                        {Operation.DETECT},
                        make_context(),
                    )

    def test_real_directory_alias_is_rejected_without_skipping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            alias = root / "alias"
            target.mkdir()
            if os.name == "nt":
                completed = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            else:
                alias.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "resolved"):
                DetectionRequest(
                    alias,
                    DeclaredMode.PLAYER,
                    "project-a",
                    RiskLevel.H0_PROJECT,
                    {Operation.DETECT},
                    make_context(),
                )

    def test_build_and_verify_reject_child_alias_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            staging = root / "staging"
            outside = root / "outside"
            source.mkdir()
            staging.mkdir()
            outside.mkdir()
            source_link = source / "linked"
            staging_link = staging / "linked"
            if os.name == "nt":
                for link in (source_link, staging_link):
                    completed = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            else:
                source_link.symlink_to(outside, target_is_directory=True)
                staging_link.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "escape"):
                BuildRequest(
                    source,
                    staging,
                    (make_segment("linked/text.txt"),),
                    "fingerprint",
                    {},
                    make_context(),
                )
            with self.assertRaisesRegex(ValueError, "escape"):
                VerifyRequest(
                    "fingerprint",
                    staging,
                    (make_manifest("linked/output.dat"),),
                    "full",
                    make_context(),
                )


class RecordNormalizationTests(unittest.TestCase):
    def test_requests_normalize_ordered_values_and_snapshot_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            working = root / "working"
            staging = root / "staging"
            target = root / "target"
            for item in (source, working, staging, target):
                item.mkdir()
            rules = {"nested": {"items": [1]}}
            options = {"nested": {"items": [1]}}
            hashes = {"game\\script.rpy": "abc"}
            extract = ExtractRequest(source, working, ["utf-8"], ["*.rpy"], "project-a", make_context())
            validation = ValidationRequest("fingerprint", [make_segment()], [make_segment()], "utf-8", rules, make_context())
            build = BuildRequest(source, staging, [make_segment()], "fingerprint", options, make_context())
            rollback = RollbackRequest("project-a", [make_manifest()], [make_manifest("backup/game.dat")], target, hashes, make_context())
            rules["nested"]["items"].append(2)
            options["nested"]["items"].append(2)
            hashes["other"] = "mutated"
            self.assertEqual(extract.candidate_encodings, ("utf-8",))
            self.assertEqual(extract.filters, ("*.rpy",))
            self.assertEqual(validation.original_segments, (make_segment(),))
            self.assertEqual(validation.project_rules, {"nested": {"items": [1]}})
            self.assertEqual(build.output_options, {"nested": {"items": [1]}})
            self.assertEqual(rollback.expected_original_hashes, {"game/script.rpy": "abc"})

    def test_ordered_request_fields_reject_unordered_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            other = root / "other"
            source.mkdir()
            other.mkdir()
            builders = (
                lambda: ExtractRequest(source, other, {"utf-8"}, (), "project", make_context()),
                lambda: ValidationRequest("fp", {make_segment()}, (), "utf-8", {}, make_context()),
                lambda: BuildRequest(source, other, {make_segment()}, "fp", {}, make_context()),
                lambda: VerifyRequest("fp", other, {make_manifest()}, "full", make_context()),
                lambda: RollbackRequest("project", {make_manifest()}, (), source, {}, make_context()),
            )
            for builder in builders:
                with self.subTest(builder=builder), self.assertRaises(TypeError):
                    builder()

    def test_result_path_lists_are_normalized_and_nested_inputs_are_copied(self):
        stats = {"files": 1}
        extract = ExtractResult([make_draft()], "source-fp", ["game\\a.rpy"], ["game/b.rpy"], ["warning"], stats)
        build = BuildResult(
            ["output\\game.dat"],
            ["output/new.dat"],
            ["output/changed.dat"],
            ["output/deleted.dat"],
            [make_manifest("output\\game.dat")],
            [make_artifact()],
            "candidate-fp",
            ["warning"],
            stats,
        )
        rollback = RollbackResult(["game\\a.rpy"], ["game/b.rpy"], ["game/c.rpy"], True, [make_issue()])
        stats["files"] = 99
        self.assertEqual(extract.read_files, ("game/a.rpy",))
        self.assertEqual(extract.statistics, {"files": 1})
        self.assertEqual(build.generated_files, ("output/game.dat",))
        self.assertEqual(build.manifest[0].relative_path, "output/game.dat")
        self.assertEqual(build.statistics, {"files": 1})
        self.assertEqual(rollback.restored_files, ("game/a.rpy",))

    def test_all_result_ordered_fields_reject_sets(self):
        builders = (
            lambda: ExtractResult({make_draft()}, "fp", (), (), (), {}),
            lambda: ValidationResult(True, {make_issue()}, (), 0, 0),
            lambda: BuildResult((), (), (), (), {make_manifest()}, (), "fp", (), {}),
            lambda: VerifyResult(True, {VerificationCheck("syntax", True, "passed")}, True, True, {}, None, ()),
            lambda: RollbackResult(set(), (), (), True, ()),
        )
        for builder in builders:
            with self.subTest(builder=builder), self.assertRaises(TypeError):
                builder()

    def test_validation_and_verification_records_validate_declared_types(self):
        issue = make_issue()
        validation = ValidationResult(False, [issue], ["restore placeholder"], 1, 0)
        check = VerificationCheck("syntax", True, "Syntax passed")
        hashes = {"output\\game.dat": "abc"}
        verify = VerifyResult(False, [check], True, True, hashes, None, [issue])
        hashes["other"] = "mutated"
        self.assertEqual(validation.issues, (issue,))
        self.assertEqual(verify.artifact_hashes, {"output/game.dat": "abc"})
        for builder in (
            lambda: make_issue(severity="error"),
            lambda: make_issue(automatically_recoverable=1),
            lambda: ValidationResult(True, (), (), -1, 0),
            lambda: VerificationCheck("syntax", 1, "passed"),
            lambda: VerifyResult(True, (), True, True, {}, "yes", ()),
            lambda: RollbackResult((), (), (), 1, ()),
        ):
            with self.subTest(builder=builder), self.assertRaises((TypeError, ValueError)):
                builder()

    def test_json_and_mapping_fields_reject_bad_values(self):
        segment = make_segment()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            staging = root / "staging"
            target = root / "target"
            for item in (source, staging, target):
                item.mkdir()
            for bad in ({"ToKeN": "secret"}, {"bad": math.nan}, {"bad": object()}):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        ValidationRequest("fp", (segment,), (segment,), "utf-8", bad, make_context())
                    with self.assertRaises(ValueError):
                        BuildRequest(source, staging, (segment,), "fp", bad, make_context())
            with self.assertRaises((TypeError, ValueError)):
                ExtractResult((), "fp", (), (), (), {"files": True})
            with self.assertRaises((TypeError, ValueError)):
                RollbackRequest("project", (), (), target, {"file": 1}, make_context())


class AdapterContractTests(AdapterV1ContractMixin, unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name).resolve()
        self.matched_root = self.root / "matched"
        self.unmatched_root = self.root / "unmatched"
        self.matched_root.mkdir()
        self.unmatched_root.mkdir()
        (self.matched_root / "matched.marker").write_text("synthetic", encoding="utf-8")

    def make_adapter(self):
        return FakeAdapter()

    def make_detection_request(self):
        return DetectionRequest(
            self.matched_root,
            DeclaredMode.PLAYER,
            "project-a",
            RiskLevel.H0_PROJECT,
            frozenset({Operation.DETECT}),
            make_context(),
        )

    def make_unmatched_detection_request(self):
        return replace(self.make_detection_request(), input_root=self.unmatched_root)

    def test_fake_unavailable_methods_return_matching_sanitized_errors_without_side_effects(self):
        adapter = self.make_adapter()
        source = self.root / "source"
        working = self.root / "working"
        staging = self.root / "staging"
        target = self.root / "target"
        for item in (source, working, staging, target):
            item.mkdir()
        cases = (
            (Operation.EXTRACT, lambda: adapter.extract(ExtractRequest(source, working, (), (), "project", make_context()))),
            (Operation.VALIDATE, lambda: adapter.validate(ValidationRequest("fp", (), (), "utf-8", {}, make_context()))),
            (Operation.BUILD, lambda: adapter.build(BuildRequest(source, staging, (), "fp", {}, make_context()))),
            (Operation.VERIFY, lambda: adapter.verify(VerifyRequest("fp", staging, (), "full", make_context()))),
            (Operation.ROLLBACK, lambda: adapter.rollback(RollbackRequest("project", (), (), target, {}, make_context()))),
        )
        before = snapshot_tree(self.root)
        for operation, call in cases:
            with self.subTest(operation=operation):
                result = call()
                self.assertIsInstance(result, AdapterError)
                self.assertIs(result.operation, operation)
                self.assertIs(result.code, AdapterErrorCode.UNSUPPORTED_INPUT)
                self.assertFalse(result.recoverable)
        after = snapshot_tree(self.root)
        self.assertEqual(after, before)

    def test_adapter_protocol_is_structural_and_exact(self):
        self.assertTrue(AdapterV1._is_protocol)
        self.assertNotIn("EngineAdapter", {base.__name__ for base in AdapterV1.__mro__})
        self.assertEqual(
            {name for name, value in AdapterV1.__dict__.items() if callable(value) and not name.startswith("_")},
            {"detect", "extract", "validate", "build", "verify", "rollback"},
        )
        adapter = self.make_adapter()
        self.assertIsInstance(adapter.metadata, AdapterMetadata)
        for name in ("detect", "extract", "validate", "build", "verify", "rollback"):
            self.assertTrue(callable(getattr(adapter, name)))

    def test_adapter_events_share_the_runner_owned_sequence(self):
        events = []
        adapter = self.make_adapter()
        plan = TaskPlan(
            task_id="task-adapter-detect",
            project_id="project-a",
            kind="detect",
            state=TaskState.QUEUED,
            steps=(
                TaskStep(
                    step_id="detect",
                    title="Detect engine",
                    operation=RouteOperation.DETECT,
                ),
            ),
        )

        def handler(context: TaskContext) -> StepResult:
            request = dataclasses.replace(
                self.make_detection_request(),
                context=context,
            )
            result = adapter.detect(request)
            self.assertIsInstance(result, DetectionResult)
            self.assertTrue(result.matched)
            return StepResult(data={"matched": result.matched})

        completed = TaskRunner(events.append).run(plan, {"detect": handler})

        self.assertEqual(completed.state, TaskState.COMPLETED)
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.QUEUED,
                EventType.STARTED,
                EventType.PROGRESS,
                EventType.LOG,
                EventType.COMPLETED,
                EventType.COMPLETED,
            ],
        )
        self.assertEqual(
            [event.sequence for event in events],
            list(range(1, len(events) + 1)),
        )


if __name__ == "__main__":
    unittest.main()
