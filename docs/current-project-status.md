# HanEngine 当前项目状态

更新时间：2026-08-08

本文是当前工作树的阶段性状态摘要。它补充并更新 `docs/project-status.md`，重点记录最近的真实 Ren'Py 项目验证和“无感汉化”目标。这里的“已验证”表示工程流水线、编译、字体和运行冒烟证据完整，不代表机器翻译质量已经达到发布标准。

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

### Ren'Py 适配器修复

- Ren'Py 明文 `.rpy` 已接入 AdapterV1 全流程。
- 已过滤 `id`、`style`、`variant`、`background`、`activate_sound` 等屏幕属性，避免把资源名或控件属性误识别为对白。
- 同一脚本中的重复文本现在会生成唯一段 ID。
- 生成翻译块时按源文本去重，避免 Ren'Py 因重复 `old` 字符串在运行时崩溃。
- `_()` 包装的普通对白、屏幕 `text`、`textbutton` 和 `label` 现在可被提取；屏幕文本按字符串翻译块写出。
- Ren'Py 占位符校验现在支持嵌套 Python 插值表达式和带属性的富文本标签；动态变量可调整顺序，但标签序列必须保持不变。
- 候选输出现在额外写出 `game/hanengine_language.rpy`，使用 Ren'Py 原生 `config.default_language` 在首次运行默认启用目标语言；用户后续通过标准 `Language(...)` 切换的选择由 Ren'Py 偏好持久化。
- 翻译文件和语言激活文件均纳入构建清单、SHA-256 和候选验证；保留激活路径冲突检查，源项目仍不会被修改。
- 官方验证器现在在临时影子目录中运行，Ren'Py 编译产生的 `.rpyc`、`game/cache` 和日志不会污染候选输出，也不会被误判为 HanEngine 修改。

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
|     |- renpy.py                   Ren'Py 提取、占位符校验、`tl/` 翻译和语言激活写出
|     |- validation.py              授权项目验证、官方验证器、字体和冒烟证据
|     |- multiengine.py             多引擎结构化资源读写
|     |- backup.py, packaging.py    备份、恢复和未加密 ZIP 副本处理
|     |- translation.py, tts.py     本地/云翻译和 TTS 路由
|     `- visual.py                  OCR 稳定性判断和视觉替换会话
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
| `--font` | 一个或多个 `.ttf`/`.otf` | 用于检查译文 Unicode 覆盖 |
| `--runtime-smoke` | `not_run`、`passed`、`failed` | `passed` 必须带稳定引用 |
| `--language` | 目标语言，默认 `zh-CN` | Ren'Py 输出标识符为 `zh_cn` |
| `HANENGINE_PYTHON` | Electron 调用的 Python 可执行文件 | Windows 默认使用 `python` |

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

- Ren'Py 当前生成的是原生 `translate <language>` 文件，并通过 `config.default_language` 在首次运行默认启用目标语言；已有 Ren'Py 持久偏好不会被覆盖。
- `Heartfelt Moments` 没有现成语言菜单，因此可见的原文/中文切换入口仍需由桌面端或项目设置页承载；底层 `Language(...)` 切换和状态持久化由 Ren'Py 原生机制提供。
- 当前验证证明了编译和启动，不等同于所有界面路径都已截图确认译文显示。

### 文本覆盖和语境

- 当前 Ren'Py 提取器重点覆盖明文对白、旁白、菜单和部分屏幕文本；复杂 `_()` 包装、运行时拼接和复数语法仍需加强，`{#...}` 文本上下文标记已纳入 Segment V2 metadata。
- Ren'Py 运行时对重复 `old` 文本存在全局冲突；当前写出器保留首个译文，已有上下文元数据仍需在写出阶段转化为更精确的语境策略。
- 目前段模型还没有完整保存字体、控件尺寸、换行约束和动画上下文，无法单独保证长中文译文不溢出。

### 范围和验证

- “任何游戏”不能由一个通用文本替换器保证。明文脚本、动态文本、图片文字、视频字幕、加密封包和受保护运行时必须分级处理。
- RPG Maker、Godot、Unity、Unreal 尚缺少与 Ren'Py 同等级别的真实授权项目 `verified` 记录。
- 图片/视频内嵌文字、复杂动态文本和专有封包不属于当前原生适配范围。
- 本次真实验证使用机械测试字典，仍需真实译文、术语表、人工审校和长文本布局回归。
- 已建立仓库自有的文件型 Ren'Py golden corpus manifest，首批 4 个合成 fixture 覆盖对白、菜单、屏幕控件、`_()`、上下文标签、富文本、嵌套插值和重复原文；该 corpus 只证明结构/构建契约，不代表真实项目或中文质量权威。
- 已登记官方 Ren'Py `The Question` 简体中文样例的固定版本和文件哈希，但没有把第三方样例译文复制进 golden corpus；该来源可证明官方项目行为和来源链，不能替代人工语言质量审校。
- 已使用登记来源在隔离候选中生成本地 `zh_cn` 翻译：228/228 段完成，内部验证通过，Ren'Py SDK `8.5.3.26051504` 编译退出码为 0；`SourceHanSansLite.ttf` + `DejaVuSans.ttf` 联合字体覆盖通过。该记录当前为 `build_ready`，因为运行时冒烟仍未执行。
- 本次代码验证中除外部合规发布扫描外的 407 个 Python 测试均通过；`tools/check_compliance.py --json --release` 在当前环境超时，合规扫描结果仍未完成。

### 桌面端和发布

- 封包页面、单文件结果统计和部分高级工作流仍需补齐。
- Electron 任务取消、重试、恢复、错误状态和多尺寸窗口仍需端到端回归。
- Windows 安装包尚未完成干净机器安装测试，npm 依赖版本也需要固定。

## 5. 下一步建议

### P1.1：Ren'Py 无感汉化闭环

1. [已完成] 增加目标语言激活策略：候选首次运行默认中文，保留原生语言切换和偏好持久化语义，并将激活文件纳入验证清单。
2. [进行中] 扩展 Ren'Py 提取器：已覆盖 `_()`、常见屏幕文本控件、有效 `menu:` 一级选项、嵌套动态表达式和富文本标签校验；通用结构化适配器与 Ren'Py AdapterV1 现在共享平衡占位符扫描和标签顺序校验；复数语法及运行时拼接仍需补齐。
3. [已完成第一步] 在现有 Segment/SegmentDraft metadata 中冻结 Segment V2 最小契约：`schema_version=2`、占位符、富文本标签、原始换行序列和 speaker/kind/文本上下文键/前后语境；契约会校验 metadata 与段字段一致，Ren'Py `{#...}` 文本上下文键已纳入提取。官方文档未发现独立通用的 Ren'Py 复数翻译语法，暂不虚构支持。
4. [进行中] 已建立文件型 Ren'Py golden corpus manifest、4 个仓库自有合成 fixture，以及官方 `The Question` 本地参考源登记；四个 fixture 均通过 Ren'Py SDK 8.5.3 编译（退出码 0、无 traceback）。已完成一个官方样例中文候选的 `build_ready` 验证，下一步执行真实运行时启动和主菜单、对白、分支、存档、设置页面的截图回归。
5. 增加长文本、字体回退、文本框溢出和原文回退测试。

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

HanEngine 已具备多引擎 AdapterV1 基础、Ren'Py 真实项目 `verified` 闭环和自动语言激活的第一版实现。当前最重要的产品缺口不是再增加一个旁路引擎，而是把“原生文本覆盖率、可见语言入口、格式/布局保真和未支持内容分级”继续做成稳定的 P1.1 能力。
