# HanEngine 当前项目状态

更新时间：2026-08-12

本文是当前工作树的阶段性状态摘要。它补充并更新 `docs/project-status.md`，重点记录最近的真实 Ren'Py 项目验证和“无感汉化”目标。这里的“已验证”表示工程流水线、编译、字体和运行冒烟证据完整，不代表机器翻译质量已经达到发布标准。

当前仓库分支为 `codex/game-localizer`。最新本地代码 checkpoint 为 `9bcda39 feat: add visual style quality gates`，远端尚未同步；工作树还包含视觉证据运行器、Ren'Py 成对截图采集器和本状态文档的未提交改动。

## 1. 已完成内容

### 核心运行时

- 已建立 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard 的统一工作流。
- 已接入 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 的结构化资源适配路径。
- 已实现检测、提取、翻译、校验、独立构建、验证、任务持久化、断点续跑、取消和重试。
- 默认输出位于源项目之外，支持源树指纹、候选树指纹、占位符校验、UTF-8 校验、产物哈希和回滚边界。

### 桌面端与账户

- Electron + React 桌面端已替代旧 Tkinter 入口。
- 已实现本地账户数据库、登录/退出、PBKDF2-SHA256 密码哈希和会话门控。
- 普通模式映射为 `player`，专业模式映射为 `studio`；未认证渲染进程不能访问项目和任务 IPC。
- 任务中心支持查看、取消、重试和重启恢复。
- 客户端设置现承载游戏启动语言（简体中文/原文）和游戏启动程序；设置保存在本地，并由受认证的 Electron IPC 以 `HANENGINE_GAME_LANGUAGE` 传给游戏进程。游戏候选不添加语言菜单。

### Ren'Py 适配器修复

- Ren'Py 明文 `.rpy` 已接入 AdapterV1 全流程。
- 已过滤 `id`、`style`、`variant`、`background`、`activate_sound` 等屏幕属性，避免把资源名或控件属性误识别为对白。
- 同一脚本中的重复文本现在会生成唯一段 ID。
- 生成翻译块时按源文本去重，避免 Ren'Py 因重复 `old` 字符串在运行时崩溃。
- `_()` 包装的普通对白、屏幕 `text`、`textbutton` 和 `label` 现在可被提取；同一行动态 screen 表达式中的多个直接字符串字面量也会逐项提取，非字面量运行时表达式仍保持未处理；屏幕文本按字符串翻译块写出。
- Ren'Py 占位符校验现在支持嵌套 Python 插值表达式和带属性的富文本标签；动态变量可调整顺序，但标签序列必须保持不变。
- 候选输出现在额外写出 `game/hanengine_language.rpy`，使用 Ren'Py 原生 `config.default_language` 在首次运行默认启用目标语言；HanEngine 客户端可以在启动时明确传入中文或原文模式，游戏内不新增语言入口。
- 翻译文件和语言激活文件均纳入构建清单、SHA-256 和候选验证；保留激活路径冲突检查，源项目仍不会被修改。
- 官方验证器现在在临时影子目录中运行，Ren'Py 编译产生的 `.rpyc`、`game/cache` 和日志不会污染候选输出，也不会被误判为 HanEngine 修改。
- `--font` 不再只做外部覆盖率检查。Ren'Py 构建会把字体复制到 `game/hanengine_fonts/`，并生成 `game/hanengine_fonts.rpy`，对目标语言配置 GUI、对白、按钮和选项字体。
- 多字体候选使用 Ren'Py 原生 `FontGroup`。字体按参数顺序分配实际 Unicode cmap 覆盖，最后一个字体作为未显式码点的运行时回退；无覆盖码点、非法字体、符号链接、文件名冲突和保留路径冲突都会使构建失败。
- 字体配置和字体二进制现在与翻译、语言激活文件一起进入 `BuildResult.generated_files`、manifest、SHA-256、候选指纹和 AdapterV1 验证，修复了“字体覆盖检查通过但候选包仍显示方框”的假阳性。

