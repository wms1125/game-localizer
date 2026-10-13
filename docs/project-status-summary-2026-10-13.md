# HanEngine 项目状态总结

更新时间：2026-10-14

- 仓库：`C:/Users/23256/Documents/汉化/.worktrees/game-localizer`
- 分支：`codex/game-localizer`
- 验收基线：`441fd7f fix: preserve English table in Addressables builds`
- 最新代码检查点：`0cb7eb9 fix: complete Unity Addressables candidate checkpoint`
- 远端关系：`0cb7eb9` 及其之前的阶段提交已推送到 `origin/codex/game-localizer-checkpoint`；工作树中本任务以外的改动未纳入这些提交。
- 工作树：仍有本任务以外的大量未提交和未跟踪改动；本摘要只记录检查到的现状，不表示其余改动已提交、推送或全部通过验证。Hello Underworld 与 Unity 往返证据保存在本机 `.tmp/`，不包含在 Git 中。

## 状态概览

HanEngine 已有多引擎结构化文本工作流、Electron 桌面工作台、本地模型翻译接口、任务状态持久化、质量报告和候选验证能力。Ren'Py 与部分 Godot 项目有真实项目验证证据；RPG Maker MV 的 Apache-2.0 Hello Underworld 固定样本已完成 v17 文本、字体和 NW.js 冒烟验收，记录结论为范围限定的 `verified`。本轮也修正了 NW.js 启动冒烟必须绑定栅格清单的限制：纯文本候选可以独立检查标题、开局地图、运行错误和截图；视频检查仍只在显式提供栅格清单时启用。

当前最大的用户流程缺口仍是：没有真实打包 Unity 游戏的合格模型翻译和完整图形运行验收。2026-10-14 已从当前《How to Fish》安装版重新提取 646 条，并使用安装版现有简中表生成完整外部候选；候选通过标准 AdapterV1 构建、回读和 CRC 校验，英文 bundle 字节保持不变。该候选不是模型翻译，且图形启动在本机与未修改安装版都返回退出码 53，未生成 Unity 日志，因此不能记为运行时通过。

### 2026-10-14 增量

- 新增按 `table_name + entry_id` 映射已安装 Unity 简中表的工具 `tools/map_installed_localization_catalog.py`；646/646 条匹配，`Close {0}` 因缺少占位符回退英文并进入人工审阅报告。
- 修复 Unity Addressables 构建在 Windows 长路径下的临时目录问题：临时完整副本改放系统短临时目录；普通 Unity XLIFF/CSV 验证继续回退原有验证器。
- 完整安装版候选位于外部 `.tmp/how-to-fish-installed-chinese-candidate-v3`，质量报告为 `review_required`；只修改简中 bundle 与 `catalog.bin`。

## 已完成内容

### 核心工作流

- 已建立 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard 的统一工作流。
- 已实现引擎检测、结构化文本提取、翻译、占位符校验、独立候选构建、验证、任务持久化、取消、重试和恢复。
- 构建输出默认位于源项目之外；流程记录源树/候选树指纹、文件哈希、编码和生成清单，以避免将候选误认为源项目改动。
- 已支持本地精确匹配字典、回环地址本地模型 Provider、显式云翻译 Provider 和翻译路由。
- 已实现 `hanengine.quality-report/v1` 质量报告，用于记录条目统计、漏译、未处理项、校验阻断项和人工审查原因。
- 已实现图片/视频资源清单、审批和候选合并边界；该能力仍是独立实验范围，不属于 v1 默认文本汉化流程。

### 桌面端

- 桌面端使用 Electron + React；普通模式映射 `player`，专业模式映射 `studio`。
- 已实现本地账户、密码哈希、登录会话门控和受限 IPC；未认证渲染进程不能直接调用项目扫描、Python 工作流或任务控制接口。
- 任务中心支持查看、刷新、取消、重试和重启恢复；质量报告可供桌面端读取并展示摘要。
- 已支持候选启动语言和启动程序配置。普通用户无需先准备字典即可提取文本；没有可用翻译来源时，不会伪造汉化成功。

### 引擎与项目验证

