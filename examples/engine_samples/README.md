# HanEngine Engine Samples

These fixtures are small, redistributable projects for testing HanEngine's
ordinary-player workflow. They contain only original text fixtures and no
third-party game assets.

| Directory | Engine | Structured resource | Public case to compare manually |
| --- | --- | --- | --- |
| `renpy_tutorial` | Ren'Py 7/8 | `game/*.rpy` | [Ren'Py Tutorial](https://www.renpy.org/doc/html/quickstart.html) |
| `rpg_maker_mv` | RPG Maker MV | `data/*.json` | [ShadowArenaMV](https://github.com/miladtak/ShadowArenaMV) |
| `rpg_maker_mz` | RPG Maker MZ | `data/*.json` | RPG Maker MZ sample projects shipped with the editor |
| `godot_dodge_the_creeps` | Godot 4 | `locale/game.po` | [Godot demo projects](https://github.com/godotengine/godot-demo-projects/tree/master/2d/dodge_the_creeps) |
| `unity_2d_kit` | Unity | `Assets/Localization/Game.xliff` | [Unity 2D Game Kit](https://learn.unity.com/project/2d-game-kit) |
| `unreal_lyra` | Unreal Engine 5 | `Content/Localization/Game.po` | [Lyra Starter Game](https://dev.epicgames.com/documentation/en-us/unreal-engine/lyra-sample-game-in-unreal-engine) |

The public cases are references for resource layout and user expectations. The
repository does not download or redistribute their assets. Obtain and process
those projects only under their respective licenses and with authorization.

## Manual smoke test

From the repository root, run the ordinary-player workflow against one sample:

```powershell
python cli.py engine localize rpg_maker_mv examples/engine_samples/rpg_maker_mv `
  --output .tmp/engine-samples/mv-output `
  --dictionary examples/engine_samples/rpg_maker_mv/dictionary.zh-CN.json `
  --state-root .tmp/engine-samples/mv-state
```

For another fixture, replace both the engine ID and project directory according
to the table above, and use that directory's `dictionary.zh-CN.json`. The
automated acceptance test covers all six adapters and checks that the source
tree remains unchanged.

## Desktop smoke test

1. From `desktop/`, run `npm run dev` and open the sample directory in the
   Electron app. The default mode is `普通`; use `专业` for this manual
   extraction/build check.
2. In the `翻译工作区`, select the matching engine ID and run extraction to a
   temporary catalog path.
3. Select that sample's `dictionary.zh-CN.json`, choose an empty output
   directory, and run the translation/build/validation workflow.
4. Open `任务中心` to inspect the persisted detection, extraction,
   translation, validation, build, and verification tasks.
