# HanEngine 项目状态总结

更新时间：2026-08-22  
仓库：`C:/Users/23256/Documents/汉化/.worktrees/game-localizer`  
分支：`codex/game-localizer`  
当前提交：`e0efb56 feat: complete visual gates and adapter capability contracts`  
远端关系：相对 `origin/codex/game-localizer-checkpoint` 超前 7 个提交；工作树存在大量未提交改动，本文不表示这些改动已经提交或推送。

## 1. 已完成内容

### 1.1 核心汉化流水线

- 已建立统一的 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard 工作流。
- 已支持 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 的检测和结构化资源适配入口。
- 已实现检测、文本提取、翻译、占位符校验、独立构建、验证、任务持久化、断点续跑、取消、重试和任务恢复。
- 默认输出位于源项目之外，构建会记录源树/候选树指纹、文件哈希、编码、占位符和生成清单，避免覆盖原项目。
- 已提供本地 JSON 精确匹配字典和显式云翻译 Provider/Router 协议。字典命中优先于云端；云端令牌只从运行时环境读取，不写入仓库、日志、任务状态或渲染进程。
- 已提供统一质量报告 `hanengine.quality-report/v1`，记录总条目、已翻译、漏译、未处理、校验阻断项、审查原因和建议处理方式。

### 1.2 桌面端

- Electron + React 已替代旧 Tkinter 入口。
- 已实现本地账户、首次建号、登录/退出、PBKDF2-SHA256 密码哈希和会话门控。
- 未认证渲染进程不能调用项目扫描、目录读取、Python 工作流或任务控制 IPC。
- 普通模式映射 CLI `player`；专业模式映射 CLI `studio`。
- 普通模式不再要求用户准备本地字典：选择游戏目录、检测引擎、选择项目外输出目录后，可以先提取文本。
- 术语表/字典入口保留在专业模式，普通模式没有翻译来源时不会伪造“汉化成功”。
- 任务中心支持查看、刷新、取消、重试和重启恢复；普通/专业模式均可查看质量报告摘要。
- 客户端设置支持游戏启动语言（简体中文/原文）和启动程序，并通过认证 IPC 传递 `HANENGINE_GAME_LANGUAGE`。

### 1.3 引擎能力与真实验证

- Ren'Py：明文 `.rpy` 已覆盖对白、旁白、菜单、屏幕文本、`_()` 和部分动态表达式；重复文本冲突、富文本标签、占位符、字体和语言激活均有校验。
- Ren'Py 真实项目：官方 The Question 和第三方 Heartfelt Moments 已形成 `verified` 记录；验证包含编译、字体覆盖、运行冒烟和源树保护。机械字典只证明工程闭环，不代表最终中文质量。
- Godot：已实现 PO/CSV 写回、语言标识规范化、CJK 字体注入、语言 autoload、源样式保护和运行时名称的窄范围发现。
- Godot 官方 Dodge the Creeps 派生项目已完成 PO 写回、Godot 4.7.1 两遍校验、字体覆盖、样式硬门和双语言运行冒烟，记录为 `verified`。
- Godot Open RPG 大型项目已验证敌人名和原作样式保留，但指定 Godot 4.6.2 下上游本身存在 Dialogic 脚本错误，记录保持 `failed`。
- RPG Maker MV Hello Underworld 已形成只含结构化文字的 v15 `build_ready` 候选，覆盖角色名、敌人名、物品、技能、菜单、地图事件、选择项、战斗文本和小游戏文本；图片/视频保持源版本。
- 已建立 `hanengine.raster-manifest/v1` 和视觉验证报告流程，可管理图片/视频文字的资源库存、文字区域、审批状态、源/产物哈希和人工复核。
- Hello Underworld 的局部视频替换在用户验收中出现明显卡顿，因此美术资源写回和视频验证暂缓，不进入 v1 默认交付。

### 1.4 工程验证结果

最近已完成的回归结果：

- Python：`585/585` 通过。
- Electron：`13/13` 通过。
- TypeScript 类型检查和 Vite 正式构建通过。
- `git diff --check` 通过。
- 桌面开发服务可通过 `http://127.0.0.1:5173/` 访问；Electron 开发窗口可由 `npm run dev` 启动。

## 2. 当前代码结构

