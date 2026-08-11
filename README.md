# HanEngine 多引擎本地化工具

HanEngine 是一个本地优先的多引擎游戏本地化工具。它面向你合法拥有或已获授权的明文项目资源，使用统一的 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard 边界完成检测、提取、翻译、校验、独立构建与验证。

当前产品范围覆盖 Ren'Py、RPG Maker MV/MZ、Godot、Unity 和 Unreal Engine。具体项目是否可构建由资源形态、适配器成熟度和 HanGuard 最终决策共同决定；检测到加密、DRM、二进制封装或未授权资源时，工具只会报告限制，不会解包、破解或修改它们。

当前完成度、支持矩阵、关键参数和后续优先级见 [项目状态](docs/project-status.md)，逐资源能力边界见 [引擎资源矩阵](docs/engine-resource-matrix.md)。这些文档与本 README 是当前产品范围的权威来源；历史计划和 RenpyThief 分析只用于保留设计演进与研究证据。

仅用于合法拥有或已获授权的游戏资源；不支持破解、解密、绕过保护或用于传播盗版内容。

## 快速开始

示例文件位于 `examples/`。运行后会匹配四个字典条目，`Options` 会作为未匹配条目写入待翻译清单。

```powershell
python cli.py examples/game.json examples/dictionary.json
python cli.py game.csv dictionary.json --output translated.csv
python cli.py game.txt dictionary.json --untranslated todo.json
python cli.py engine inspect auto "C:\Games\AuthorizedProject" --json --mode player
python cli.py engine extract rpg_maker_mv "C:\Games\AuthorizedProject" --output catalog.json --mode studio
python cli.py engine build rpg_maker_mv "C:\Games\AuthorizedProject" catalog.json --output build --dictionary dictionary.json --mode studio
python cli.py engine localize auto "C:\Games\AuthorizedProject" --output build --dictionary dictionary.json --mode player
python cli.py project validate renpy "C:\Games\AuthorizedProject" --output build --dictionary dictionary.json --state-root state --record validation.json --record-id project-001 --project-label authorized-project --authorized --authorization-reference internal-ticket-1234
python cli.py renpy extract "C:\Games\AuthorizedProject" --output catalog.json
python cli.py renpy build "C:\Games\AuthorizedProject" catalog.json --output build --dictionary dictionary.json
python cli.py package game.zip patch.json --output game.localized.zip
python -m unittest discover -s tests -v
```

启动桌面端：

```powershell
cd desktop
npm install
npm run dev
```

命令行的 `--output` 用于指定汉化资源输出位置，`--untranslated` 用于指定待翻译 JSON 清单的位置。运行 `python cli.py --help` 可查看参数说明和授权提示。桌面图形界面统一使用 `desktop/` 下的 Electron + React 应用：开发时运行 `npm run dev`，构建前端运行 `npm run build`，生成 Windows 安装包运行 `npm run dist`。

桌面端默认使用“普通”模式，面向单个游戏的一键汉化流程；“专业”模式用于手动提取、目录编辑、构建、封包和任务控制。界面标签使用“普通/专业”，内部仍分别映射到 Python CLI 的 `player/studio`，以保持后端和 CLI 兼容。普通模式只在 AdapterV1 与 HanGuard 同时允许 `extract`、`validate`、`build`、`verify` 时开放一键汉化。

桌面端首次启动会创建本地账户数据库并显示建号界面，后续通过用户名和密码登录。密码采用 PBKDF2-SHA256 加盐哈希，原始密码只通过子进程 stdin 传递；会话令牌只以哈希形式进入 SQLite，原始令牌仅保留在 Electron 主进程内存中。此功能是单机身份门控，不是云账号或跨设备同步服务。

## 引擎检测与能力门控

可先对你合法拥有或获明确授权的游戏项目目录进行只读检测：

```powershell
python cli.py engines
python cli.py detect "C:\Games\AuthorizedProject"
python cli.py detect "C:\Games\AuthorizedProject" --json
```

传统 `detect` 命令只扫描文件名和目录结构，用于快速识别 Ren'Py、RPG Maker MV、RPG Maker MZ、Godot、Unity 与 Unreal Engine 的证据；它不会读取或解析资源内容。`engine inspect` 会进一步创建只读的 AdapterV1 检测任务，并返回引擎、证据、能力、HanGuard 允许操作和 `ready`/`detect_only` 状态。