### 真实非官方项目验证

- 项目：`Heartfelt Moments`，来源为第三方 GitLab 仓库：<https://gitlab.com/asa_hito/hm>。
- 目标包：`HM-1.2.5-pc`；仓库声明 MIT License。
- 纯净归档验证记录：`.tmp/heartfelt-pristine-validation-record-final.json`。
- 检测并提取了 4 个 `.rpy` 文件，共 232 个文本段，232/232 段完成翻译。
- 官方 Ren'Py SDK：`8.5.3.26051504`，编译退出码为 0。
- `simhei.ttf` + `seguisym.ttf` 字体覆盖检查通过，无缺失码点。
- 真实 `HM.exe` 使用隔离 `--savedir` 启动，15 秒内到达界面和 OpenGL 初始化，无 `traceback.txt`、无 stderr；随后主动停止进程。
- 最终记录结论为 `verified`，已确认源树 SHA-256 前后一致。

本次真实验证使用的是保留占位符的机械测试字典，因此它证明的是适配器和发布流水线闭环，不代表最终中文翻译的语言质量。

### 语料与术语来源治理

- 已建立 `docs/translation-source-policy.md` 和机器可读的 `docs/translation-sources.json`，把来源可追溯、许可证证据、运行时参考和中文质量权威分开记录。
- Ren'Py 官方 `The Question` 样例已按发行包 `8.5.3.26051504`、发行包 SHA-256、上游参考提交 `3baa108`、许可证文件哈希、样例树哈希和简体中文文件哈希登记；发行包版本和上游提交是两个独立的证据点。它只作为本地运行时和人工术语审校参考，不作为通用中文翻译质量权威。
- golden corpus 继续使用仓库文件和 manifest 管理；当前规模不需要专门数据库。数据库只有在需要多人在线审校、权限、查询和版本合并时才有实际收益。

### 官方 The Question 中文候选与运行时证据

- 固定来源：Ren'Py 官方 SDK `8.5.3.26051504` 中的 `The Question`；中文和运行时来源链见 `docs/translation-sources.json`。
- 历史 v8 统一验证记录：`.tmp/record-renpy-the-question-zhcn-fonts-v8-dynamic-ui-verified.json`；本轮客户端语言/术语修正以 v10 候选为基线，最终 v11 候选位于 `.tmp/candidate-renpy-the-question-zhcn-client-language-v11-verified`，验证记录为 `.tmp/record-renpy-the-question-zhcn-client-language-v11-verified.json`。
- 共提取 242 个源段，目录中 242/242 均存在目标值；这只是目录覆盖率，不能证明每条都已完成中文化。新增覆盖 `Page {}`、`Automatic saves`、`Quick saves`、`{#file_time}%A, %B %d %Y, %H:%M` 和 `empty slot` 等嵌套 screen 表达式字符串，源项目树保持不变。
- v8 记录和 r7 截图均早于客户端语言控制与标题术语修正，不能用于证明本轮语言切换或标题。v11 已重新完成候选构建、官方 SDK 编译和原文/中文双模式 runtime smoke，记录结论为 `verified`。
- 候选生成 5 个受管文件：翻译文件、语言激活文件、字体配置文件、`SourceHanSansLite.ttf` 和 `DejaVuSans.ttf`。v10/v11 候选指纹均为 `d50fbaa29b479a61f78b3b722eb3032a5f94bf4abc44086fd345bdea3eb77471`，输出树 SHA-256 均为 `1bd6d0d4a1e71e3d9f92489d6c135837d2a06cff2ce741fe1abd945965b42a95`。
- AdapterV1 内部验证通过，字体覆盖无缺失码点，官方 Ren'Py 编译退出码为 0。v11 runtime smoke 引用 `.tmp/dual-language-v11-clean.json`，验证记录 SHA-256 为 `d5b9c54ffbd0935e40624c0a3f8a4ceb17de1b50efcc957c08312f2ab3d468f5`。
- r7 隔离候选成对采集位于 `.tmp/visual-evidence-renpy-the-question-v7-dynamic-ui-r7/`，采集报告 SHA-256 为 `423afc73dccbe427102bf35ed35e825d53151ace9e9ad9d98bc05f0385ad075f`，候选指纹与 v8 记录一致。
- 已人工检查 v11 中文候选的 `main-menu.png`、`dialogue.png`、`branch.png`、`settings.png`、`save.png` 和 `load.png`。主菜单、对白、分支选项、设置、保存和读取页面均显示真实汉字；保存/读取页使用全新空存档目录，未再携带含原文对白的旧缩略图。设置页保留的 `English`、`Español` 等是语言名称，`Ren'Py` 是品牌。
- v11 中文和原文报告均整体通过，参考/候选 screen 断言分别为 `6/6 + 6/6`。中文报告 SHA-256 为 `ec1bb5107a2829ef083926a54ad65d245df599a9231c32c7d47164d097a7d6b4`，原文报告 SHA-256 为 `8d4ee66b9b010c1cabf8086ec8ca38e702569c6049671c94ffdcd2c1c0efde2f`；短证据索引 SHA-256 为 `b955a3e45d24f122f67b43963f473bc0158a066931df8d8cfc0350f2abdee48e`。
- v9 中文客户端采集中的候选变体六个 screen 断言全部通过，主菜单标题为“问题”，对白、分支、设置、保存和读取页未见英文自然语言残留；整组报告未通过的原因是参考原文动作序列受桌面前台程序干扰，不能把它写成成对采集整体通过。v10 已补齐无障碍说明、Page Up/Down 和测试分支等目录漏译，剩余 2 个非阻断告警是作者署名和语言名称。

