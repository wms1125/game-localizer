# HanEngine 项目状态

更新时间：2026-08-08

本文是 HanEngine 当前范围、能力矩阵和开发优先级的权威说明。HanEngine 的长期目标是通过统一适配器覆盖主流游戏引擎，而不是只适配 Ren'Py。新引擎和新资源格式必须接入 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard；不得绕过资源格式验证、授权边界或能力门控。

“目标覆盖主流引擎”不等于对所有版本、所有资源格式和所有成品游戏作出可修改承诺。每项能力必须按引擎、资源形态、版本和真实授权项目验证结果分级为“仅检测”“可提取”“可构建”或“已验证”。

## 1. 已完成内容

### 多引擎运行时

- 已建立 AdapterV1 契约、注册表和运行时，统一 `detect`、`extract`、`validate`、`build`、`verify`、`rollback` 的输入输出、证据、错误和能力模型。
- 已接入首批主流引擎适配：Ren'Py、RPG Maker MV、RPG Maker MZ、Godot、Unity、Unreal Engine；旧检测层继续保留兼容识别。
- 已实现 `engine inspect`：以只读任务返回引擎选择、检测证据、适配器能力、HanGuard 最终允许操作和 `ready`/`detect_only` 状态。
- 已实现 `engine localize`：检测、提取、字典/云翻译、逐段检查点、校验、独立构建和验证的可恢复流水线。
- 已实现结构化资源读写：Ren'Py 明文 `.rpy`、RPG Maker MV/MZ JSON、Godot PO/CSV、Unity XLIFF/CSV、Unreal PO。输出始终是原项目之外的独立副本。
- Ren'Py 已接入 AdapterV1、HanPipelineV1、HanGuard、HanTask 和普通模式一键链路；支持对白、旁白、菜单、源指纹、占位符、UTF-8、产物哈希和生成结构校验。旧 `renpy extract` / `renpy build` 命令继续作为兼容入口保留；当前不宣称通过 Ren'Py SDK 编译或游戏运行验证。

### 翻译、任务与安全

- HanPipelineV1 支持本地 UTF-8 JSON 精确字典、可选云翻译路由、占位符保护、逐段持久化、断点续跑和失败后重试。
- HanStore 使用全局索引 SQLite 加每项目 SQLite 数据库存储项目、段、任务、步骤、事件、检查点、产物、取消请求、重试描述和项目写入租约。
- CLI 任务中心已支持 `tasks list`、`tasks show <task-id>`、`tasks retry <task-id>`、`tasks cancel <task-id>`。
- HanGuard 根据风险等级与适配器能力的交集决定最终路线。一键本地化必须同时允许 `extract`、`validate`、`build`、`verify`。
- 普通模式拒绝把输出目录设为原项目目录或其子目录；同一项目使用写入租约，避免两个构建任务并发写入。
- 后端已实现普通未加密 ZIP 的独立副本修改、哈希备份、失败恢复和显式回滚。它拒绝加密条目、路径穿越、重复路径和不支持的专有封包。
- 后端已实现 OCR 视觉替换和 TTS：OCR 仅在连续三帧稳定且置信度合格时覆盖文字，原始截图不持久化；支持 Windows SAPI 和可选云 TTS。

### Electron + React 桌面端