AdapterV1 当前为以下**明文原始项目**提供结构化提取、翻译、校验、独立构建与验证链路：Ren'Py 的 `.rpy`，RPG Maker MV/MZ 的 JSON，Godot 的 PO/CSV，Unity 的 XLIFF/CSV，以及 Unreal 的 PO。旧的 `renpy extract/build` 命令继续保留兼容。Unity Player、Unreal Pak/IoStore、Godot PCK、Ren'Py 归档及其他加密或二进制封装资源均为仅检测，绝不会被自动解包或修改。

原有的单文件翻译命令仍然可用，例如 `python cli.py game.json dictionary.json`；它们仅面向前述受支持的明文资源，且同样只应处理你拥有合法权利或已获授权修改的内容。

## HanEngine

HanEngine 不改变现有单文件翻译器的使用方式。当前实现包括：

- 多引擎 AdapterV1：Ren'Py、RPG Maker MV/MZ、Godot、Unity 和 Unreal 的检测、结构化资源提取、占位符保护、独立构建与验证；封装资源按引擎统一降级为仅检测。
- Ren'Py 明文 `.rpy` 对白、旁白和菜单已接入 HanPipelineV1 一键链路，生成独立 `game/tl/<language>/` 输出并校验源项目指纹、占位符、UTF-8、产物哈希和生成结构。`project validate --renpy-sdk` 可显式调用外部 SDK 编译器；仓库当前没有实际 SDK 编译或游戏运行冒烟认证记录。
- P1 项目验证运行器：`project validate` 强制授权确认并生成脱敏 JSON 证据；完整记录源树保护、候选哈希、任务链、HanGuard、官方验证器、字体覆盖和运行冒烟状态，缺少外部证据时只标记为 `build_ready`。
- OCR 原位置视觉替换；连续三帧稳定且 OCR 置信度足够时才绘制覆盖层，不注入游戏进程、不读取内存，也不保存原始截图。
- 本地字典和显式启用的云翻译路由；云请求只发送文本、语言与文本上下文，令牌仅从运行时环境读取。
- HanPipelineV1 多引擎流水线；按段把译文和恢复检查点原子写入 HanStore，中断后重新执行只翻译未完成段。
- Windows SAPI 本地 TTS 和可选的云 TTS 接口，输出经过 WAV 格式检查后原子写入。
- 普通未加密 ZIP 的独立副本修改；拒绝加密条目、路径穿越、重复路径、`.rpa`、`.rpyc` 和其他专有封包。
- 文件哈希备份、失败自动恢复和显式回滚；原地应用需要最终 HanGuard 路由授权。
- 普通/专业双模式 Electron + React GUI，以及保留兼容性的单文件页面。
- 本地用户数据库、首次建号、登录和退出；未登录渲染进程不能调用项目扫描、catalog、Python 工作流或任务控制 IPC。

检测命令仍是只读的 Phase 1 适配器能力，不会因为上述显式工作流而自动修改任何项目。GUI 的 ZIP 工作流只生成独立副本；CLI 原地应用还必须同时传入 `--apply --authorized --backup-root`。

云翻译服务需实现以下 JSON 契约：请求字段为 `text`、`source_language`、`target_language`、`context`；响应字段为 `translation`，并可包含 `provider`、`model`、`confidence`。示例：

```powershell
$env:HANENGINE_TRANSLATION_TOKEN = "runtime-only-token"
python cli.py cloud-translate "New Game" --endpoint https://translate.example/api --target zh-CN
python cli.py engine localize auto "C:\Games\AuthorizedProject" --output build --dictionary dictionary.json --cloud-endpoint https://translate.example/api --translated-catalog translated.json
python cli.py tts "你好" --output voice.wav --language zh-CN
```

`engine localize` 依次执行检测、提取、翻译、校验、构建和验证。字典提供方优先，字典未命中的段才发送到显式配置的云端点。默认状态目录位于 `%LOCALAPPDATA%\HanEngine`；也可通过 `--state-root` 指定。再次运行会复用源指纹、上下文指纹和目标语言均匹配的已完成段；`--no-resume` 会强制重译，`--translated-catalog` 可额外导出完整翻译目录。`engine build` 也接受相同的翻译和恢复参数。

