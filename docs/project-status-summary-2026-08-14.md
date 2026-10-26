# HanEngine 项目状态摘要

更新时间：2026-08-21
仓库：`C:/Users/23256/Documents/汉化/.worktrees/game-localizer`  
分支：`codex/game-localizer`  
当前里程碑：冻结 v1 发布范围，随后完成核心文本工作流、桌面端发布闭环和可复现构建。P1.2 的真实项目证据保留为能力等级依据，不再以单个游戏美术调试作为当前主线。

> 本摘要面向继续开发和交接。`verified` 表示工程、编译、运行和证据链通过，不等于机器翻译语言质量已经达到发布标准。

v1 正式范围、排除项和发布退出条件见 [v1 发布范围](release-scope-v1.md)。图片/视频栅格文字流程保留为独立实验能力，默认不进入 v1 文本汉化构建。

## 已完成内容

### 核心工作流

- 建立 `AdapterV1`、`HanPipelineV1`、`HanTask`、`HanStore` 和 `HanGuard` 统一工作流。
- 支持 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 的结构化适配入口。
- 已实现检测、提取、翻译、校验、独立构建、验证、任务持久化、断点续跑、取消、重试和回滚边界。
- 输出默认位于源项目之外，并记录源树/候选树指纹、占位符、UTF-8、产物哈希和构建清单。
- 图片/视频文字已抽象为 `hanengine.raster-manifest/v1`：支持媒体库存、文字区域/视频时间段、OCR 置信度、字体/颜色/描边/角度、审批状态、源/产物 SHA-256、独立候选合并和 `hanengine.raster-verification-report/v1`。未审批资源保持原样并进入复核，不会静默写回。

### Ren'Py

- 明文 `.rpy` 已接入 AdapterV1 全流程，覆盖对白、旁白、菜单、`_()`、screen 文本控件和同一表达式中的多个直接字符串。
- 动态参数、字符串拼接和无法安全静态翻译的表达式进入 `unhandled_items`，不会静默当作已汉化。
- 已处理重复 `old` 文本冲突、嵌套插值、富文本标签、上下文标记、语言激活文件和多字体 `FontGroup`。
- 候选使用 Ren'Py 原生 `translate <language>` 与 `config.default_language`；原文/中文切换入口在 HanEngine 客户端，不添加游戏内语言菜单。
- 官方 `The Question` 和第三方 `Heartfelt Moments` 均完成对应范围的真实构建/运行验证；The Question v11 候选目录覆盖率为 `242/242`，但这只是目录覆盖率，不代表中文质量全部完成。

### Godot

- 官方验证器改为在同一影子候选上执行冷导入和第二遍干净检查；即使 Godot 退出码为 `0`，第二遍仍出现 `SCRIPT ERROR:`、`FATAL ERROR:` 或 `CRASH HANDLER:` 也会阻断认证。
- 已实现保守的运行时名称发现：仅追踪明确进入 `tr()` 的类型化 GDScript 参数流，并从挂载对应实体脚本的 `.tscn` 节点提取稳定名称；同名多类型、`Battler2` 等默认类名和无明确 CSV 目标会阻断。该能力仍是窄范围实现，公开 `dynamic_text` 状态保持 `detect_only`。
- Godot 样式构建只打包完整 CJK 字体、设置目标语言并注册 autoload；原 `.theme/.tres/.tscn` 的字体大小、颜色和描边必须保持不变。视觉硬门会校验源样式哈希、字体覆盖、autoload 和禁止的全局样式覆盖。
- GDQuest Open RPG v8 完成 `97/97` 翻译，并覆盖 `Bugcat/Wolf/Baloo/Nutsy` 等运行时敌人名；像素字体、黑色描边、原作布局和颜色均保留，7 项样式硬门和字体覆盖通过。项目指定的官方 Godot 4.6.2 下，原始上游与中文候选第二遍日志逐字节相同，均在 Dialogic `node_portrait_container.gd:89` 报 `SCRIPT ERROR:`，因此记录结论严格保持 `failed`，不能宣称 `verified`。
- Godot CSV 新目标列现在会把公共语言标识 `zh-CN` 规范为 Godot 原生 `zh_CN`；修复后的 v8 候选树与已人工检查的 v6 候选树哈希完全一致。
- 第二项目采用 Godot 官方 Dodge the Creeps 授权派生版。最终记录 `godot-dodge-the-creeps-v3-style` 完成 `4/4` PO 写回、Godot 4.7.1 两遍官方校验、字体覆盖、7 项样式硬门和原文/中文运行冒烟，结论为 `verified`；候选树与截图所用预检候选哈希一致。

### 视觉判官与真实证据