### 视觉证据与真实截图采集（第一阶段新增）

- 已建立 `VisualStyleProfile`、`VisualComparison`、硬性排版门槛和可插拔 `VisualJudge` 的严格 JSON 往返契约；`VisualEvidenceManifest` 和 `VisualEvidenceReport` 已升级到 v2，报告只保存相对路径、截图尺寸、SHA-256、观察来源/引用和结构化判定，不嵌入图片二进制。
- 已新增 `visual_evidence.py`、`cli.py visual prepare` 和 `cli.py visual verify`。`prepare` 从 v2 Ren'Py 采集报告和严格 `hanengine.visual-evidence-annotations/v1` 人工标注生成受控 manifest，重新校验 screen 语义、场景顺序、源指纹、PNG 尺寸/哈希和区域 ID，并固定写入 `observation_source=manual`；`verify` 按 `blocked -> escalate -> pass` 顺序执行确定性硬门和可选外部判官。
- 已新增 `renpy_visual_capture.py` 和 `cli.py visual capture-renpy`：同一声明式交互计划分别运行原文和候选项目，项目先复制到临时影子目录，记录源树是否保持不变、窗口几何、截图哈希和运行状态。
- Ren'Py 采集计划和报告已升级到 v2。每个场景必须声明 `expected_screen`，临时影子项目中的只读引擎探针通过原生 `renpy.get_screen()` 验证页面语义；旧 v1 计划仍可读取，但只能得到 `capture_passed`，不能得到 `semantic_alignment_verified` 或整体 `passed`。Windows 后端支持右键菜单动作，并会重新定位同一进程、等待稳定窗口几何，拒绝瞬时小窗口截图；目标窗口优先通过 Win32 `PrintWindow` 直接采集，失败时才回退桌面截图，默认使用 `angle2` 渲染器规避渲染器恢复页。
- 官方 `The Question` 参考源和 v7 汉化候选已通过 v2 六场景成对采集。`.tmp/visual-evidence-renpy-the-question-v7-dynamic-ui-r7/capture-report.json` 记录原文和候选在主菜单、对白、分支、设置、保存和读取页面均为 6/6 screen 断言通过，12 张 PNG 均为 `1296x759`，两棵源树保持不变，报告 SHA-256 为 `423afc73dccbe427102bf35ed35e825d53151ace9e9ad9d98bc05f0385ad075f`。
- r7 截图已补充布局容器级人工观察并生成 v2 A/B `VisualEvidenceReport`。`.tmp/visual-evidence-renpy-the-question-v7-dynamic-ui-r7/visual-manifest.json` 的 SHA-256 为 `9cf3547d2c0ce37dd183a527e01c85776678799cb55e831367d365d65c181fcb`；`visual-report.json` 的 SHA-256 为 `ecdfd100262604f5155292a2512e3d553cc134fa32f7c51f566db7be08171de5`。6/6 场景的区域集合、位置、尺寸、换行、基线、缺字、溢出、裁切和字体解析硬门全部通过；保存/读取页额外覆盖页码、时间戳和空存档标签。由于未配置视觉判官，最终决定按设计为 `escalate`，唯一原因为 `visual_judge_unavailable`，不能表述为视觉判官 `pass`。视觉/采集/CLI 相关窄回归曾完成 42 项，随后扩展到 64 项。全量工作区 Python `python -m unittest discover -s tests` 已完成 479 项，其中 475 项通过、3 项失败、1 项错误：两项 compliance 用例受本地 `.tmp/sdk/unpacked` 和不可枚举 `.pytest_cache` 影响，一项因工作区 Python 缺少 `fontTools`，一项为 Windows 重解析点错误文案与 `Symlink loop` 预期不一致；这些环境问题未归入本轮功能结论。