| 引擎/项目 | 当前证据 | 边界 |
| --- | --- | --- |
| Ren'Py | 明文 `.rpy` 支持对白、菜单、静态 screen 文本、部分动态表达式、语言激活与字体构建；官方 The Question 和 Heartfelt Moments 有 `verified` 记录。 | `.rpa`、`.rpyc` 不在明文结构化写回范围。机械测试字典证明工程闭环，不等于语言质量认证。 |
| RPG Maker MV | Hello Underworld Apache-2.0 v15 样本的 v17 候选已记录为 `verified`：审校目录 1,954/1,954 条匹配，未处理项为 0，字体缺失码位为 0，NW.js 0.29.4 检查 23/23 通过。 | 仅覆盖结构化文本、字体和启动冒烟；没有完整游玩、视频或栅格资源验收，标题图仍显示英文 “ASPHODEL”，地图截图为全黑。此结论不代表译文质量认证。 |
| RPG Maker MZ | 支持明文 `data/*.json` 的结构化提取、构建和内部验证。 | 尚无真实授权项目 `verified` 记录。 |
| Godot | 支持 PO/CSV 资源、语言标识规范化、CJK 字体注入及窄范围静态名称发现；Dodge the Creeps 派生项目的 PO 路径有 `verified` 记录。 | `.pck` 只检测；Open RPG 在指定 Godot 4.6.2 下因上游 Dialogic 脚本错误保持 `failed`，不归因于汉化候选。 |
| Unity | 原始工程 XLIFF/CSV；一个严格识别的 Unity Localization 英文/简体中文 Addressables 字符串表 profile 已进入标准 AdapterV1。当前安装版《How to Fish》已提取 646 条，并生成完整外部候选；英文 bundle 保持字节一致，简中 bundle 与 `catalog.bin` 通过回读和 CRC 校验。 | 候选使用游戏现有简中表，不是机器翻译；`Close {0}` 回退英文并需人工审阅。当前机器和未修改安装版图形启动都返回退出码 53，尚无运行时通过证据。旧 v4 专项候选改写了英文表，且 594 条目录指纹已过期。其他 Player/Addressables 布局仍仅检测。 |
| Unreal | 原始工程 PO 有结构化能力和合成样例验证。 | `.pak`、`.ucas`、`.utoc` 只检测；暂无真实项目 `verified` 记录。 |

### 本地模型与游戏试验

- 已建立 `LocalModelTranslationProvider` 和 Ollama 回环桥接；基线模型为 `qwen2.5:3b`，本机服务地址 `127.0.0.1:11434`，HanEngine 桥接地址 `127.0.0.1:8080`。
- R.E.P.O. 曾通过 HanEngine `player` 工作流完成 603/603 条 Unity TSV 文本翻译，候选在源目录外构建；质量报告要求少量人工复核。
- 《How to Fish》有 Unity Addressables 专项实验工具 `tools/unity_addressables_localize.py`。重新检查外层 `.tmp` 后找到了 v4 候选与报告：报告显示 594/594 条已翻译，但也记录英文 bundle 被改写 594 条、CRC 从 `dd831fb6` 变为 `edd7c6e0`，简中 bundle CRC 从 `4676f30b` 变为 `32e6bb3a`。源/候选哈希也确认两个 bundle 都不同。因此该候选破坏“保留英文表”要求，不能作为合格验收；专项工具已修正为只写简中 bundle，且新的聚焦回归测试验证英文 bundle 字节保持不变。旧候选报告标记 `review_required`，仍要求人工译文复核。该报告记载的输入路径是 `D:\steammm\steamapps\common\How to Fish\How to Fish`；它与下述 `.tmp/how-to-fish-qwen25-3b-v1` 探测目录的二进制来源关系尚未核实，不应合并成同一份真实项目验收记录。
- v4 Unity 启动日志来自 Null Gfx 运行，包含 Steam 初始化异常；它不能证明图形游戏运行成功。报告和旧 catalog 记录 594 条，但 2026-10-13 对同一安装路径提取到 646 条，旧 catalog 的源项目指纹不匹配，不能安全复用。初次标准 CLI 检查发现工作流注册表误用了纯 Unity 检测适配器；已改为 Addressables AdapterV1 并加入回归测试。当前 `player` 模式成功提取 646 条。基于真实 Addressables 文件的夹具往返已通过，但使用的是现存简中表而非模型输出，且一条占位符不匹配文本回退了英文；因此翻译质量仍待审阅。Python 3.12 环境没有 UnityPy；使用 Python 3.11.3 + UnityPy 完成。`127.0.0.1:8080/healthz` 和 Ollama `127.0.0.1:11434/api/tags` 均拒绝连接；本机有 qwen2.5:3b 模型清单，但常见安装路径没有 Ollama 可执行文件。没有构建完整安装版候选或执行图形启动。
- 前序状态摘要引用了 `.tmp/how-to-fish-player-run-v1/hanengine-player-flow.log`，并报告旧工作流中的 `extract`、`localize auto` 和显式 `localize unity` 因 `route does not authorize extract` 被阻断，专项诊断在第 264/594 条遇到 `TranslationProviderError`。本次没有找到该旧 HanEngine Player 日志；注册表修正后的标准 extract 已成功，但本地模型不可用，标准 Player 全流程和断点续跑仍需模型服务支持后复核。