- `VisualEvidenceManifest` 为 `hanengine.visual-evidence-manifest/v3`，`VisualEvidenceReport` 为 v2，均支持严格 JSON 往返。
- Ren'Py capture report 为 `hanengine.renpy-capture-report/v3`；新 renderer observation 为 v2，记录 `region_id`、`render_path`、`z_index`、文本、坐标、尺寸和 baseline。
- 已接入 OCR 硬门、确定性 renderer 文本相交硬门和智谱 `glm-4.6v` 辅助复核。GLM 不能绕过硬门或直接授权发布通过。
- The Question 六场景已用新 v2 探针连续采集两次：12 个场景侧的节点集合、层级、绘制顺序、坐标和文本跨次稳定，正常布局误报为 0。
- 仓库 fixture `tests/fixtures/renpy_renderer_overlap/` 已真实制造文字覆盖；`renderer_text_overlap` 正确阻断，交叠面积为 `18,528 px²`，较小区域覆盖率为 `69.42%`，智谱判官调用为 0。
- 机器可读里程碑报告：`.tmp/renderer-v2-milestone-report.json`，SHA-256：`62056f6bc2de15ed4d521cb3369b64ce2282d52ff0bbc12cdb04956711b3145b`。

### 桌面端

- Electron + React 已替代 Tkinter 入口。
- 已实现本地账户、PBKDF2-SHA256 密码哈希、会话门控、普通/专业模式、任务中心和客户端语言设置。
- `engine build/localize` 的 `hanengine.quality-report/v1` 现经受认证的 Electron IPC 以裁剪摘要读取；普通模式保留构建结果，专业模式同步显示总条目、已翻译、漏译、未处理、阻断项、审查原因、校验问题、建议处理方式和报告路径。失败构建的报告同样可见，不会被退出码以外的状态掩盖。
- 普通模式不再要求用户预先理解或选择 JSON 本地字典：流程只需先选游戏、检测引擎和独立输出目录，然后即可提取文本并查看目录。专业模式才提供可选术语表覆盖；没有翻译来源时，系统不会把未翻译内容伪装成成功汉化。云端翻译协议已存在，但在正式服务地址、隐私和密钥策略确定前不提供虚构的默认云端字典。
- 视觉验收入口显示确定性硬门、OCR、模型辅助结果和人工复核状态；报告图片和哈希由主进程重新校验。
- 游戏启动语言通过认证 IPC 传递为 `HANENGINE_GAME_LANGUAGE`，不写入 React 状态、日志或 localStorage。

### 验证结果

- Python：`585/585`。
- Electron：`13/13`。
- TypeScript 检查和 Vite 正式构建通过。
- `git diff --check` 通过，源码/文档 API-key 形状字面量扫描通过。

## 当前代码结构

```text
game_localizer/
  adapters/                 各引擎 AdapterV1、结构化契约
  hanengine/
    core.py                 核心模型和路由
    pipeline.py             HanPipelineV1
    tasks.py/store.py       任务、状态和持久化
    renpy.py                Ren'Py 提取、构建、验证
    godot.py                Godot CJK 字体注入与源样式硬门
    renpy_visual_capture.py Ren'Py 影子项目采集和 renderer v2 探针
    visual.py               OCR 与视觉会话
    visual_style.py         视觉样式、硬门和判官契约
    visual_evidence.py      manifest、OCR、报告、硬门和 GLM 边界
desktop/
  electron/                 主进程、IPC、视觉报告校验和人工复核证明
  src/                      React 客户端界面
tests/
  golden/                   Ren'Py 结构/构建 golden corpus
  fixtures/                 真实视觉覆盖 fixture
  test_*.py                 适配器、契约、视觉、客户端和回归测试
docs/
  current-project-status.md 详细阶段状态
  analysis/                 视觉、模型和真实项目审计
```

## 关键参数

| 参数 | 当前值/含义 |
| --- | --- |
| `--mode` | `player` 普通模式，`studio` 专业模式 |
| `--language` | 默认 `zh-CN`，Ren'Py 输出标识为 `zh_cn` |
| `HANENGINE_GAME_LANGUAGE` | `zh_cn` 启动中文，`source` 启动原文；仅由 HanEngine 客户端传递 |
| `ZHIPU_API_KEY` | 智谱 API Key 的唯一读取环境变量；不要写入仓库或日志 |
| 默认视觉模型 | `glm-4.6v`，仅作辅助复核 |
| `--ocr-provider` | `tesseract` 或 `rapidocr` |
| `--ocr-language` | 例如 `chi_sim+eng`，启用本地 OCR 观察 |
| OCR 最低置信度 | `0.80` |
| 视觉位置/尺寸阈值 | 默认 `2 px` |
| 视觉 baseline 阈值 | 默认 `2 px` |
| 最大行数差 | 默认 `1` |
| Renderer overlap 最小面积 | `16 px²` |
| Renderer overlap 最小覆盖率 | 较小区域至少 `20%` |
| 视觉处理顺序 | 确定性硬门 -> OCR/布局 -> GLM -> 人工复核 |
| Electron 构建 | `npm run build` |
| Electron 测试 | `npm run test:electron --silent` |

常用命令：

```powershell
python -m unittest discover -s tests
python cli.py visual capture-renpy ...
python cli.py visual prepare ...
python cli.py visual verify ...
cd desktop; npm run test:electron --silent; npm run build --silent
```

## 未解决问题

