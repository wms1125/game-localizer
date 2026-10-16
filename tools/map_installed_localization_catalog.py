"""Map an installed Unity Localization table onto a fresh HanEngine catalog.

The input table audit is keyed by Unity table name and entry ID.  This keeps
duplicate source strings unambiguous and lets the standard Addressables adapter
perform validation and candidate construction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from game_localizer.hanengine.multiengine import LocalizationCatalog
from game_localizer.hanengine.translation import _preserves_placeholders


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def map_catalog(
    catalog: LocalizationCatalog,
    audit: dict[str, object],
) -> tuple[LocalizationCatalog, dict[str, object]]:
    if audit.get("source_project_fingerprint") != catalog.project_fingerprint:
        raise ValueError("installed table audit fingerprint does not match catalog")
    raw_entries = audit.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("installed table audit has no entries list")
    targets: dict[tuple[str, int], str] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("installed table audit entry is not an object")
        table_name = raw.get("table_name")
        entry_id = raw.get("entry_id")
        target = raw.get("target")
        if not isinstance(table_name, str) or not isinstance(entry_id, int) or not isinstance(target, str):
            raise ValueError("installed table audit entry has invalid fields")
        key = (table_name, entry_id)
        if key in targets:
            raise ValueError(f"duplicate installed table entry: {table_name}:{entry_id}")
        targets[key] = target

    fallback_keys: list[dict[str, object]] = []
    mapped: list = []
    expected_keys: set[tuple[str, int]] = set()
    for entry in catalog.entries:
        table_name = entry.locator.get("table_name")
        entry_id = entry.locator.get("entry_id")
        if not isinstance(table_name, str) or not isinstance(entry_id, int):
            raise ValueError("catalog entry is missing Unity table identity")
        key = (table_name, entry_id)
        expected_keys.add(key)
        try:
            target = targets[key]
        except KeyError as exc:
            raise ValueError(f"installed table is missing {table_name}:{entry_id}") from exc
        if not _preserves_placeholders(entry.source_text, target):
            fallback_keys.append(
                {
                    "table_name": table_name,
                    "entry_id": entry_id,
                    "source": entry.source_text,
                    "installed_target": target,
                    "reason": "installed target does not preserve source placeholders",
                }
            )
            target = entry.source_text
        mapped.append(entry.__class__(**{**entry.to_dict(), "target_text": target}))
    unexpected = sorted(set(targets) - expected_keys)
    if unexpected:
        raise ValueError(f"installed table has {len(unexpected)} entries absent from catalog")
    result = catalog.__class__(
        engine_id=catalog.engine_id,
        language=catalog.language,
        source_language=catalog.source_language,
        project_fingerprint=catalog.project_fingerprint,
        files=catalog.files,
        entries=tuple(mapped),
    )
    report = {
        "schema_version": "hanengine.installed-localization-map/v1",
        "source_project_fingerprint": catalog.project_fingerprint,
        "catalog_entries": len(catalog.entries),
        "mapped_entries": len(mapped),
        "placeholder_fallbacks": fallback_keys,
        "human_review_required": True,
        "translation_source": "installed Simplified Chinese Unity Localization table",
    }
    return result, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    catalog = LocalizationCatalog.from_dict(_read_json(args.catalog))
    audit = _read_json(args.audit)
    if not isinstance(audit, dict):
        raise SystemExit("audit must be a JSON object")
    mapped, report = map_catalog(catalog, audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapped.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