### 最近记录的测试

- Python 定向测试：2026-10-13 使用 Python 3.12 重新运行 NW.js 与项目验证模块，`23/23` 通过，其中新增纯文本、无栅格清单运行冒烟路径测试。
- Unity 真实 profile 只读检测：2026-10-13 使用 Python 3.11.3 + UnityPy 1.25.3，标准 AdapterV1 对安装版 How to Fish 返回 `matched=true`、`maturity=build_ready`；英文和简中表均为 646 条且条目 ID、catalog CRC 匹配。未构建候选。
- Unity 标准 CLI 验收：`engine inspect` 在 `player/H1_OFFLINE` 下放行五项结构化操作；`engine extract` 成功输出 646 条、任务 ID `cf0aa9a6-e9d4-45a9-b504-b1f51623c93b`。外部 catalog 位于 `.tmp/how-to-fish-current-standard-catalog-v2.json`，source fingerprint 为 `c639abcdd0d252c402b5c4de3cf19daa85f944a93fa35c3f31d77adda104ac53`；HanStore 在 `.tmp/how-to-fish-current-standard-state-v2`。这些本机证据未纳入 Git。
- Unity Addressables 真实 bundle 往返：646 条通过标准 HanPipeline；使用现有游戏简中表作离线输入，1 条占位符不匹配改为保留源英文后，完整候选验证通过、0 个验证问题。候选只修改简中 bundle 与 `catalog.bin`；英文 bundle SHA-256 前后均为 `27c2bd8b0878f3ee159877d419512cf9d127b5b47ed9a83022caff0ffefa0d28`。候选 profile 重新读取通过，英文/简中表各 646 条，catalog CRC 匹配；游戏安装 bundle/catalog 与构建前夹具副本哈希相同。
- Unity Addressables 回归：Python 3.11.3，`tests/test_unity_addressables_localize.py` 与 `tests/test_unity_addressables_adapter.py` 共 `11/11` 通过，覆盖英文表保持、标准 AdapterV1 构建回读及 StructuredWorkflowSession 普通模式提取路由。
- 本轮聚焦回归：Unity Addressables、专项工具和 Ollama 桥接共 `24/24` 通过；完整 Python 回归 `629/629` 通过，包含 `636` 个子测试。
- 完整 Python 回归：2026-10-13，`622/622` 通过。
- Electron 质量报告测试：2026-10-13，`3/3` 通过。
- Python 测试：现有 2026-08-22 状态摘要记录，R.E.P.O. 本地模型实现后的回归为 `609/609` 通过（该摘要另有更早的 `585/585` 记录）；这不是本轮完整回归结果。
- Electron 测试、TypeScript 检查和 Vite 构建：2026-08-22 项目状态记录为通过，其中 Electron 为 `13/13`。
- 上一轮 Addressables AdapterV1 与 HanGuard/AdapterRuntime 定向回归记录为 `89 passed`、`12 subtests passed`（地址表适配器、能力矩阵、结构化适配器、AdapterRuntime 和 feature CLI）；使用合成文件和 UnityPy 边界替身，没有读取真实游戏 bundle，本轮未重跑。
- Electron 测试、TypeScript 检查和 Vite 构建未在本轮重跑。