```text
game-localizer/
|- cli.py                         CLI 总入口：engine、project、tasks、package、visual、auth 等
|- translator.py                  兼容的单文件文本翻译器和 JSON 字典加载
|- game_localizer/
|  |- adapters/                   旧检测适配器和 AdapterV1 能力契约
|  |  |- contract.py               能力、成熟度、错误、请求/结果模型
|  |  |- structured.py             多引擎结构化提取/构建/验证实现
|  |  |- renpy.py                  旧 Ren'Py 检测入口
|  |  |- rpgmaker.py               旧 RPG Maker 检测入口
|  |  |- godot.py / unity.py / unreal.py
|  |- hanengine/
|  |  |- pipeline.py               HanPipelineV1 翻译和断点恢复
|  |  |- tasks.py / store.py        HanTask、HanStore、任务状态和检查点
|  |  |- routing.py / auth.py       HanGuard 路由和本地账户
|  |  |- multiengine.py             Godot、RPG Maker、Unity、Unreal 目录适配
|  |  |- renpy.py / rpg_maker.py    Ren'Py、RPG Maker 专用构建和验证
|  |  |- translation.py              字典、云翻译 Provider 和 Router
|  |  |- quality.py                  质量报告
|  |  |- raster.py                   图片/视频清单和候选合并
|  |  |- visual.py / visual_evidence.py / visual_style.py
|  |  |                             OCR、视觉硬门、判官和人工复核证据
|  |  |- godot.py / nwjs.py          Godot 字体样式和 RPG Maker NW.js 验证
|  |- structured_workflow.py         跨引擎检测、提取、翻译、校验、构建、验证会话
|- desktop/
|  |- src/App.tsx                  React 主界面、普通/专业模式和质量报告
|  |- src/styles.css               桌面端样式
|  |- electron/main.cjs            主进程、Python 子进程、认证 IPC、任务 IPC
|  |- electron/preload.cjs         受限渲染端 API
|  |- electron/quality-report.cjs  质量报告严格读取和裁剪
|  |- electron/visual-report.cjs   视觉报告和人工复核证明
|- tests/                          Python 回归、契约、适配器、质量、栅格和 NW.js 测试
|- docs/                           状态、发布范围、授权验证和美术资源流程
|- examples/                       Ren'Py、RPG Maker、Godot 等合成/授权样例
|- tools/                          Hello Underworld 审校目录和候选构建辅助工具
```

## 3. 关键参数

### 3.1 CLI 工作流

| 参数 | 作用 |
| --- | --- |
| `engine inspect auto <project> --json` | 只读检测引擎、能力矩阵和 HanGuard 决策 |
| `engine extract <engine> <project> --output <catalog>` | 提取结构化待翻译目录 |
| `engine localize <engine> <project> --output <dir>` | 执行检测、提取、翻译、校验、构建和验证 |
| `--dictionary <json>` | UTF-8 原文到译文的精确匹配字典；可选于提取阶段，汉化阶段至少需要字典或云端点 |
| `--cloud-endpoint <https-url>` | 显式云翻译服务地址，字典未命中时使用 |
| `--token-env <name>` | 云翻译 bearer token 的环境变量名，默认 `HANENGINE_TRANSLATION_TOKEN` |
| `--translated-catalog <json>` | 导出完整翻译目录 |
| `--quality-report <json>` | 指定质量报告路径，默认是 `<output>.quality.json` |
| `--state-root <dir>` | HanStore、任务、检查点和段翻译持久化目录 |
| `--mode player/studio` | 普通用户或专业工作流的 HanGuard 模式 |
| `--risk-level H0_PROJECT/H1_OFFLINE/...` | 显式指定风险基线；默认由模式推导 |
| `--font <file>` | 为支持的引擎打包 CJK 字体并参与覆盖校验 |
| `--raster-manifest <json>` | 合并已经审批的图片/视频候选资源 |

### 3.2 授权验证参数

`project validate` 需要显式提供 `--authorized`、`--authorization-reference`、源项目外的 `--output`、`--record` 和 `--state-root`。真实项目若无官方验证器，结论最多是 `build_ready`；不能把人工试玩或机械字典写成 `verified`。

### 3.3 桌面端行为

- 普通模式必须同时满足检测结果为 `ready`、适配器能力包含 `extract/validate/build/verify`、HanGuard 允许这四项操作。
- 没有字典时普通模式的“先提取文本”仍可用；“一键汉化”保持禁用。
- 所有候选输出必须位于源项目之外；输出目录是项目本身或其子目录时被拒绝。
- 云翻译没有默认服务地址，不在普通模式中展示虚构的云端配置。

## 4. 未解决问题

### 4.1 当前阻断或高风险问题

- **仓库根目录误检测**：选择 HanEngine 自身仓库时，检测器递归发现 `.tmp/authorized-tv/TV_Demo/game/gui.rpyc`，将代码仓库误判为 Ren'Py 项目。由于 `.rpyc` 是编译资源，结果被降级为 `detect_only`，普通模式无法提取或构建。应忽略 `.tmp`、测试产物、嵌套工作树和已知构建缓存，并为“不是游戏项目”显示明确原因。
- **普通模式尚无正式云翻译服务**：云 Provider 协议和 CLI 参数存在，但没有正式 endpoint、隐私政策、额度治理、重试策略和用户密钥管理，因此不能作为默认用户路径。
- **普通用户翻译来源已增加本地模型路径，但尚未成为桌面端默认入口**：Ollama `qwen2.5:3b` 经 HanEngine 回环桥接已完成 R.E.P.O. 的 603 条 Unity TSV 候选；字典仍可作为术语覆盖和人工审校来源，桌面端自动启动、模型资源管理和质量复核入口仍待完善。
- **美术资源汉化性能**：局部视频/图片替换会造成播放卡顿；通用 OCR、风格重绘、视频重编码性能优化和运行认证未完成。
- **跨引擎认证不完整**：RPG Maker MV 只有结构化文字 `build_ready`；RPG Maker MZ、Unity、Unreal 尚未形成与 Ren'Py/Godot 同等级的真实授权项目 `verified` 记录。
- **Windows 发布闭环未完成**：安装包、干净机器安装、升级、回滚和依赖锁定验证仍缺少最终证据。
- **回滚入口不完整**：后端存在备份/恢复边界，但桌面端尚未提供完整、可验证的用户级回滚命令和界面。
- **中文质量仍需人工审校**：当前多处真实验证使用机械测试字典，工程通过不等于中文表达、术语一致性、长文本布局和字体风格已经达到发布质量。

