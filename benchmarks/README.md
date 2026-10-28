# HanEngine Synthetic Benchmarks

`benchmarks/LICENSE` contains the CC0 1.0 Universal legal text. CC0-1.0
applies only to repository-owned synthetic assets and metadata under
`benchmarks/`.

The repository root license remains undecided. This benchmark-scoped CC0
declaration does not license production code, tests, documentation, or any
other repository path.

No commercial game files, screenshots, or translated text are included.
No third-party code or assets are copied, adapted, generated, or committed here.
This cycle commits only manifests and risk snapshots. Future multi-engine
fixtures, screenshots, dynamic sequences, and human-reference assets must
match the IDs frozen by these manifests. The existing Ren'Py manifest is a
historical benchmark subset, not a product-scope restriction.

Regenerate the manifests with:

```powershell
python tools/generate_benchmark_manifests.py
```

Verify their exact committed bytes without writing with:

```powershell
python tools/generate_benchmark_manifests.py --check
```

## Controlled visual-judge dataset

`visual_judge_controlled/` contains 36 deterministic paired scenes: four
normal controls plus four variants for each of eight release-blocking defect
classes. Its machine-readable truth uses the same
`hanengine.visual-judge-benchmark/v1` sample contract as
`tools/benchmark_visual_judges.py`.

The images use a fixed 960x540 synthetic interface and a vendored, renamed
subset of Adobe Source Han Sans SC. The font is licensed separately under
SIL OFL 1.1 in `assets/FONT-OFL-LICENSE.txt`; generated screenshots and their
truth manifest remain covered by the benchmark's CC0 license. The manifest
records the font hash and Pillow version. Install the pinned image dependency
from `requirements-visual-benchmarks.txt` before regeneration. Generator v3
uses the same fixed font on every supported host and localizes the candidate's
title, chapter, button, and save-slot labels so the four normal controls
contain no known English UI residual. Benchmark requests also omit
category-bearing sample IDs.

Regenerate the dataset with:

```powershell
python tools/generate_visual_judge_dataset.py
```

Verify schema, image dimensions, category balance, byte determinism, and the
committed output with:

```powershell
python -m unittest tests.test_visual_judge_dataset
```