## 当前代码结构

```text
game-localizer/
|- cli.py                         CLI 总入口：engine、tasks、project、visual、auth 等
|- translator.py                  兼容旧版单文件字典翻译入口
|- game_localizer/
|  |- adapters/                   AdapterV1 契约和各引擎适配器
|  |  |- contract.py               能力、成熟度、请求/结果和错误类型
|  |  |- structured.py             Ren'Py、RPG Maker、Godot、Unity、Unreal 结构化资源
|  |  |- renpy.py / rpgmaker.py / godot.py / unity.py / unreal.py
|  |- hanengine/
|  |  |- pipeline.py               翻译、检查点和恢复
|  |  |- tasks.py / store.py        HanTask 生命周期、事件和持久化
|  |  |- routing.py / auth.py       HanGuard 路由和本地账户
|  |  |- translation.py             字典、云 Provider、本地模型 Provider 和 Router
|  |  |- multiengine.py             多引擎目录和定位数据模型
|  |  |- renpy.py / rpg_maker.py    引擎专用构建和验证
|  |  |- quality.py / validation.py 质量报告、结构和产物验证
|  |  |- visual*.py / raster.py     视觉证据、样式检查和图片/视频清单
|  |  |- backup.py / packaging.py   备份、回滚和打包边界
|  |- structured_workflow.py         跨引擎检测、提取、翻译、构建和验证会话
|- desktop/
|  |- src/App.tsx                   React 工作台和普通/专业模式界面
|  |- electron/main.cjs             主进程、认证 IPC、任务和 Python 工作流
|  |- electron/preload.cjs          渲染端受限 API
|  |- electron/*report*.cjs         质量/视觉报告校验与裁剪
|- tests/                            Python 契约、引擎、工作流、视觉和桥接测试
|- docs/                             状态、发布范围、引擎能力和流程说明
|- tools/                            模型桥接、基准、项目审校和专项诊断工具
```

## 关键参数

| 参数或命令 | 用途/当前值 |
| --- | --- |
| `python cli.py engine inspect auto <project> --json` | 只读检测引擎、能力矩阵和 HanGuard 决策。 |
| `python cli.py engine extract <engine> <project> --output <catalog>` | 提取受支持的结构化文本目录；必须先通过路由和适配器能力检查。 |
| `python cli.py engine localize <engine> <project> --output <candidate>` | 执行检测、提取、翻译、校验、独立构建和验证。 |
| `--mode player` / `--mode studio` | 普通用户/专业模式；`player` 默认风险级别为 `H1_OFFLINE`，`studio` 默认 `H0_PROJECT`。 |
| `--risk-level H0_PROJECT/H1_OFFLINE/H2_RESTRICTED/H3_PROTECTED` | 显式设置风险基线；改变风险值不会自动提升适配器能力。 |
| `--local-model-endpoint http://127.0.0.1:8080/translate` | 本地模型桥接服务；桥接必须先启动并可通过 `/healthz`。 |
| `--local-model-name qwen2.5:3b` | 记录所用模型名称；模型运行时本身由 Ollama 提供。 |
| `--local-model-timeout 180` | 本机模型单次请求超时参数。 |
| `--dictionary <json>` | 可选精确匹配翻译字典；普通模式不要求预先提供。 |
| `--translated-catalog <json>` / `--quality-report <json>` | 导出翻译目录和质量报告。 |
| `--state-root <dir>` | HanStore、任务和翻译检查点目录。 |
| `--no-resume` | 忽略已有翻译检查点并重新请求模型。 |
| `--font <file>` | 为支持的适配器提供 CJK 字体并纳入构建/覆盖验证。 |
| `--raster-manifest <json>` | 合并已经审批的图片/视频候选资源；不属于 v1 默认流程。 |

常见本地模型启动方式：先运行 `ollama serve`，确认 `ollama list` 中存在 `qwen2.5:3b`，再启动 `python tools/ollama_translation_server.py --model qwen2.5:3b --ollama-url http://127.0.0.1:11434 --host 127.0.0.1 --port 8080`。

## 未解决问题

### P0：真实打包 Unity 项目的普通用户端到端验收未完成