- 旧 Tkinter 入口 `gui.py` 和对应 GUI 测试已删除，桌面端唯一目标是 `desktop/`。
- Electron 主进程保持文件系统和 Python 子进程边界；渲染进程使用 React + TypeScript，启用 `contextIsolation`、禁用 `nodeIntegration`，通过 preload 暴露最小 IPC。
- 已实现本地账户数据库和登录门控：首次启动创建账户，支持登录与退出；密码使用 PBKDF2-SHA256 独立盐值，原始密码仅通过 stdin 交给 Python，SQLite 只保存密码哈希和会话令牌哈希，原始令牌仅驻留 Electron 主进程内存。未认证渲染进程不能访问项目、catalog、Python 工作流和任务控制 IPC。
- 默认模式为“普通”，内部映射为 CLI `player`；“专业”映射为 `studio`。普通模式不暴露 catalog、风险参数和专业操作。
- 普通模式实现四步一键汉化：选择游戏目录、自动检测、选择本地字典、选择项目外输出目录，然后运行 `engine localize auto ... --mode player`。
- 任务中心已接入 `tasks:list`、`tasks:show`、`tasks:retry`、`tasks:cancel`，显示任务阶段、进度、最近检查点、HanGuard 决策、失败原因和产物，并支持取消、重试和重启后恢复。
- 专业模式保留项目树、catalog 表格编辑、手动提取和构建入口；主进程对 catalog 保存采用临时文件后原子重命名。

### 验证与样例

- 已提供可再分发的六个适配器合成样例：Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal，位于 `examples/engine_samples/`，并附带字典和公开案例参考。
- 已验证 RPG Maker MV 和 Ren'Py 合成样例从 `engine localize auto` 到独立输出的完整流程，并产生检测、提取、翻译、校验、构建、验证的持久化任务；其余适配器也由样例验收测试覆盖。
- P1 验证代码闭环已完成：新增 `project validate` 授权门控命令，统一运行六阶段 AdapterV1 工作流，记录完整源树/候选树哈希、Adapter 与 HanGuard 证据、任务链、构建清单和内部验证结果，并支持官方验证器、字体 Unicode 覆盖和运行冒烟引用。
- 六个合成样例均已通过验证运行器并得到 `build_ready`；只有内部验证、官方验证器、字体覆盖和运行冒烟全部通过且外部验证器不修改候选树时，记录才会升级为 `verified`。真实授权项目认证仍需项目持有人提供项目和外部工具环境。
- 最近一次 Python 全量回归：432 项测试通过。
- 最近一次前端生产构建：`desktop/` 下 `npm run build` 成功。
- 最近一次 `git diff --check` 通过。

## 2. 当前代码结构

```text
game-localizer/
|- cli.py                         CLI 总入口：认证、单文件、Ren'Py、engine、tasks、package、cloud、tts
|- translator.py                  兼容的单文件明文翻译器
|- game_localizer/
|  |- adapters/                   旧检测适配器、AdapterV1 契约、结构化多引擎适配器
|  |- structured_workflow.py      结构化工作流会话、项目 ID、任务状态根目录
|  `- hanengine/
|     |- adapter_runtime.py        AdapterV1 注册、检测选择、操作编排
|     |- core.py                   HanCore 授权和段接收门面
|     |- auth.py                   本地用户 SQLite、密码哈希与会话校验
|     |- routing.py                HanGuard、RoutePlan、风险等级和操作权限
|     |- tasks.py                  HanTask 状态机、事件、检查点、协作取消
|     |- store.py                  HanStore SQLite、项目租约、任务状态查询
|     |- pipeline.py               HanPipelineV1 翻译、断点续跑、逐段持久化
|     |- validation.py             授权项目验证运行器、JSON 证据、官方验证器与字体覆盖
|     |- multiengine.py            JSON/PO/CSV/XLIFF 多引擎资源提取与独立写回
|     |- renpy.py                  Ren'Py 明文目录与 tl/ 输出
|     |- backup.py, packaging.py   备份、恢复和普通未加密 ZIP 修改
|     |- translation.py, tts.py    本地/云翻译路由与 TTS 提供方
|     `- visual.py                 OCR、稳定性判断和视觉替换会话
|- desktop/
|  |- electron/main.cjs           BrowserWindow、登录会话、文件操作、Python 子进程与 IPC
|  |- electron/preload.cjs        最小化 contextBridge API
|  `- src/App.tsx                 登录、普通/专业工作区、任务中心和命令映射
|- examples/engine_samples/       多引擎合成验收样例
|- tests/                         Python 单元、契约、工作流与样例验收测试
`- docs/                          当前状态、设计、历史计划、合规和分析记录
```

