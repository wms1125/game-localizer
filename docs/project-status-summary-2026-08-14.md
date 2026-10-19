# HanEngine 项目状态摘要

更新时间：2026-08-14  
仓库：`C:/Users/23256/Documents/汉化/.worktrees/game-localizer`  
分支：`codex/game-localizer`  
当前里程碑：P1.1 已完成，下一阶段为 P1.2。

> 本摘要面向继续开发和交接。`verified` 表示工程、编译、运行和证据链通过，不等于机器翻译语言质量已经达到发布标准。

## 已完成内容

### 核心工作流

- 建立 `AdapterV1`、`HanPipelineV1`、`HanTask`、`HanStore` 和 `HanGuard` 统一工作流。
- 支持 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 的结构化适配入口。
- 已实现检测、提取、翻译、校验、独立构建、验证、任务持久化、断点续跑、取消、重试和回滚边界。
- 输出默认位于源项目之外，并记录源树/候选树指纹、占位符、UTF-8、产物哈希和构建清单。

### Ren'Py

- 明文 `.rpy` 已接入 AdapterV1 全流程，覆盖对白、旁白、菜单、`_()`、screen 文本控件和同一表达式中的多个直接字符串。
- 动态参数、字符串拼接和无法安全静态翻译的表达式进入 `unhandled_items`，不会静默当作已汉化。
- 已处理重复 `old` 文本冲突、嵌套插值、富文本标签、上下文标记、语言激活文件和多字体 `FontGroup`。
- 候选使用 Ren'Py 原生 `translate <language>` 与 `config.default_language`；原文/中文切换入口在 HanEngine 客户端，不添加游戏内语言菜单。
- 官方 `The Question` 和第三方 `Heartfelt Moments` 均完成对应范围的真实构建/运行验证；The Question v11 候选目录覆盖率为 `242/242`，但这只是目录覆盖率，不代表中文质量全部完成。

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
- 视觉验收入口显示确定性硬门、OCR、模型辅助结果和人工复核状态；报告图片和哈希由主进程重新校验。
- 游戏启动语言通过认证 IPC 传递为 `HANENGINE_GAME_LANGUAGE`，不写入 React 状态、日志或 localStorage。

### 验证结果

- Python：`549/549`。
- Electron：`10/10`。
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
- RPG Maker、Godot、Unity、Unreal 尚未形成与 Ren'Py 同等级别的真实授权项目 `verified` 记录。
- 复杂动态表达式、图片/视频内嵌文字、字幕重绘、加密/专有封包不属于当前原生文本替换范围。
- GLM 在受控缺陷集上存在重叠和样式缺陷漏检；不能把模型 `pass` 当作自动发布授权。
- 中文翻译仍需要真实译文、术语表、人工审校和长文本布局回归；当前机械字典只验证工程闭环。
- Windows 安装包尚未完成干净机器安装、升级、回滚和依赖锁定验证。
- 用户在聊天中提交过 Key，发布前必须轮换，并改用系统密钥存储或环境变量直接配置。
- 当前工作树存在未提交改动，且本分支相对 `origin/codex/game-localizer-checkpoint` 超前 6 个提交；本摘要不代表这些改动已经推送。

## 下一步建议

### P1.2.1：能力声明统一（已完成）

1. 已审计六个 AdapterV1 引擎（Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal）的原生写回、动态文本、栅格文字和仅检测边界。
2. 已建立 `hanengine.adapter-capabilities/v1` 严格 JSON schema；每项都带 `implemented`、`verified`、`detect_only` 或 `unsupported` 状态、原因和可追溯证据。
3. `AdapterMetadata`、`cli.py engines`、`cli.py engine inspect` 和 Electron 检测模型现在返回同一能力矩阵；封包输入会把写回相关维度降为 `detect_only`。
4. 已为矩阵和五类能力声明补充契约测试、严格 JSON 往返测试和 CLI 输出测试；完整 Python 回归为 `553/553`。
5. Ren'Py 原生文本替换以真实项目记录标为 `verified`；其他引擎的原生结构化写回保持 `implemented`，在取得真实项目证据前不升级为 `verified`。

### 后续

- P2：为 RPG Maker、Godot、Unity、Unreal 准备合规真实项目和版本兼容证据。
- P3：完成 OCR/图片重绘/视频字幕独立能力、干净机器安装、升级、回滚和发布依赖固定。

## 当前结论

P1.1 在已声明的 Ren'Py 明文项目范围内完成，P1.2.1 已把能力边界统一暴露给适配器、CLI 和 Electron。当前最有价值的后续工作是为 RPG Maker、Godot、Unity、Unreal 获取合规真实项目证据，而不是把未验证的实现升级为发布授权。
