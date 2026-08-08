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
