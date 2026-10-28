from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_CATALOG_SHA256 = (
    "2cf6c7cb511f224a50278ff3e750b11022d82364b854d82509e129269ed0ffbc"
)
EXPECTED_DICTIONARY_SHA256 = (
    "4670b241021133da467ed443649a95f99d467ad4d6982d50a4b53b4c15e9dc7c"
)

SEGMENT_OVERRIDES = {
    ("data/CommonEvents.json", "/2/list/335/parameters/0/0"): ("Hit", "要牌"),
    ("data/CommonEvents.json", "/2/list/475/parameters/0/0"): ("Hit", "要牌"),
    ("data/CommonEvents.json", "/2/list/615/parameters/0/0"): ("Hit", "要牌"),
}

for card_number, indexes in {
    3: (367, 376, 385, 394, 403, 412, 421, 430, 439),
    4: (507, 516, 525, 534, 543, 552, 561, 570, 579),
    5: (647, 656, 665, 674, 683, 692, 701, 710, 719),
}.items():
    for index in indexes:
        SEGMENT_OVERRIDES[
            ("data/CommonEvents.json", f"/2/list/{index}/parameters/0")
        ] = ("Player Card 2: \\v[4]", f"玩家第{card_number}张牌：\\v[4]")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_catalog(
    catalog: dict[str, object], dictionary: dict[str, str]
) -> tuple[dict[str, object], dict[str, object]]:
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise TypeError("catalog entries must be a list")

    missing_dictionary: set[str] = set()
    applied_overrides: list[dict[str, str]] = []
    seen_override_keys: set[tuple[str, str]] = set()
    translated_entries: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("catalog entries must be objects")
        source_text = entry.get("source_text")
        relative_path = entry.get("relative_path")
        locator = entry.get("locator")
        if not isinstance(source_text, str) or not isinstance(relative_path, str):
            raise TypeError("catalog entry source_text and relative_path must be strings")
        if not isinstance(locator, dict) or not isinstance(locator.get("pointer"), str):
            raise TypeError("catalog entry locator pointer must be a string")

        target_text = dictionary.get(source_text)
        if target_text is None:
            missing_dictionary.add(source_text)
            target_text = entry.get("target_text")
        key = (relative_path, locator["pointer"])
        override = SEGMENT_OVERRIDES.get(key)
        if override is not None:
            expected_source, target_text = override
            if source_text != expected_source:
                raise ValueError(
                    f"segment override source mismatch at {relative_path}#{locator['pointer']}"
                )
            seen_override_keys.add(key)
            applied_overrides.append(
                {
                    "relative_path": relative_path,
                    "pointer": locator["pointer"],
                    "source_text": source_text,
                    "target_text": target_text,
                }
            )
        translated_entries.append({**entry, "target_text": target_text})

    unapplied = sorted(set(SEGMENT_OVERRIDES) - seen_override_keys)
    if unapplied:
        raise ValueError(f"segment overrides were not found in the catalog: {unapplied}")
    if missing_dictionary:
        raise ValueError(
            f"dictionary is missing {len(missing_dictionary)} source texts: "
            f"{sorted(missing_dictionary)}"
        )
    if any(entry["target_text"] is None for entry in translated_entries):
        raise ValueError("translated catalog contains empty target bindings")

    result = {**catalog, "entries": translated_entries}
    report = {
        "schema_version": "hanengine.project-reviewed-catalog-report/v1",
        "catalog_entries": len(translated_entries),
        "unique_source_texts": len({entry["source_text"] for entry in entries}),
        "dictionary_entries": len(dictionary),
        "segment_override_count": len(applied_overrides),
        "segment_overrides": applied_overrides,
        "untranslated_entries": 0,
    }
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind the reviewed Hello Underworld dictionary to catalog segments."
    )
    parser.add_argument("catalog", type=Path)
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    catalog_path = args.catalog.resolve(strict=True)
    dictionary_path = args.dictionary.resolve(strict=True)
    if _sha256(catalog_path) != EXPECTED_CATALOG_SHA256:
        raise ValueError("catalog does not match the reviewed v3 source catalog")
    if _sha256(dictionary_path) != EXPECTED_DICTIONARY_SHA256:
        raise ValueError("dictionary does not match the reviewed v3 dictionary")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    dictionary = json.loads(dictionary_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(dictionary, dict):
        raise TypeError("catalog and dictionary roots must be objects")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in dictionary.items()):
        raise TypeError("dictionary entries must map strings to strings")

    translated, report = build_catalog(catalog, dictionary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(translated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Catalog: {args.output.resolve()}")
    print(f"Report: {args.report.resolve()}")
    print(f"Entries: {report['catalog_entries']}")
    print(f"Segment overrides: {report['segment_override_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
