from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .raster import RasterAssetKind, RasterManifest


NWJS_RPG_MAKER_PROBE_SCHEMA_VERSION = "hanengine.nwjs-rpg-maker-probe/v3"
NWJS_RPG_MAKER_VALIDATION_SCHEMA_VERSION = "hanengine.nwjs-rpg-maker-validation/v2"
_PROBE_FILE_NAME = "nwjs_rpg_maker_probe.js"
_PROBE_CONFIG_FILE_NAME = "hanengine_probe_config.js"
_INJECTED_PROBE_FILE_NAME = "hanengine_nwjs_probe.js"
_SHA256_LENGTH = 64


class NwjsValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class NwjsRpgMakerValidatorConfig:
    executable: Path
    evidence_root: Path
    timeout_seconds: int = 180
    probe_script: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path):
            raise TypeError("executable must be a Path")
        executable = self.executable.expanduser().resolve(strict=True)
        if not executable.is_file():
            raise ValueError("NW.js executable must be a file")
        object.__setattr__(self, "executable", executable)
        if not isinstance(self.evidence_root, Path):
            raise TypeError("evidence_root must be a Path")
        object.__setattr__(
            self,
            "evidence_root",
            self.evidence_root.expanduser().resolve(strict=False),
        )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 30 <= self.timeout_seconds <= 900
        ):
            raise ValueError("timeout_seconds must be between 30 and 900")
        probe = self.probe_script or Path(__file__).with_name(_PROBE_FILE_NAME)
        if not isinstance(probe, Path):
            raise TypeError("probe_script must be a Path or None")
        probe = probe.expanduser().resolve(strict=True)
        if not probe.is_file():
            raise ValueError("NW.js probe script must be a file")
        object.__setattr__(self, "probe_script", probe)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    resolved = root.resolve(strict=True)
    digest = hashlib.sha256()
    for path in sorted(
        resolved.rglob("*"),
        key=lambda item: (item.as_posix().casefold(), item.as_posix()),
    ):
        if path.is_symlink():
            raise NwjsValidationError("NW.js validation does not accept symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(path)))
        digest.update(b"\n")
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise NwjsValidationError(f"{name} must be an object")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise NwjsValidationError(f"{name} must be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise NwjsValidationError(f"{name} must be a non-empty string")
    return value


def _rpg_maker_base(root: Path) -> Path:
    nested = root / "www"
    return nested if (nested / "data").is_dir() else root


def _database_names(root: Path) -> dict[str, object]:
    base = _rpg_maker_base(root)

    def read(name: str) -> object:
        return json.loads((base / "data" / name).read_text(encoding="utf-8-sig"))

    system = _mapping(read("System.json"), "System.json")
    actors = _list(read("Actors.json"), "Actors.json")
    enemies = _list(read("Enemies.json"), "Enemies.json")

    def names(values: list[object]) -> list[dict[str, object]]:
        result = []
        for value in values:
            if not isinstance(value, Mapping):
                continue
            identifier = value.get("id")
            name = value.get("name")
            if isinstance(identifier, int) and isinstance(name, str) and name:
                result.append({"id": identifier, "name": name})
        return result

    title = system.get("gameTitle")
    if not isinstance(title, str):
        raise NwjsValidationError("System.json gameTitle must be a string")
    return {"game_title": title, "actors": names(actors), "enemies": names(enemies)}


def _slug(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:80] or uuid.uuid4().hex


def _video_plan(manifest: RasterManifest | None) -> list[dict[str, object]]:
    if manifest is None:
        return []
    assets = []
    for asset in manifest.assets:
        if asset.kind is not RasterAssetKind.VIDEO or not asset.is_approved:
            continue
        segments = []
        for index, segment in enumerate(asset.segments, 1):
            if segment.frame_start_ms is None or segment.frame_end_ms is None:
                raise NwjsValidationError("approved video segments require frame ranges")
            segments.append(
                {
                    "segment_id": segment.segment_id,
                    "midpoint_seconds": (
                        segment.frame_start_ms + segment.frame_end_ms
                    )
                    / 2000.0,
                    "screenshot_file": (
                        f"segments/{index:02d}-{_slug(segment.segment_id)}.png"
                    ),
                }
            )
        assets.append(
            {
                "path": asset.relative_path,
                "movie_name": Path(asset.relative_path).stem,
                "segments": segments,
            }
        )
    return assets


def _copy_shadow_tree(source: Path, destination: Path) -> dict[str, int]:
    destination.mkdir(parents=True)
    linked = 0
    copied = 0
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(source)
        if relative.parts and relative.parts[0].casefold() == "save":
            continue
        target = destination / relative
        if path.is_symlink():
            raise NwjsValidationError("NW.js shadow projects do not accept symbolic links")
        if path.is_dir():
            target.mkdir(exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
            linked += 1
        except OSError:
            shutil.copy2(path, target)
            copied += 1
    (destination / "save").mkdir(exist_ok=True)
    return {"hardlinked_files": linked, "copied_files": copied}


def _replace_linked_text(path: Path, text: str) -> None:
    path.unlink()
    path.write_text(text, encoding="utf-8", newline="\n")


def _prepare_shadow(
    source: Path,
    destination: Path,
    *,
    label: str,
    evidence_root: Path,
    video_plan: list[dict[str, object]],
    probe_script: Path,
) -> dict[str, int]:
    copy_stats = _copy_shadow_tree(source, destination)
    package_path = destination / "package.json"
    package = _mapping(
        json.loads(package_path.read_text(encoding="utf-8-sig")),
        "package.json",
    )
    configured_package = dict(package)
    configured_package["name"] = f"hanengine-nwjs-{_slug(label).casefold()}"
    configured_package["main"] = "index.html"
    configured_package["js-flags"] = "--expose-gc"
    window = configured_package.get("window")
    configured_window = dict(window) if isinstance(window, Mapping) else {}
    configured_window.update({"toolbar": False, "width": 816, "height": 624})
    configured_package["window"] = configured_window
    _replace_linked_text(
        package_path,
        json.dumps(configured_package, ensure_ascii=False, indent=2) + "\n",
    )

    index_path = destination / "index.html"
    index = index_path.read_text(encoding="utf-8-sig")
    marker = "<body"
    start = index.find(marker)
    if start < 0:
        raise NwjsValidationError("RPG Maker index.html has no body element")
    close = index.find(">", start)
    if close < 0:
        raise NwjsValidationError("RPG Maker index.html body element is malformed")
    tags = (
        '\n        <script type="text/javascript" '
        f'src="{_PROBE_CONFIG_FILE_NAME}"></script>'
        '\n        <script type="text/javascript" '
        f'src="{_INJECTED_PROBE_FILE_NAME}"></script>'
    )
    _replace_linked_text(index_path, index[: close + 1] + tags + index[close + 1 :])

    shutil.copy2(probe_script, destination / _INJECTED_PROBE_FILE_NAME)
    config = {
        "label": label,
        "output": str(evidence_root),
        "video_assets": video_plan,
    }
    (destination / _PROBE_CONFIG_FILE_NAME).write_text(
        "window.HANENGINE_NWJS_PROBE_CONFIG = "
        + json.dumps(config, ensure_ascii=False, sort_keys=True)
        + ";\n",
        encoding="utf-8",
        newline="\n",
    )
    return copy_stats


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_probe(
    config: NwjsRpgMakerValidatorConfig,
    shadow_root: Path,
    evidence_root: Path,
    label: str,
) -> dict[str, object]:
    report_path = evidence_root / "report.json"
    failure_path = evidence_root / "failure.json"
    evidence_root.mkdir(parents=True)
    profile_root = shadow_root.parent / f"{label}-profile"
    process = subprocess.Popen(
        [
            str(config.executable),
            f"--user-data-dir={profile_root}",
            str(shadow_root),
        ],
        cwd=config.executable.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + config.timeout_seconds
    try:
        while time.monotonic() < deadline:
            if report_path.is_file():
                break
            if failure_path.is_file():
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
                raise NwjsValidationError(
                    f"NW.js {label} probe failed: {failure.get('error', 'unknown error')}"
                )
            if process.poll() is not None:
                raise NwjsValidationError(
                    f"NW.js {label} exited before writing a report"
                )
            time.sleep(0.1)
        else:
            raise NwjsValidationError(f"NW.js {label} probe timed out")
    finally:
        _stop_process(process)
    return json.loads(report_path.read_text(encoding="utf-8"))


def _png_observation(path: Path) -> dict[str, object]:
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise NwjsValidationError("Pillow is required for NW.js screenshot checks") from exc
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        extrema = tuple(tuple(item) for item in ImageStat.Stat(rgb).extrema)
        width, height = rgb.size
    nonblank = any(low != high for low, high in extrema)
    return {
        "width": width,
        "height": height,
        "channel_extrema": [list(item) for item in extrema],
        "nonblank": nonblank,
    }


def _probe_checks(
    label: str,
    report: Mapping[str, object],
    project_root: Path,
    evidence_root: Path,
    video_plan: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    checks: list[dict[str, object]] = []

    def check(code: str, passed: bool, message: str) -> None:
        checks.append({"code": f"{label}:{code}", "passed": passed, "message": message})

    check(
        "schema",
        report.get("schema_version") == NWJS_RPG_MAKER_PROBE_SCHEMA_VERSION,
        "Probe report uses the supported schema",
    )
    check("label", report.get("label") == label, "Probe report label matches the run")
    title = _mapping(report.get("title_observation"), "title_observation")
    map_observation = _mapping(report.get("map_observation"), "map_observation")
    check("title_scene", title.get("scene") == "Scene_Title", "Title scene loaded")
    check(
        "map_scene",
        map_observation.get("scene") == "Scene_Map"
        and isinstance(map_observation.get("map_id"), int)
        and int(map_observation["map_id"]) > 0,
        "A non-zero start map loaded",
    )
    expected_names = _database_names(project_root)
    check(
        "game_title",
        title.get("game_title") == expected_names["game_title"],
        "Runtime game title matches System.json",
    )
    check(
        "actor_names",
        title.get("actors") == expected_names["actors"],
        "Runtime actor names match Actors.json",
    )
    check(
        "enemy_names",
        title.get("enemies") == expected_names["enemies"],
        "Runtime enemy names match Enemies.json",
    )
    events = report.get("runtime_events")
    check(
        "runtime_events",
        isinstance(events, list) and not events,
        "No console, window, or unhandled promise errors were captured",
    )

    expected_segments = {
        segment["segment_id"]
        for asset in video_plan
        for segment in asset["segments"]
    }
    runs = report.get("video_runs")
    run_by_path = {
        item.get("path"): item
        for item in runs
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    } if isinstance(runs, list) else {}
    observed_segments: set[object] = set()
    for asset in video_plan:
        asset_path = asset["path"]
        run = run_by_path.get(asset_path)
        passed = (
            isinstance(run, Mapping)
            and run.get("status") == "passed"
            and run.get("command_code") == 261
            and run.get("loaded_path") == asset_path
        )
        check(
            f"video:{asset_path}",
            passed,
            "RPG Maker command261 loaded and rendered the exact approved video path",
        )
        if not isinstance(run, Mapping):
            continue
        segments = run.get("segments")
        if isinstance(segments, list):
            observed_segments.update(
                item.get("segment_id")
                for item in segments
                if isinstance(item, Mapping)
            )
    check(
        "approved_segments",
        observed_segments == expected_segments,
        "Every approved video segment produced a runtime observation",
    )

    screenshot_results = []
    screenshots = report.get("screenshots")
    if not isinstance(screenshots, list):
        screenshots = []
    for item in screenshots:
        if not isinstance(item, Mapping):
            continue
        relative = item.get("file")
        expected_hash = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            continue
        candidate = (evidence_root / Path(*relative.split("/"))).resolve(strict=False)
        inside = candidate != evidence_root and evidence_root in candidate.parents
        exists = inside and candidate.is_file()
        hash_matches = exists and _sha256_file(candidate) == expected_hash
        observation = _png_observation(candidate) if hash_matches else None
        nonblank_required = relative != "map.png"
        screenshot_results.append(
            {
                "file": relative,
                "sha256": expected_hash,
                "hash_matches": hash_matches,
                "nonblank_required": nonblank_required,
                "image": observation,
            }
        )
    expected_screenshot_files = {"title.png", "map.png"} | {
        str(segment["screenshot_file"])
        for asset in video_plan
        for segment in asset["segments"]
    }
    observed_screenshot_files = [item["file"] for item in screenshot_results]
    screenshots_passed = (
        len(observed_screenshot_files) == len(expected_screenshot_files)
        and set(observed_screenshot_files) == expected_screenshot_files
        and all(item["hash_matches"] for item in screenshot_results)
        and all(
            isinstance(item["image"], Mapping)
            and (
                not item["nonblank_required"]
                or item["image"].get("nonblank")
            )
            for item in screenshot_results
        )
    )
    check(
        "screenshots",
        screenshots_passed,
        (
            "Title, map, and approved segment screenshots are present and hashed; "
            "title and segment captures are nonblank"
        ),
    )
    versions = _mapping(report.get("runtime_versions"), "runtime_versions")
    compact = {
        "runtime_versions": {
            "nw": versions.get("nw"),
            "chromium": versions.get("chromium"),
            "node": versions.get("node"),
        },
        "title_observation": title,
        "map_observation": map_observation,
        "video_runs": runs,
        "runtime_event_count": len(events) if isinstance(events, list) else None,
        "screenshots": screenshot_results,
    }
    return checks, compact


def _evidence_manifest(root: Path) -> list[dict[str, object]]:
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path != root / "validation-report.json"
    ]


def _publish_evidence(temporary: Path, destination: Path) -> None:
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise NwjsValidationError("NW.js evidence root must be a directory")
        if next(destination.iterdir(), None) is not None:
            raise NwjsValidationError("NW.js evidence root already exists and is not empty")
        destination.rmdir()
    temporary.replace(destination)


def run_nwjs_rpg_maker_validation(
    config: NwjsRpgMakerValidatorConfig,
    source_root: Path,
    candidate_root: Path,
    manifest: RasterManifest | None = None,
) -> dict[str, object]:
    if not isinstance(config, NwjsRpgMakerValidatorConfig):
        raise TypeError("config must be an NwjsRpgMakerValidatorConfig")
    if manifest is not None and not isinstance(manifest, RasterManifest):
        raise TypeError("manifest must be a RasterManifest or None")
    source = source_root.resolve(strict=True)
    candidate = candidate_root.resolve(strict=True)
    evidence = config.evidence_root
    evidence.parent.mkdir(parents=True, exist_ok=True)
    video_plan = _video_plan(manifest)
    source_before = _tree_sha256(source)
    candidate_before = _tree_sha256(candidate)
    evidence_temporary = Path(
        tempfile.mkdtemp(prefix=f".{evidence.name}.nwjs.", dir=evidence.parent)
    ).resolve()
    work_parent = Path(
        tempfile.mkdtemp(prefix=".hanengine-nwjs-work.", dir=candidate.parent)
    ).resolve()
    try:
        variants = {}
        all_checks = []
        copy_stats = {}
        for label, project in (("source", source), ("candidate", candidate)):
            variant_evidence = evidence_temporary / label
            shadow = work_parent / label
            copy_stats[label] = _prepare_shadow(
                project,
                shadow,
                label=label,
                evidence_root=variant_evidence,
                video_plan=video_plan,
                probe_script=config.probe_script,
            )
            raw_report = _run_probe(config, shadow, variant_evidence, label)
            checks, compact = _probe_checks(
                label,
                _mapping(raw_report, f"{label} probe report"),
                project,
                variant_evidence,
                video_plan,
            )
            all_checks.extend(checks)
            variants[label] = compact

        source_after = _tree_sha256(source)
        candidate_after = _tree_sha256(candidate)
        preservation_checks = [
            {
                "code": "source_tree_preserved",
                "passed": source_before == source_after,
                "message": "NW.js validation preserved the source tree",
            },
            {
                "code": "candidate_tree_preserved",
                "passed": candidate_before == candidate_after,
                "message": "NW.js validation preserved the candidate tree",
            },
        ]
        all_checks.extend(preservation_checks)
        source_versions = variants["source"]["runtime_versions"]
        candidate_versions = variants["candidate"]["runtime_versions"]
        all_checks.append(
            {
                "code": "runtime_versions_match",
                "passed": source_versions == candidate_versions,
                "message": "Source and candidate used identical NW.js runtime versions",
            }
        )
        issues = [
            {
                "code": check["code"],
                "message": check["message"],
                "blocking": True,
            }
            for check in all_checks
            if not check["passed"]
        ]
        report: dict[str, object] = {
            "schema_version": NWJS_RPG_MAKER_VALIDATION_SCHEMA_VERSION,
            "status": "passed" if not issues else "failed",
            "tool": {
                "name": config.executable.name,
                "sha256": _sha256_file(config.executable),
            },
            "source_tree_sha256_before": source_before,
            "source_tree_sha256_after": source_after,
            "candidate_tree_sha256_before": candidate_before,
            "candidate_tree_sha256_after": candidate_after,
            "approved_video_count": len(video_plan),
            "approved_segment_count": sum(
                len(asset["segments"]) for asset in video_plan
            ),
            "shadow_copy": copy_stats,
            "variants": variants,
            "checks": all_checks,
            "issues": issues,
        }
        report_path = evidence_temporary / "validation-report.json"
        report["evidence_files"] = _evidence_manifest(evidence_temporary)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _publish_evidence(evidence_temporary, evidence)
        published_report = evidence / "validation-report.json"
        report["report_sha256"] = _sha256_file(published_report)
        report["evidence_root_name"] = evidence.name
        return report
    except Exception:
        shutil.rmtree(evidence_temporary, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work_parent, ignore_errors=True)


__all__ = [
    "NWJS_RPG_MAKER_PROBE_SCHEMA_VERSION",
    "NWJS_RPG_MAKER_VALIDATION_SCHEMA_VERSION",
    "NwjsRpgMakerValidatorConfig",
    "NwjsValidationError",
    "run_nwjs_rpg_maker_validation",
]