## 2. 当前代码结构

```text
game-localizer/
|- cli.py                         CLI 总入口：engine、project validate、tasks、package 等
|- translator.py                  兼容的单文件明文翻译器和 JSON 字典加载
|- game_localizer/
|  |- adapters/
|  |  |- contract.py               AdapterV1 数据模型、能力、错误和请求/结果契约
|  |  |- structured.py              JSON/PO/CSV/XLIFF 结构化适配器
|  |  `- registry.py                适配器注册和引擎选择
|  |- structured_workflow.py        结构化会话和六阶段工作流编排
|  `- hanengine/
|     |- adapter_runtime.py        AdapterV1 注册、检测和操作调用
|     |- auth.py                    本地账户、密码哈希和会话
|     |- routing.py                 HanGuard 风险等级和最终路线
|     |- tasks.py                   HanTask 状态、事件、检查点和取消
|     |- store.py                   HanStore SQLite 和项目写入租约
|     |- pipeline.py                HanPipelineV1 翻译、断点续跑和重试
|     |- renpy.py                   Ren'Py 提取、占位符校验、`tl/` 翻译、语言激活和字体组写出
|     |- validation.py              授权项目验证、官方验证器、字体和冒烟证据
|     |- multiengine.py             多引擎结构化资源读写
|     |- backup.py, packaging.py    备份、恢复和未加密 ZIP 副本处理
|     |- translation.py, tts.py     本地/云翻译和 TTS 路由
|     |- visual.py                  OCR 稳定性判断和视觉替换会话
|     |- visual_style.py            VisualStyleProfile、硬性视觉门槛和可插拔 VisualJudge 契约
|     |- visual_evidence.py         A/B 截图清单、哈希校验、视觉报告和外部判官边界
|     `- renpy_visual_capture.py    Ren'Py 影子项目成对截图采集和运行报告
|- desktop/
|  |- electron/main.cjs             窗口、登录会话、Python 子进程和 IPC
|  |- electron/preload.cjs          最小化 contextBridge
|  `- src/App.tsx                   登录、普通/专业工作区和任务中心
|- examples/engine_samples/         多引擎合成样例
|- tests/                           契约、适配器、工作流、验证和前端相关测试
`- docs/                            状态、验证、合规和设计文档
```

## 3. 关键参数

| 参数 | 当前含义 | 约束 |
| --- | --- | --- |
| `--mode` | `studio` 或 `player` | 普通 GUI 使用 `player`，专业 GUI 使用 `studio` |
| `--risk-level` | 专业默认 `H0_PROJECT`，普通默认 `H1_OFFLINE` | 最终权限仍由 HanGuard 和适配器能力共同决定 |
| `--state-root` | HanStore、任务、检查点和项目状态目录 | 建议每次真实验证使用独立目录 |
| `--output` | 独立候选输出目录 | 不能是源项目或源项目子目录 |
| `--dictionary` | UTF-8 JSON 精确匹配字典 | 字典命中优先于云翻译 |
| `--authorized` | 项目验证授权确认 | `project validate` 必须显式提供 |
| `--authorization-reference` | 授权依据的可脱敏引用 | 不写入私密令牌或项目内容 |
| `--renpy-sdk` / `--validator` | 官方编译器或验证器 | 成功执行前最多只能得到 `build_ready` |
| `--font` | 一个或多个 `.ttf`/`.otf` | Ren'Py 会按顺序打包字体、生成 `FontGroup` 并检查译文 Unicode 覆盖 |
| `--runtime-smoke` | `not_run`、`passed`、`failed` | `passed` 必须带稳定引用 |
| `--language` | 目标语言，默认 `zh-CN` | Ren'Py 输出标识符为 `zh_cn` |
| `renpy_font_paths` | 内部 `BuildRequest.output_options` 字段 | 由验证工作流从 `--font` 生成，不是用户 CLI 参数 |
| `HANENGINE_PYTHON` | Electron 调用的 Python 可执行文件 | Windows 默认使用 `python` |
| `HANENGINE_GAME_LANGUAGE` | HanEngine 客户端启动游戏时传递的语言模式 | `zh_cn` 启动中文；`source` 清除 Ren'Py 语言偏好后启动原文；仅由客户端启动生效 |
| `visual prepare` | 从已验证采集报告和人工区域标注生成 v2 manifest | 必须显式提供 `--authorized`；输入、输出和证据图片必须位于同一证据目录 |
| `visual verify` | 对成对截图运行硬门和可选外部判官 | 必须显式提供 `--authorized` 和 `--authorization-reference` |
| `visual capture-renpy` | 按声明式计划采集原文/候选 PNG | 只在临时影子项目中运行，输出目录必须为空 |
| `observation_source` | 区域观察来源：`renderer`、`ocr` 或 `manual` | 人工标注不能伪装成自动检测 |

常用验证命令：

```powershell
python cli.py engine inspect renpy <project> --json --mode studio --state-root <state>
python cli.py engine extract renpy <project> --output <catalog> --mode studio --state-root <state>
python cli.py project validate renpy <project> `
  --output <output> `
  --dictionary <dictionary> `
  --state-root <state> `
  --record <record> `
  --record-id <record-id> `
  --project-label <label> `
  --authorized `
  --authorization-reference <reference> `
  --renpy-sdk <renpy.exe> `
  --font <font.ttf> `
  --runtime-smoke passed `
  --runtime-smoke-reference <smoke-reference>