- 限定 Addressables profile 已注册在标准 Unity AdapterV1，HanGuard 的 `player` 模式对它开放 Adapter 能力范围内的操作；合成 runtime 测试已验证提取进入 HanStore。
- Adapter 只支持标准目录形态下配对的 `localization-string-tables-english*.bundle` 与 `localization-string-tables-chinese(simplified)*.bundle`；会检查表后缀/ID、两个源 bundle CRC 与 `catalog.bin`，构建时只写简体中文 bundle 并保留英文 bundle，候选在源目录外生成并回读。
- 对外层 `.tmp/how-to-fish-qwen25-3b-v1` 这个独立快照做过只读 catalog 探测：文件为 73,284 字节，简体中文 bundle CRC `0x4676f30b` 的小端值只出现一次（偏移 14602）；前序只读探测记录的英文 bundle CRC `0xca6e6605` 未在该快照的 catalog 中找到，因此该快照不满足标准 AdapterV1 的严格 profile，必须保持 `detect_only`。它与当前 Steam 安装目录不是同一个检查结果。
- 当前 Steam 安装目录 `D:\steammm\steamapps\common\How to Fish\How to Fish` 的标准 AdapterV1 检测成功，英文和简中表各 646 条、catalog CRC 匹配。已修复普通结构化工作流注册适配器错误，标准 CLI `player/H1_OFFLINE` 能从真实 Addressables bundle 提取 646 条。基于当前安装文件构建的轻量夹具经 HanPipeline 处理后成功完成候选构建和回读；候选仅改简中 bundle 与 `catalog.bin`，英文 bundle 字节保持不变，安装源文件与夹具原始副本哈希相同。该测试使用游戏内已有简中值且有一条占位符安全回退，不能当作模型翻译或完整游戏验收。外部记录：`.tmp/how-to-fish-addressables-roundtrip-record-v1.json`，SHA-256 `3466cf2285057a55a6549d4a862513d17706dc3863a012537d075e18325e3191`。候选在 `.tmp/how-to-fish-addressables-roundtrip-v1/`，使用的夹具不含完整游戏运行文件。旧 v4 专项候选不合格，且其 Null Gfx 启动日志有 Steam 初始化异常。
- 2026-10-14 已对完整安装目录生成 `.tmp/how-to-fish-installed-chinese-candidate-v3`；源/候选英文 bundle SHA-256 均为 `27c2bd8b0878f3ee159877d419512cf9d127b5b47ed9a83022caff0ffefa0d28`，646/646 条表回读通过，适配器验证无阻断问题。候选仍标记 `review_required`，因为它复用了游戏自带简中表而不是模型译文。候选与未修改安装版各执行一次启动探测均以退出码 53 结束且无日志，当前环境不能提供图形运行通过证据。
- Hello Underworld v16 记录失败的原因是验收命令传入了仓库外层目录；检测到了 MV 标记，但该目录没有游戏所需的 `data/`，提取返回 `UNSUPPORTED_INPUT`。实际游戏根目录为源项目的 `Main/`，这是输入路径错误，不是适配器缺陷。保留 v16 记录用于诊断。
- v17 在正确的 `Main/` 根目录完成，验证记录结论为 `verified`：审校目录匹配 `1,954/1,954`，未处理项为 0，字体缺失码位为 0；NW.js 0.29.4 检查 `23/23` 通过，源树和候选树指纹在运行前后保持一致，运行错误数为 0。标题场景的游戏标题及菜单文本为中文；静态标题图仍含英文 “ASPHODEL”。地图场景读到地图 12、坐标 `(1,1)`，但源版和候选版截图均为全黑。
- 本次未配置栅格资源清单，视频检查为 0；没有进行完整游戏流程或译文质量认证。因此 `verified` 只适用于这条记录中的文本、字体和 NW.js 启动冒烟范围，不能作为整款游戏完整汉化验收。

### P1：模型翻译稳定性和断点恢复

- 《How to Fish》专项诊断在 264/594 条时遇到模型输出校验错误；错误被 Router 汇总成泛化的 `TranslationProviderError`，没有暴露具体的换行/标签/占位符校验原因。
- 专项工具目前未逐条保存已完成翻译，失败会导致整批重跑；标准 HanPipeline 有检查点机制，但专项 Addressables 路径尚未接入。
- 短文本和带上下文的字符串曾出现模型把元数据混入译文的质量问题；需把质量扫描、拒绝条件和人工修订回流纳入正式流程。

