# Hello Underworld v14 Non-Art Text Candidate

Date: 2026-08-17

## Scope

This candidate is the current user-review build for `CMPUT250HU/HelloUnderworld`, commit `afbb145ca626a43ae73432c64724d9be17e9ae82` (Apache-2.0). It intentionally excludes raster localization after the localized cutscene videos produced noticeable playback stutter during review.

Included: structured RPG Maker MV text and the native CJK font configuration. Excluded: title artwork, all image resources, all three WebM cutscenes, audio, and JavaScript.

## Build

The candidate was generated with `project validate` using the v4 reviewed catalog and Source Han Sans SC:

```powershell
python cli.py project validate rpg_maker_mv <source> `
  --output .tmp/rpg-maker-hello-underworld-zh-cn-v14 `
  --dictionary .tmp/rpg-maker-hello-underworld-zh-cn-dictionary-v3.json `
  --reviewed-catalog .tmp/rpg-maker-hello-underworld-reviewed-catalog-v4.json `
  --state-root .tmp/rpg-maker-hello-underworld-v14-state `
  --record .tmp/rpg-maker-hello-underworld-validation-record-v14-reviewed-text.json `
  --record-id rpg-maker-hello-underworld-v14-reviewed-text `
  --project-label "Hello Underworld non-art text v14" `
  --authorized `
  --authorization-reference "Hello Underworld Apache-2.0 repository-owned source" `
  --font .tmp/rpg-maker-hello-underworld-font-v2/SourceHanSansSC-Regular.otf
```

The reviewed catalog matched `1954/1954` segments. It is merged before the mechanical dictionary, so distinct translations for identical English source text remain segment-specific.

## Result

- Record: `.tmp/rpg-maker-hello-underworld-validation-record-v14-reviewed-text.json`
- Conclusion: `build_ready`
- Candidate tree SHA-256: `c1f06f1ca03246f85a3aba2873ee6f02c3def792e5d8d4b825c4b0e8261672d2`
- Reviewed catalog SHA-256: `590f3185ad2418dd3cfb787be98bb1f2677d2554376941de8c3311e3a0ba8fab`
- Raster status: `not_configured`
- Runtime smoke: `not_run`

The build changes 22 structured data files plus `fonts/gamefont.css`, and adds `fonts/SourceHanSansSC-Regular.otf`. The title artwork, window skin, engine scripts, and each of the three WebM files match the source project byte-for-byte.

This candidate is appropriate for checking dialogue, choices, battle text, mini-game text, character names, enemy names, items, skills, and system menus. It does not claim Chinese cutscene text or a localized title image.

## Follow-up Smoke Record

On 2026-08-21, the same candidate tree was launched in an isolated NW.js 0.29.4 profile and manually checked after the raster-localized cutscene variants had been removed. The user confirmed normal operation. The rebuilt v15 candidate is byte-for-byte identical to v14 and records this result as `manual-nwjs-v14-playtest-2026-08-21`.

The v15 validation record is `.tmp/rpg-maker-hello-underworld-validation-record-v15-reviewed-text-smoke.json`. It remains `build_ready`: this manual smoke record validates the current non-art text scope, but it is not an official validator result and does not certify raster resources or a complete story playthrough.