### 4.2 已知能力边界

- 加密、DRM、二进制封包、Unity Player、Unreal Pak/IoStore、Godot PCK、Ren'Py `.rpa/.rpyc` 默认只检测，不解包、不破解、不修改。
- 动态运行时文本仍以 `detect_only` 或人工复核清单处理，不能宣称静态目录覆盖了全部运行时文字。
- 图片/视频文字流程默认关闭，不能把旧的美术实验候选当作当前 v1 验收版本。

## 5. 下一步建议

### P0：先修复“无法使用”的检测体验

1. 在 AdapterV1 扫描层统一排除 `.git`、`.tmp`、`.worktrees`、`node_modules`、`dist`、`build`、`release`、缓存和测试输出。
2. 增加“游戏项目根目录判定”：必须在目录自身发现受支持的项目标记或明文资源，不能只凭任意深层文件命中。
3. 检测报告增加结构化原因，例如“发现编译后的 `.rpyc`，但没有明文 `.rpy`；该项目仅支持检测”。桌面端直接展示该原因和推荐操作。
4. 为普通模式补充一个端到端测试：选择代码仓库、选择封包游戏、选择明文样例，分别验证按钮状态和用户提示。

### P1：完成普通用户可用的翻译来源

1. 先定义正式云翻译契约：服务地址、隐私声明、文本保留期限、令牌存储、超时、重试、限流、费用和失败降级。
2. 在普通模式增加“官方云翻译”作为可选来源，仅显示服务名称和隐私说明，不要求用户填写陌生 endpoint。
3. 保留专业模式的本地术语表覆盖，并让云翻译结果进入质量报告和人工审校目录。
4. 增加无网络、云端返回非法占位符、超时、部分成功和恢复重试测试。

### P2：完成发布和跨引擎闭环

1. 完成 RPG Maker MZ、Unity、Unreal 的合规真实项目和版本兼容证据。
2. 完成桌面安装包、升级、回滚、依赖锁定和干净 Windows 机器验收。
3. 补齐桌面端真正可用的回滚命令、失败恢复提示和用户级产物管理。
4. 将中文术语表、人工审校、长文本溢出和字体回归纳入发布门槛。

### P3：独立推进美术资源能力

1. 先解决局部视频替换的性能问题，再恢复 NW.js 运行认证；不要在当前 v1 文本候选上混入实验性美术写回。
2. 完成通用 OCR、风格参数校准、视频重编码性能基准和逐场景人工复核。
3. 只有在性能、画面和运行证据同时通过后，才把 `raster_text` 从实验能力提升为发布能力。

## 6. 2026-08-24 R.E.P.O. 本地模型实施结果

- 已在本机 RTX 4060 Laptop（约 8 GB 显存）上使用 Ollama `qwen2.5:3b`（Q4_K_M）运行 HanEngine 本地翻译路径，桥接地址为 `http://127.0.0.1:8080/translate`。
- R.E.P.O. 源目录 `D:\steammm\steamapps\common\REPO` 提取 603 条 Unity TSV 文本；`player` 模式完成 603/603 翻译，未翻译数为 0，占位符阻断项为 0。
- 候选目录：`C:\Users\23256\Documents\汉化\.tmp\repo-qwen25-3b-zh-v3`；翻译目录导出：`repo-qwen25-3b-catalog-v3.json`；质量报告：`repo-qwen25-3b-quality-v3.json`。
- Unity 候选构建和 3 个 TSV 文件的 UTF-8/语法/哈希验证均通过；源目录未写回。质量报告为 `review_required`，仅有 3 条占位模板保持英文的自然语言复核警告。
- 本地桥接层现会拒绝模型新增物理换行、注释或警告，并对字面量 `\\n` 分片翻译，避免破坏 Unity TSV 单行格式。
- 候选副本已完成 Unity 批处理启动烟雾测试并加载到 Steam/命令系统；无图形设备模式产生的 shader 警告不代表文本资源失败，仍需在有图形环境中进行人工游戏内对比。
- 本次实现后 Python 回归测试为 `609/609` 通过。

## 当前结论

HanEngine 已具备可审计的多引擎结构化文本汉化核心和可用的 Electron 桌面工作台；本地模型路径也已在 R.E.P.O. 上完成一轮可运行的 Unity 文本候选。该候选仍需人工游戏内对比和术语审校，不能把批处理启动或机械校验当作中文质量认证。仓库根目录误检测、桌面端模型管理、Windows 发布闭环和美术资源性能仍是主要缺口。