### 当前引擎能力矩阵

| 引擎 | 已实现的明文项目资源 | 当前流程 | 封装或二进制形态 |
| --- | --- | --- | --- |
| RPG Maker MV/MZ | `data/*.json` | AdapterV1 一键链路 | 加密或专有封包仅检测 |
| Godot | 原始项目中的 PO/CSV | AdapterV1 一键链路 | `.pck` 仅检测 |
| Unity | 原始工程中的 XLIFF/CSV | AdapterV1 一键链路 | Player、Asset 二进制仅检测 |
| Unreal | 原始工程中的 PO | AdapterV1 一键链路 | `.pak`、`.ucas`、`.utoc` 仅检测 |
| Ren'Py | 明文 `.rpy` | AdapterV1 一键链路；旧命令兼容 | `.rpa`、`.rpyc` 仅检测 |

“一键链路”表示代码层具备检测、提取、翻译、校验、独立构建和验证路径，不表示所有版本、插件或商业项目已经完成真实授权项目认证。

## 3. 关键参数

| 参数或配置 | 默认值或含义 | 约束 |
| --- | --- | --- |
| `--mode` | `studio`；普通 GUI 固定传 `player`，专业 GUI 传 `studio` | 普通/专业是界面术语，不向普通用户展示内部值 |
| `--risk-level` | 专业默认 `H0_PROJECT`，普通默认 `H1_OFFLINE` | 最终权限仍由 HanGuard 规则和证据决定 |
| `--state-root` | `%LOCALAPPDATA%\HanEngine`；不可用时回退 `~/.hanengine` | 保存 HanStore 数据、任务和检查点；可指定隔离目录 |
| `--output` | 必填 | 普通模式必须位于源项目之外，构建不会覆盖源项目 |
| `--dictionary` | UTF-8 JSON 精确匹配字典 | 优先于云翻译；未命中段才交给显式云端点 |
| `--cloud-endpoint` | 默认无 | 仅显式提供时联网；发送文本、语言和上下文 |
| `--token-env` | `HANENGINE_TRANSLATION_TOKEN` | 只读运行时环境变量，令牌值不写入 SQLite、JSON、日志或重试描述 |
| `--no-resume` | 默认关闭 | 开启后忽略逐段检查点并重新翻译 |
| `--translated-catalog` | 默认无 | 额外导出完成后的 catalog JSON |
| `project validate --authorized` | 无默认值，必须显式提供 | 仅用于合法拥有或已获授权项目；同时要求稳定授权引用和源项目外记录路径 |
| `--validator` / `--renpy-sdk` | 默认无 | 未实际配置并成功运行时，验证记录只能是 `build_ready` |
| `--font` | 可重复，默认无 | 使用字体 cmap 检查译文 Unicode 覆盖；未配置时不能升级为 `verified` |
| `--runtime-smoke` | `not_run` | `passed` 只接受带稳定引用的外部或人工冒烟证据 |
| `HANENGINE_PYTHON` | Windows 默认 `python` | Electron 启动 CLI 时可指定 Python 可执行文件 |

常用命令：

```powershell
python cli.py engine inspect auto "C:\Games\AuthorizedProject" --json --mode player
python cli.py engine localize auto "C:\Games\AuthorizedProject" --output "D:\Localized\Game" --dictionary dictionary.zh-CN.json --mode player
python cli.py project validate renpy "C:\Games\AuthorizedProject" --output "D:\Localized\Game" --dictionary dictionary.zh-CN.json --state-root "D:\HanEngine\state" --record "D:\HanEngine\records\project-001.json" --record-id project-001 --project-label authorized-project --authorized --authorization-reference internal-ticket-1234
python cli.py tasks list
python cli.py tasks show <task-id>
python cli.py tasks retry <task-id>
python cli.py tasks cancel <task-id>
```

## 4. 未解决问题

