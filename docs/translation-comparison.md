# Translation Comparison

`engine compare` compares three values for Unity Localization Addressables entries:

- the English source in the catalog;
- the Simplified Chinese table packaged by the game;
- the current `target_text` in the translated catalog.

The packaged Chinese text is evidence for review. It is not copied into the candidate automatically.

## Command

From the repository root:

```powershell
py -3.12 cli.py engine compare unity `
  "D:\steammm\steamapps\common\How to Fish\How to Fish" `
  "D:\HanEngine\reviews\translated.json" `
  --official-bundle "D:\HanEngine\backups\how-to-fish-original-20261022-183026\localization-string-tables-chinese(simplified)(zh-cn)_assets_all_e67ef9ecbbde6f3bbc9e7dc785834f2c.bundle" `
  --output "D:\HanEngine\reviews\comparison.json" `
  --html-output "D:\HanEngine\reviews\comparison.html"
```

The JSON report is intended for later model or batch processing. The HTML report supports filtering by severity and searching by source, official Chinese, candidate Chinese, or table name.

Categories are deterministic in the first pass:

- `match`: candidate equals the packaged Chinese value;
- `difference`: both are present but differ and require review;
- `format_error`: placeholders changed;
- `corrupt_output`: replacement characters are present;
- `untranslated`: English source was returned unchanged;
- `missing_target`: no candidate translation exists.
- `source_mismatch`: the catalog English value does not match the current game resource;
- `candidate_only`: the official Chinese table has no matching entry.

The report does not edit the catalog. After review, a separate approved catalog can be passed to `engine build`.

For a new local-model translation pass, the same report can be supplied to `engine localize --reference-report` so each matching official entry guides wording, terminology, and punctuation. See [Local Model Translation](local-model-translation.md); use `--no-resume` when regenerating an existing project's translations.

Use `--official-bundle` when the game's installed Chinese bundle has already been replaced. Without it, the command reads the Chinese bundle from `project`.