### P1：桌面普通模式和本地模型管理

- 本地 Provider 和 CLI 参数已存在，但普通模式尚未形成对已打包 Unity 游戏可用的端到端默认路径。
- 模型安装、启动、健康检查、资源占用提示和用户可理解的失败信息仍不完整。

### P2：质量、视觉与发布

- 机器翻译完成率不代表语言质量；术语统一、上下文一致性、长文本布局、字体回退、按钮溢出和游戏内截图审校还需要系统化。
- Unity、Unreal、RPG Maker MZ 等引擎仍缺真实授权项目的同等级 `verified` 记录。
- Windows 安装包、干净环境安装/升级、依赖锁定和用户级回滚尚无完整发布证据。
- 图片/视频文字替换仍有性能风险，保持为独立实验能力，不进入 v1 默认交付。

## 下一步建议

1. **完成真实 Addressables 模型验收。** 当前安装版的 646 条提取、标准候选构建、英文 bundle 保持、简中 CRC 更新和完整回读已完成；下一步是用 HanPipeline 检查点运行真正的模型翻译，完成人工质量审阅，并在可用图形设备上重新启动候选。`Extra Labels:373258983133184` 的 `{0}` 缺失值已安全回退英文；未知/不匹配格式继续保持 `detect_only`。
2. **补齐 Addressables 失败诊断和模型质量门。** 当前适配器已使用 HanPipeline/HanStore 的段级检查点，并报告表/条目进度；下一步应暴露模型校验错误类别、重试信息，并验证失败恢复可从已保存段继续。
3. **补齐 Unity 运行时验收。** 项目外候选只回写简体中文表、保留英文表、更新 `catalog.bin` 中对应 bundle CRC、重新读取表并验证占位符/富文本/换行的构建链已通过；需要在图形环境完成候选启动冒烟，并保留启动失败诊断，不触及源目录。
4. **增加模型输出质量门。** 记录原始错误类别与重试次数；拒绝上下文污染、丢失控制符、非法换行和标签顺序破坏；将低置信或疑似直译项目进入人工审校目录。
5. **完成普通用户端到端验收并刷新发布证据。** 桌面普通模式展示适配器范围、进度、断点恢复、质量报告和候选入口；然后重跑完整 Python、Electron、TypeScript/Vite 检查及干净环境安装、升级和回滚验证。

## 证据与结论说明

- 本文项目分支状态、NW.js 纯文本验收改动和定向测试结果在 2026-10-13 检查；较早的跨引擎回归结果仍来自 2026-08-21 至 2026-08-24。
- Hello Underworld v16/v17 验收记录位于本地 `.tmp/rpg-maker-hello-underworld-validation-record-v16-e2e.json` 和 `.tmp/rpg-maker-hello-underworld-validation-record-v17-e2e.json`。v17 记录 SHA-256 为 `6c6be2f1853d9c007ea64b77bcdf5ea59c714d71c18fb87eddd8fb03e5fb72b4`；NW.js 报告 SHA-256 为 `7e5ce516161389cdb6df4ee71db48ef0e9e4707778f1c7c3c8385e5706768b89`。运行截图在 `.tmp/rpg-maker-hello-underworld-nwjs-evidence-v17-e2e/`，这些 `.tmp` 文件未纳入 Git。
- 《How to Fish》v4 专项报告和候选可在外层仓库 `.tmp/how-to-fish-qwen25-3b-report-v3.json` 与 `.tmp/htf-v4/` 复查；报告 SHA-256 为 `aa9d0d56cff44d528d3544c8bd6931350a0c55408d1eed785b88b853709200fd`。它们记录的英文表改写使该候选不合格。此前提到的 `.tmp/how-to-fish-player-run-v1/hanengine-player-flow.log` 本次仍未找到。外层 `.tmp` 证据不在 Git 版本控制内。
- `build_ready` 表示结构化构建和内部验证达到候选状态；`verified` 只对记录中的固定项目、版本和资源范围有效。两者都不自动代表译文通过出版级语言审校。