- **真实项目认证资料尚未产生。** 六个适配器已有合成样例、验证运行器和结构化证据格式，但仍需获得授权的 MV/MZ、Godot、Unity、Unreal、Ren'Py 原始项目及对应官方工具环境，才能产生真实的 `verified` 记录和版本兼容性报告。
- **Ren'Py SDK 尚未在仓库环境实际执行。** `project validate --renpy-sdk` 已接入 `<launcher> <candidate> compile` 调用和退出码记录，但当前没有已配置 SDK、目标字体或游戏运行冒烟结果，因此 Ren'Py 成熟度仍为“可构建”。
- **资源范围有限。** Ren'Py 仅处理明文 `.rpy`，Unity 仅处理 XLIFF/CSV，Unreal 仅处理 PO，Godot 仅处理 PO/CSV，RPG Maker 仅处理明文 JSON；二进制资源、加密资源、运行时注入和专有封包始终不在范围内。
- **前端能力尚未全部兑现。** 封包页面仍是说明占位，单文件翻译缺少结果统计；云翻译、OCR 视觉替换、TTS、备份/回滚虽有后端模块，尚未形成完整 Electron 工作流。
- **发布准备未完成。** `electron-builder` 配置已存在但还未实际产出 Windows 安装包；`package.json` 仍使用 `latest`，发布前应固定依赖版本并执行干净机器安装测试。
- **前端自动化验证不足。** 已完成普通模式截图检查和 Vite 构建，但任务中心取消/重试、错误状态、各窗口尺寸和打包版本仍需端到端回归。
- **P1 基线已按功能分组提交。** 后端基线提交为 `19af039`，Electron + React 桌面端提交为 `2331841`；后续迭代应在这些提交之上继续，并保持测试与验证门禁。

## 5. 下一步建议

### P1：执行真实项目认证

P1 的代码、CLI、证据模式和合成样例回归已经闭环。剩余工作是项目特定的外部认证，不再需要新增引擎旁路：

1. 为 RPG Maker MV/MZ、Godot、Unity、Unreal、Ren'Py 分别准备已授权的真实原始项目、官方工具和目标字体。
2. 按 `docs/authorized-project-validation.md` 执行 `project validate`，在授权环境中完成官方验证和运行冒烟；没有完整证据时不得把“可构建”升级为“已验证”。
3. 将脱敏后的 `verified` JSON 记录用于更新版本兼容性结论；项目内容、私有绝对路径和验证器输出不得提交。

### P2：完成桌面端工作流

1. 将封包页面接入 `cli.py package`，展示独立输出、授权确认、备份位置和回滚结果。
2. 补齐单文件翻译结果统计、未翻译清单入口和产物打开操作。
3. 为云翻译添加专业模式配置界面，只保存端点和环境变量名，不保存令牌；恢复任务时重新读取当前环境。
4. 将 OCR 视觉替换、TTS 和备份/回滚设计为独立受 HanGuard 门控的桌面任务，不以进程注入、内存读取或渲染 Hook 实现。

### P3：发布与质量门禁

1. 固定 npm 依赖版本，执行 `npm run dist`，验证安装包中的 Python 后端资源与 `HANENGINE_PYTHON` 覆盖行为。
2. 增加 Electron 端到端测试和桌面截图回归，覆盖普通/专业模式、任务恢复、取消、重试、禁用状态及 1120x720 和 1440x920 窗口。
3. P1 基线已完成分组提交；后续变更继续按“核心运行时、适配器与样例、桌面端、文档”边界审阅，并在提交前运行对应 Python 测试和 `npm run build`。

## 维护规则

- 不得把任何单一引擎写成 HanEngine 的唯一目标或默认产品范围。
- 新引擎必须先实现 AdapterV1 契约和样例测试，再宣称可提取、可构建或已验证。
- 所有用户可见能力必须准确区分“仅检测”“可提取”“可构建”和“已通过真实授权项目验证”。
- 默认输出始终独立于源项目；加密、DRM、封装二进制、未授权内容、进程注入、内存读写和协议拦截不在支持范围内。