- P1.2.1 已建立跨引擎统一能力声明：`native_text_replace`、`dynamic_text`、`raster_text`、`detect_only`，每项带 `implemented`、`verified`、`detect_only` 或 `unsupported` 状态、原因和证据引用。
- RPG Maker、Unity、Unreal 尚未形成与 Ren'Py、Godot 同等级别的真实授权项目 `verified` 记录。RPG Maker MV 的 Hello Underworld 当前验收候选为 v15，仅含原生结构化文字和字体，已完成一次隔离 NW.js 人工运行冒烟；图片与视频均保持源项目版本。
- Open RPG 的翻译、敌人名和视觉样式已通过，但原始上游在指定 Godot 4.6.2 下可复现的 Dialogic 脚本错误仍阻断官方认证；修复上游项目不属于本轮汉化器的默认修改范围。
- 复杂动态表达式和加密/专有封包仍不属于当前写回范围。图片/视频已经具备正式清单、审批和候选写回闭环，公开 `raster_text` 为 `implemented`；但 Hello Underworld 的用户验收发现局部替换后的过场视频明显卡顿，当前已暂停该路线。通用自动 OCR、风格重绘、视频重编码和运行认证仍未实现。
- GLM 在受控缺陷集上存在重叠和样式缺陷漏检；不能把模型 `pass` 当作自动发布授权。
- 中文翻译仍需要真实译文、术语表、人工审校和长文本布局回归；当前机械字典只验证工程闭环。
- Windows 安装包尚未完成干净机器安装、升级、回滚和依赖锁定验证。
- 用户在聊天中提交过 Key，发布前必须轮换，并改用系统密钥存储或环境变量直接配置。
- 当前工作树存在未提交改动，且本分支相对 `origin/codex/game-localizer-checkpoint` 超前 7 个提交；本摘要不代表这些改动已经推送。

## 下一步建议

### P1.2.1：能力声明统一（已完成）

1. 已审计六个 AdapterV1 引擎（Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal）的原生写回、动态文本、栅格文字和仅检测边界。
2. 已建立 `hanengine.adapter-capabilities/v1` 严格 JSON schema；每项都带 `implemented`、`verified`、`detect_only` 或 `unsupported` 状态、原因和可追溯证据。
3. `AdapterMetadata`、`cli.py engines`、`cli.py engine inspect` 和 Electron 检测模型现在返回同一能力矩阵；封包输入会把写回相关维度降为 `detect_only`。
4. 已为矩阵和五类能力声明补充契约测试、严格 JSON 往返测试和 CLI 输出测试；包含 Godot 名称/样式/验证器、栅格资源流程、字体/栅格联合 CLI、NW.js 精确视频路径和审校目录回归后，完整 Python 回归为 `583/583`。
5. Ren'Py 原生文本替换以真实项目记录标为 `verified`；Godot 随后以官方 Dodge the Creeps 派生项目完成 4.7.1 PO 写回认证；其余引擎保持 `implemented`。

### P1.2.2：跨引擎真实项目认证（证据维护）

- Godot：官方 Dodge the Creeps 派生项目已通过 Godot 4.7.1 两遍官方校验、PO 原生写回、CJK 字体覆盖、源样式硬门和原文/中文运行对照，最终记录为 `godot-dodge-the-creeps-v3-style`。
- Godot 大型项目：Open RPG v8 已证明窄范围运行时敌人名发现、Godot CSV 语言标识规范化和原作样式保留生效；原始上游与候选在指定 Godot 4.6.2 下复现同一 Dialogic 脚本错误，仍不得用截图通过替代官方校验结论。详见 `docs/analysis/2026-08-14-godot-open-rpg-4.6.2-baseline.md`。
- RPG Maker MV：Hello Underworld v15 使用 `project validate --reviewed-catalog --font --runtime-smoke passed` 重建，审校目录与新提取的 `1954/1954` 片段严格匹配；候选树与 v14 一致，仅新增人工运行引用 `manual-nwjs-v14-playtest-2026-08-21`。标题图、窗口皮肤、脚本和三段 WebM 均与源树逐字节一致。记录仍为 `build_ready`，因为本次没有配置官方验证器；它是供当前文字、敌人名、角色名、物品、技能、菜单、地图事件和小游戏文本验收的候选，不声称过场美术已汉化。
- 后续：为 RPG Maker MZ、Unity、Unreal 准备合规真实项目和版本兼容证据；未获得证据前保持 `implemented`。
- 美术资源：局部替换视频的卡顿问题独立排期，不进入 v1 默认交付或当前候选。

## 当前结论

P1.1 在已声明的 Ren'Py 明文项目范围内完成，P1.2.1 已把能力边界统一暴露给适配器、CLI 和 Electron。P1.2.2 已完成 Godot 4.7.1 PO 写回的首个认证；RPG Maker MV 当前使用 Hello Underworld v15 验收非美术结构化文字，并记录一次隔离人工运行冒烟。图片、标题图和过场视频的局部替换因性能问题暂缓，不应把旧 v9/v10/v12/v13 美术候选当作当前版本。接下来的主线是 v1 核心工作流、桌面端发布闭环和可复现构建，而不是继续调试该单一游戏。