```

## 4. 未解决问题

### 无感汉化闭环

- Ren'Py 当前生成的是原生 `translate <language>` 文件，并通过 `config.default_language` 在首次运行默认启用目标语言。由 HanEngine 客户端启动时，`HANENGINE_GAME_LANGUAGE=source` 会清除本次原文启动所需的 Ren'Py 语言状态；`zh_cn` 显式选择中文。
- 原文/中文切换入口已放在 HanEngine 客户端设置和启动按钮中，不在游戏内添加语言菜单。用户直接双击游戏可执行文件时不经过该客户端控制，仍遵循候选默认值和 Ren'Py 自身偏好。
- `The Question` 已通过 `visual capture-renpy` 确认主菜单、对白、分支、设置、保存和读取页面；旧的固定坐标一次性脚本不再承担本轮证据。
- v11 正式记录携带构建、编译、字体以及原文/中文双模式六场景运行时引用，当前图形环境补证已完成。截图文件名不单独承担页面语义断言，证据由报告中的 `expected_screen` 结果、PNG 哈希、报告哈希和候选树哈希共同约束。
- `visual capture-renpy` 已用 Ren'Py 引擎级 screen 探针阻止错页截图被误判为对齐，并用 `PrintWindow` 降低桌面前台程序干扰。声明式动作仍使用相对坐标，计划需要为目标项目校准并由 `expected_screen` 验收；renderer/OCR 自动观察仍未接入。
- 当前没有配置实际 AI 服务；`CommandImageVisualJudge` 只提供无 shell 的外部命令边界，r7 报告因此按设计为 `escalate`，而不是视觉质量 `pass`。

### 文本覆盖和语境

- 当前 Ren'Py 提取器覆盖明文对白、旁白、菜单、屏幕控件以及同一行多个直接 `_()` 字符串字面量；复杂运行时拼接和复数语法仍需加强，`{#...}` 文本上下文标记已纳入 Segment V2 metadata。
- 结构化适配器会把中文目标中“源文等于译文”的明显英文自然语言标记为非阻断性 `untranslated_natural_language` 告警；客户端将其显示为“需检查”。单个标识符、缩写、路径、变量和产品品牌不按此规则误报。
- Ren'Py 运行时对重复 `old` 文本存在全局冲突；当前写出器保留首个译文，已有上下文元数据仍需在写出阶段转化为更精确的语境策略。
- 目前段模型还没有完整保存字体、控件尺寸、换行约束和动画上下文，无法单独保证长中文译文不溢出。
- 字体回退目前只按本次译文实际码点生成显式映射，最后一个字体承接其他运行时文本；动态生成的新字符仍需专门的回退/缺字回归测试。

### 范围和验证

- “任何游戏”不能由一个通用文本替换器保证。明文脚本、动态文本、图片文字、视频字幕、加密封包和受保护运行时必须分级处理。
- RPG Maker、Godot、Unity、Unreal 尚缺少与 Ren'Py 同等级别的真实授权项目 `verified` 记录。
- 图片/视频内嵌文字、复杂动态文本和专有封包不属于当前原生适配范围。
- 本次真实验证使用机械测试字典，仍需真实译文、术语表、人工审校和长文本布局回归。
- 已建立仓库自有的文件型 Ren'Py golden corpus manifest，首批 4 个合成 fixture 覆盖对白、菜单、屏幕控件、`_()`、上下文标签、富文本、嵌套插值和重复原文；该 corpus 只证明结构/构建契约，不代表真实项目或中文质量权威。
- 已登记官方 Ren'Py `The Question` 简体中文样例的固定版本和文件哈希，但没有把第三方样例译文复制进 golden corpus；该来源可证明官方项目行为和来源链，不能替代人工语言质量审校。
- 已使用登记来源在隔离候选中生成本地 `zh_cn` 翻译：目录覆盖率为 242/242，v11 内部验证通过且仅剩 2 个非阻断告警（作者署名、语言名称），Ren'Py SDK `8.5.3.26051504` 编译退出码为 0；字体已实际打包且联合覆盖通过。原文/中文客户端模式均完成六场景 runtime smoke，候选树与验证记录一致。
- 本轮已完整执行 Ren'Py、结构化适配、视觉采集、视觉证据、视觉样式和项目验证六个相关测试模块，共 92 项通过；其中包含客户端语言环境传递和字体覆盖回归。完整工作区 Python `python -m unittest discover -s tests` 此前已完成 479 项，其中 475 项通过、3 项失败、1 项错误。

### 桌面端和发布

- 封包页面、单文件结果统计和部分高级工作流仍需补齐。
- Electron 任务取消、重试、恢复、错误状态和多尺寸窗口仍需端到端回归。
- Windows 安装包尚未完成干净机器安装测试，npm 依赖版本也需要固定。

## 5. 下一步建议

### P1.1：Ren'Py 无感汉化闭环

1. [已完成] 增加目标语言激活策略：候选首次运行默认中文，HanEngine 客户端提供原文/中文启动控制，不在游戏内增加语言菜单，并将激活文件纳入验证清单；官方 Ren'Py 项目的两个客户端模式均已完成六场景实际启动和截图验证。
2. [已完成第一阶段] 扩展 Ren'Py 提取器：已覆盖 `_()`、常见屏幕文本控件、有效 `menu:` 一级选项、同一行多个直接字符串字面量、嵌套动态表达式和富文本标签校验；通用结构化适配器与 Ren'Py AdapterV1 现在共享平衡占位符扫描和标签顺序校验；复数语法及运行时拼接仍需补齐。
3. [已完成第一步] 在现有 Segment/SegmentDraft metadata 中冻结 Segment V2 最小契约：`schema_version=2`、占位符、富文本标签、原始换行序列和 speaker/kind/文本上下文键/前后语境；契约会校验 metadata 与段字段一致，Ren'Py `{#...}` 文本上下文键已纳入提取。官方文档未发现独立通用的 Ren'Py 复数翻译语法，暂不虚构支持。
4. [已完成] 已建立文件型 Ren'Py golden corpus manifest、4 个仓库自有合成 fixture，以及官方 `The Question` 本地参考源登记；四个 fixture 均通过 Ren'Py SDK 8.5.3 编译（退出码 0、无 traceback）。官方样例中文候选已完成真实运行时启动和主菜单、对白、分支、保存、读取、设置页面的截图回归，动态 UI 文本显示正常；v8 记录的稳定运行时引用中包含 r7 报告 SHA-256 和候选指纹。
5. [已完成第一步] Ren'Py 候选已打包多字体并生成 `FontGroup`，真实样例未再出现方框。下一步补充长中文文本、文本框溢出、动态生成字符缺字、多字体回退和无法翻译时保留原文的自动化测试。
6. [进行中] 视觉档案、截图比较、硬门报告和判定结果已支持严格 JSON 往返；A/B PNG 清单、哈希校验、外部判官边界、Ren'Py 影子项目成对采集器和受控人工标注准备流程已完成。官方样例 v11 已完成原文/中文双模式六场景 `6/6 + 6/6` 语义对齐，保存/读取页已用空存档重采并通过人工检查；视觉判官最终仍为 `escalate`，因为实际 AI 服务尚未接入，renderer/OCR 自动观察和 Unity/TMP 资源构建也尚未接入。

### P1.2：统一“原生渲染替换”能力

1. 为每个适配器定义 `native_text_replace`、`dynamic_text`、`raster_text`、`detect_only` 能力。
2. 所有引擎优先写回原生本地化格式，不使用字幕叠加或进程注入。
3. 对无法原生替换的内容生成清晰的未处理清单和原因。

### P2：扩展真实项目认证

1. 为 RPG Maker、Godot、Unity、Unreal 分别准备合规的真实项目、官方工具、字体和运行冒烟环境。
2. 每个引擎至少形成一份脱敏 `verified` 记录和版本兼容性报告。
3. 建立跨引擎 golden corpus，比较提取覆盖率、占位符完整性、编译结果和运行画面。

### P3：资源和发布质量

1. 将 OCR/图片重绘/视频字幕作为独立能力，继续受 HanGuard 门控，不与原生文本替换混淆。
2. 完成桌面端端到端测试、安装包、升级、回滚和多窗口尺寸回归。
3. 固定依赖版本，执行干净机器构建和安装验证。

## 当前结论

HanEngine 已具备多引擎 AdapterV1 基础、Ren'Py 真实项目 `verified` 闭环、自动语言激活和字体随候选包交付的第一版实现。本轮已将语言入口迁移到 HanEngine 客户端，并把“目录有目标值”与“译文完整”分开表示；明显未翻译英文会进入待检查队列，v10 已修复可见的无障碍说明和测试分支漏译。v11 已独立完成官方编译以及原文/中文双模式六场景运行验证，保存/读取页也已用全新空存档重采；候选指纹和输出树与 v10 基线完全一致，最终记录结论为 `verified`。下一步是补齐长文本布局、动态缺字、多字体回退和可审计的自动视觉观察。