六个适配器验收样例（Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal）位于 [`examples/engine_samples`](/C:/Users/23256/Documents/汉化/.worktrees/game-localizer/examples/engine_samples)。每个样例都保留真实项目标记和明文本地化资源，并附带可直接用于 GUI 或 CLI 的中文测试字典；样例说明同时列出了公开案例入口。仓库只分发原创 fixture，不自动下载或再分发这些案例的游戏资产。

HanTask Center 会持久化任务阶段、逐段进度、最近检查点、HanGuard 决策、失败原因和产物。GUI 的“任务”页可刷新详情、取消运行中任务并重试可恢复任务；CLI 提供相同控制面：

```powershell
python cli.py tasks list
python cli.py tasks show <task-id>
python cli.py tasks retry <task-id>
python cli.py tasks cancel <task-id>
```

使用自定义状态目录时，为上述命令追加 `--state-root <path>`。取消是跨进程的协作式请求，运行任务会在检查点停止；应用异常退出后，`tasks retry` 会把没有有效项目租约的遗留运行任务标记为中断并从已持久化段继续。云端点和令牌环境变量名可以进入重试描述，但令牌值不会持久化；恢复云任务时会从当前进程环境重新读取。每个项目只有一个结构化工作流写入租约，因此两个 CLI/GUI 构建不能同时写入同一项目。

视觉替换需要本机安装 Pillow、pytesseract 和 Tesseract OCR；缺少依赖时会停止并显示错误，不会降级为底部字幕。

可运行以下发布门禁：

```powershell
python tools/generate_benchmark_manifests.py --check
python -m unittest discover -s tests -v
```

只处理你合法拥有或已获明确授权的资源；本项目不提供破解、解密、DRM 绕过、注入、内存钩子或协议拦截能力。`benchmarks/LICENSE` 的 CC0-1.0 仅适用于仓库自有的合成基准内容；仓库根许可证仍为未决状态，且不包含第三方代码或资产。

## 翻译字典

字典必须是 UTF-8 编码的 JSON 对象：键是原文，值是简体中文译文。例如：

```json
{
  "New Game": "新游戏",
  "Hello, {name}!": "你好，{name}！"
}
```

也就是 `{ "原文": "中文" }` 的格式。键和值都必须是字符串，键不能是空字符串。字典和资源 JSON 都拒绝重复对象键；资源 JSON 还拒绝非有限数和不能安全保持的数值。项目提供的 `examples/dictionary.json` 以英文→简体中文为主，并保留一个日文条目，方便确认多语言字典兼容性。

请保留原文中的占位符，例如 `{name}`、`{0}`、`%1`、`%s` 与换行标记 `\\n`。工具会报告译文缺少的占位符，但不会自动修复；请在交付前人工核对所有警告。

## 支持的资源与输出

只处理以下**明文**资源扩展名：`.txt`、`.ks`、`.rpy`、`.script`、`.csv`、`.json`。输入会依次识别 UTF-8 BOM、UTF-8、CP932 和 Shift-JIS；无论输入编码为何，输出一律为无 BOM 的 UTF-8。

默认情况下，工具不会覆盖源文件：

- `game.json` 会生成 `game.zh.json`
- 同时生成 `game.untranslated.json`，其中包含可补充进字典的未翻译原文

汉化文件和待翻译清单会作为一对事务写入：对可捕获的写入错误或中断会尽力回滚两者，避免只更新其中一个；不承诺强制终止或断电安全。重新执行可覆盖已有输出；本次实际覆盖的每个目标都会在 CLI 和 GUI 日志中逐项提示。

对于 JSON，仅翻译字符串值，绝不改动对象键；CSV 按完整单元格精确匹配；纯文本按最长键优先进行单次行内替换。除显式支持的普通未加密 ZIP 副本工作流外，二进制、加密、受保护或需要反编译的游戏资源不在支持范围内。

## 本地与授权限制

默认处理在本机完成。只有显式执行 `cloud-translate` 或使用云提供方时才会访问用户指定的 HTTPS 服务；云翻译不发送截图，运行时令牌不会写入 SQLite、JSON、日志或导出包。请仅处理你拥有合法权利或明确授权修改的资源。使用本工具不提供破解、解密、规避 DRM、进程注入、内存读取、渲染 Hook 或协议拦截的能力或指导。
