# HanEngine 当前项目状态

更新时间：2026-08-14

本文是当前工作树的阶段性状态摘要。它补充并更新 `docs/project-status.md`，重点记录最近的真实 Ren'Py 项目验证和“无感汉化”目标。这里的“已验证”表示工程流水线、编译、字体和运行冒烟证据完整，不代表机器翻译质量已经达到发布标准。

当前仓库分支为 `codex/game-localizer`。本轮起点 checkpoint 为 `fe64856 docs: record v11 client language evidence`，并已同步到远端检查点；P1.1 后续里程碑已在同一分支形成仅本地提交，尚未推送。

## 1. 已完成内容

### 核心运行时

- 已建立 AdapterV1、HanPipelineV1、HanTask、HanStore 和 HanGuard 的统一工作流。
- 已接入 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 的结构化资源适配路径。
- 已实现检测、提取、翻译、校验、独立构建、验证、任务持久化、断点续跑、取消和重试。
- 默认输出位于源项目之外，支持源树指纹、候选树指纹、占位符校验、UTF-8 校验、产物哈希和回滚边界。

### 桌面端与账户

- Electron + React 桌面端已替代旧 Tkinter 入口。
- 已实现本地账户数据库、登录/退出、PBKDF2-SHA256 密码哈希和会话门控。
- 已修复 Python `needs_setup` 与渲染端 `needsSetup` 的首次启动字段映射，全新本地配置可正确进入创建账户流程。
- 普通模式映射为 `player`，专业模式映射为 `studio`；未认证渲染进程不能访问项目和任务 IPC。
- 任务中心支持查看、取消、重试和重启恢复。
- 客户端设置现承载游戏启动语言（简体中文/原文）和游戏启动程序；设置保存在本地，并由受认证的 Electron IPC 以 `HANENGINE_GAME_LANGUAGE` 传给游戏进程。游戏候选不添加语言菜单。

### Ren'Py 适配器修复

- Ren'Py 明文 `.rpy` 已接入 AdapterV1 全流程。
- 已过滤 `id`、`style`、`variant`、`background`、`activate_sound` 等屏幕属性，避免把资源名或控件属性误识别为对白。
- 同一脚本中的重复文本现在会生成唯一段 ID。
- 生成翻译块时按源文本去重，避免 Ren'Py 因重复 `old` 字符串在运行时崩溃；同一源文本的相同译文确定性去重，不同译文会在创建输出目录前失败，并报告两处路径、行号、segment ID 和目标文本，不再静默保留第一条。
- `_()` 包装的普通对白、屏幕 `text`、`textbutton` 和 `label` 现在可被提取；同一行动态 screen 表达式中的多个直接字符串字面量也会逐项提取。非字面量参数和字符串拼接不会被误翻译或静默丢弃，而是以路径、行号、表达式和原因写入 catalog `unhandled_items`，CLI 和 AdapterV1 同时提示运行时/人工复核；屏幕文本按字符串翻译块写出。
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

### 视觉证据与真实截图采集

- 已建立 `VisualStyleProfile`、`VisualComparison`、硬性排版门槛和可插拔 `VisualJudge` 的严格 JSON 往返契约；`VisualEvidenceManifest` 已升级到 `hanengine.visual-evidence-manifest/v3` 并独立保存参考/候选 renderer observation，`VisualEvidenceReport` 保持 `hanengine.visual-evidence-report/v2`。manifest、报告和硬门 `details` 均支持严格 JSON 对象往返；报告只保存相对路径、截图尺寸、SHA-256、观察来源/引用和结构化判定，不嵌入图片二进制。
- 已新增 `visual_evidence.py`、`cli.py visual prepare` 和 `cli.py visual verify`。`prepare` 从 v3 Ren'Py 采集报告和严格 `hanengine.visual-evidence-annotations/v1` 人工标注生成受控 manifest，重新校验 screen 语义、场景顺序、源指纹、PNG 尺寸/哈希、renderer observation viewport 和区域 ID，并固定写入 `observation_source=manual`；`verify` 按 `blocked -> escalate -> pass` 顺序执行确定性硬门和可选外部判官。
- `visual verify` 已支持 Tesseract 或 RapidOCR 本地自动观察：`--ocr-provider` 选择实现，`--ocr-language` 启用观察，`--ocr-allowlist` 扩展默认允许的 `English`/`Ren'Py` 名称，`--ocr-min-confidence` 默认 `0.80`，`--ocr-report` 指定证据目录内的 sidecar。`hanengine.visual-ocr-observation/v2` 会记录 provider/version、真实像素指纹以及每个 OCR 框的位置、尺寸、文本、换行数和置信度；达到阈值的候选框若含英文自然语言残留或参考有文字而候选无有效文字，会触发硬门并在判官前短路。
- 已新增 `renpy_visual_capture.py` 和 `cli.py visual capture-renpy`：同一声明式交互计划分别运行原文和候选项目，项目先复制到临时影子目录，记录源树是否保持不变、窗口几何、截图哈希和运行状态。
- Ren'Py 采集报告保持 `hanengine.renpy-capture-report/v3`。新采集写 `hanengine.renpy-renderer-observation/v2`：只读探针递归观察 `renpy.game.interface.surftree`，累加 Render 子节点坐标，并为每个 Text 节点记录文本、区域、行数、可用 baseline、稳定 `region_id`、child-index `render_path` 和绘制顺序 `z_index`，再把 Windows client 坐标映射到完整 PNG 的 `capture_pixels`。历史 `renderer-observation/v1` 继续严格读取，但不伪造其不存在的层级和绘制顺序；缺少 observation 或 viewport 与截图不一致仍会失败，旧 layout cache 无行指标时明确记录 `line_count=0`、`baseline=null`。
- renderer 文本相交硬门已在 GLM 前接入。规则不是“矩形相交即失败”，而是比较候选相对参考新增或显著恶化的关系，同时检查交叠面积、双向覆盖/可见比例、文本基线、父子 render path、绘制顺序、重复阴影层和按场景允许区域对。异常直接 `blocked`，报告的严格 JSON `details` 记录场景、两个区域 ID/文本摘要、坐标、基线、路径、层级、前景区域、交叠面积和比例。配置智谱判官时，缺少任一场景 renderer observation 会先触发覆盖硬门，模型调用次数保持 0。
- 历史 v14 六场景用 v3 manifest 重新持久化两侧 v1 renderer observation 并完成零费用回归：manifest SHA-256 为 `a58d0ff58fe15d778dabdb894c38406b73fcd40563464a2240aef76c741e99ce`，报告 SHA-256 为 `f1ea629c3fab0f6a46eb67ce5813806f76c42406ed22e1503a079ddac2616377`。六个 renderer 检查均通过、失败 0；设置页参考/候选各保留 26 个同构可疑布局关系而未误报，其余五场景为 0。整份报告 133/133 硬门通过；最终为 `escalate` 仅因本次刻意未调用 GLM，不能写成模型通过。
- 已用新探针对官方 `The Question` 原文和 v11 中文候选连续完成两次真实 v2 六场景采集。两份 capture report SHA-256 分别为 `e5f778b5ffae31c7b531aaa172853bf54d566950d1218c45c76488d76793fc47` 和 `111f7df6272b752c5789abe04a1521c3f6fe390c5cc52ce71c411af9b3e60f2e`；12 组 observation 的 `region_id`、`render_path`、`z_index`、文本、坐标、尺寸、行数和 baseline 跨次逐项一致，不稳定项 0，PNG 哈希也全部一致。新 v2 数据的六场景相交误报为 0，设置页 26 个正常同构关系仍不误报。
- 仓库自有真实运行 fixture `tests/fixtures/renpy_renderer_overlap/` 已通过 SDK 8.5.3 的 `capture -> prepare -> verify` 全链路。候选只把第二段文字移动到第一段上方，最终唯一失败码为 `renderer_text_overlap`，交叠面积 `18528 px²`、较小区域覆盖 `69.42%`；报告严格 JSON 往返通过。最终采集使用只含受控 `.rpy` 的干净临时树，capture/manifest/report SHA-256 分别为 `817f61221bc6bb2e901e0ebc6ad62eed6518d9fc791ce37f6fd876319307048b`、`5750ad1f8f109540884825709d764cf5f458ad12a200cdf25a936b634980b13b`、`ef11cded850d03eb5d01f2dcf751074a305908fa9499b47b44b99fb09f66afd8`。另用启用本地 OCR 的 `ZhipuImageVisualJudge` 计数子类复验，报告提供方为 `zhipu:glm-4.6v`，GLM 调用为 0且未发网络请求；短路报告 SHA-256 为 `d2e5e9699fc24c9f5a27a2a113ebabf8163133ca725093e4bf69908ef9cc80f8`。
- renderer v2 真实验收汇总已写入 `.tmp/renderer-v2-milestone-report.json`，schema 为 `hanengine.renderer-v2-milestone-report/v1`，SHA-256 为 `62056f6bc2de15ed4d521cb3369b64ce2282d52ff0bbc12cdb04956711b3145b`。该报告绑定六份底层证据哈希，并记录 12/12 场景侧稳定、正常误报 0、真实覆盖坐标/比例反算通过、智谱调用 0，以及本轮 Python 549/549、Electron 10/10 和正式构建通过。
- 官方 `The Question` v14 证据位于 `.tmp/visual-evidence-renpy-the-question-v14-renderer-zhcn-six/`。原文和候选在主菜单、对白、分支、设置、保存和读取页面均为 `6/6 + 6/6` screen 断言通过，12 张 PNG 均为 `1296x759`，两棵源树保持不变；capture report SHA-256 为 `59123a175dd6b6a2c66aa3f691bc79ec370232dd661a2af7b139f2e45f8f3b59`。原文和候选各记录 125 个 renderer 文本区域；v14 图片与已人工核验的 v11 图片逐字节一致，因此布局几何标注可追溯复用。
- v14 使用隔离的 RapidOCR 1.4.4 对六场景真实像素完成 `chi_sim+eng` 复验。manifest SHA-256 为 `36319fe6fac7c89223988f3fa374e614ad2e10280df35850fb9d49b1c876d588`，OCR sidecar SHA-256 为 `168eb7dd8236b492c7d863f3b02d86b542c063696ad53408786ce1d2b5a7389a`，visual report SHA-256 为 `313483ae0d9d2465681d35f7d0132c48285b5984ed34e66a3f5e1b4254e9754c`。6/6 候选场景均检测到文字，英文自然语言残留为 0；布局、字体、OCR 覆盖和残留共 140/140 项确定性硬门通过。设置页拉丁文本只允许登记的语言名称，品牌名沿用默认允许规则。
- 已接入智谱原生 `ZhipuImageVisualJudge`，API Key 只从 `ZHIPU_API_KEY` 读取，远端只接收内存 JPEG 压缩副本，原始 PNG/哈希/硬门证据不变；API 错误、超时、非法 JSON 和低置信度均升级为 `escalate`，模型不能绕过硬门。CLI 使用 `--zhipu-model` 时强制同时启用本地 OCR。
- 同一历史 r6 六场景盲测中，付费 `glm-4.6v-flashx` 请求成功率和 JSON 合规率均为 100%，但已知缺陷漏检率为 100%；付费 `glm-4.6v` 请求成功率 100%、JSON 合规率 100%、漏检率 0%、误报率 0%，因此选为当前质量优先辅助模型。v14 历史路径的 140/140 硬门和 6/6 GLM 复核均通过，旧报告最终决定为 `pass`；当前策略不再允许 GLM 单独授权自动通过。
- 已新增仓库自有的 36 场景受控视觉缺陷集：4 个正常对照，漏翻、截断、溢出、重叠、缺字、乱码、错误换行和样式/可读性八类缺陷各 4 个变体；固定 960x540 画布、生成器版本、字体记录和机器真值，72 张 PNG 总计约 2 MB，可由 `tools/generate_visual_judge_dataset.py` 重现。生成器 v2 已确保中文候选固定 UI 文本全部汉化，基准请求不向模型泄露含类别的场景 ID。
- 修正前提后的 v2 门槛复测覆盖上一轮漏掉的 8 个缺陷和 4 个正常对照：`glm-4.6v` 请求与 JSON 合规均为 12/12，正常误报 0/4，但缺陷漏检 7/8；错误换行检出 1/1，文字重叠 0/3，样式/可读性 0/4。P50 为 13.16 秒、P95 为 20.56 秒，API 返回总计 26,285 tokens。该结果不满足全量重跑门槛，因此未继续产生 36 次调用。
- Electron 普通/专业模式均新增“视觉验收”入口，固定组合 `glm-4.6v`、RapidOCR 和 `chi_sim+eng`，显示检查中、已通过、已阻断和人工复核四态；执行/配置错误单独显示失败。确定性硬门失败直接阻断，GLM 结果只作辅助；即使 GLM 返回高置信 `pass`，最终也升级为人工复核。Key 不进入 React 状态、IPC 参数、日志或 localStorage，Python 子进程只继承本机环境变量。主进程只读取严格 v2 视觉报告并返回裁剪摘要，且客户端仅在当前命令明确写出报告后读取，避免旧报告假通过。客户端现可按报告场景读取经过 PNG 签名、大小、目录边界和 SHA-256 校验的原文/候选证据图；全部场景确认后，主进程重新校验报告及所有证据图，并原子写入独立的 `hanengine.visual-review-proof/v1` sidecar。证明绑定完整报告 SHA-256、机器结论、场景图片哈希、确认时间和当前本地账户；已有有效证明不会被另一会话覆盖。

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
|     |- visual.py                  OCR 稳定性、残留文本识别和视觉替换会话
|     |- visual_style.py            VisualStyleProfile、硬性视觉门槛和可插拔 VisualJudge 契约
|     |- visual_evidence.py         A/B 截图清单、哈希校验、OCR sidecar、视觉报告和外部判官边界
|     `- renpy_visual_capture.py    Ren'Py 影子项目成对截图采集和运行报告
|- desktop/
|  |- electron/main.cjs             窗口、登录会话、Python 子进程和受控 IPC
|  |- electron/visual-report.cjs    严格视觉报告/图片校验、客户端摘要和人工复核证明
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
| `--font-probe-text` | 可重复的运行时动态文本探针 | 必须与 `--font` 同时使用；探针码点和译文一起参与字体覆盖与 `FontGroup` 分配 |
| `--runtime-smoke` | `not_run`、`passed`、`failed` | `passed` 必须带稳定引用 |
| `--language` | 目标语言，默认 `zh-CN` | Ren'Py 输出标识符为 `zh_cn` |
| `renpy_font_paths` / `renpy_font_probe_texts` | 内部 `BuildRequest.output_options` 字段 | 由验证工作流从 `--font` / `--font-probe-text` 生成，不是用户 CLI 参数 |
| `HANENGINE_PYTHON` | Electron 调用的 Python 可执行文件 | Windows 默认使用 `python` |
| `HANENGINE_GAME_LANGUAGE` | HanEngine 客户端启动游戏时传递的语言模式 | `zh_cn` 启动中文；`source` 清除 Ren'Py 语言偏好后启动原文；仅由客户端启动生效 |
| `visual prepare` | 从已验证采集报告和人工区域标注生成 v2 manifest | 必须显式提供 `--authorized`；输入、输出和证据图片必须位于同一证据目录 |
| `visual verify` | 对成对截图运行硬门和可选外部判官 | 必须显式提供 `--authorized` 和 `--authorization-reference` |
| `--ocr-provider` | 选择 `tesseract` 或 `rapidocr`，默认 `tesseract` | provider 不可用时明确失败；sidecar 记录实际 provider 和版本 |
| `--ocr-language` | 为 `visual verify` 启用本地 OCR 观察，例如 `chi_sim+eng` | 需要对应的 Tesseract/pytesseract 或 RapidOCR 本地运行时；未启用时不改变旧工作流 |
| `--ocr-min-confidence` | OCR 覆盖率和英文残留门使用的最低置信度，默认 `0.80` | 必须在 `0.0..1.0`；低于阈值的框只保留在 sidecar，不参与阻断 |
| `--ocr-allowlist` / `--ocr-report` | 扩展自然语言允许名单 / 指定 OCR sidecar 文件 | 两者都必须与 `--ocr-language` 一起使用，sidecar 必须位于证据目录 |
| `visual capture-renpy` | 按声明式计划采集原文/候选 PNG 和 renderer 文本区域 | 只在临时影子项目中运行，输出目录必须为空；v3 报告要求双侧 renderer observation |
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
- v11 正式记录携带构建、编译、字体以及原文/中文双模式六场景运行时引用；v14 在相同 PNG 像素上补充 renderer observation 和 RapidOCR 复验。截图文件名不单独承担页面语义断言，证据由报告中的 `expected_screen`、renderer viewport/区域、PNG 哈希、报告哈希和候选树哈希共同约束。
- `visual capture-renpy` 已用 Ren'Py 引擎级 screen 探针阻止错页截图被误判为对齐，并用 `PrintWindow` 降低桌面前台程序干扰。声明式动作仍使用相对坐标，计划需要为目标项目校准并由 `expected_screen` 验收；renderer observation 验证自动采集区域和坐标空间，受控人工区域继续承担布局比较，RapidOCR 承担候选文字覆盖和英文残留硬门。
- 本机已配置智谱服务并验证 `glm-4.6v` 鉴权；生产代码仍只从 `ZHIPU_API_KEY` 读取。聊天中出现过 Key，因此当前 Key 只能视为开发期本机凭据，发布前仍需轮换并由用户直接写入系统密钥存储或环境变量。

### 文本覆盖和语境

- 当前 Ren'Py 提取器覆盖明文对白、旁白、菜单、屏幕控件以及同一行多个直接 `_()` 字符串字面量；复杂运行时参数和字符串拼接保持源行为，并进入严格未处理清单供运行时/人工复核，不会被静默当作已汉化。`{#...}` 文本上下文标记已纳入 Segment V2 metadata；自动翻译复杂动态表达式不属于本轮已完成范围。
- 结构化适配器会把中文目标中“源文等于译文”的明显英文自然语言标记为非阻断性 `untranslated_natural_language` 告警；客户端将其显示为“需检查”。单个标识符、缩写、路径、变量和产品品牌不按此规则误报。
- Ren'Py 运行时对重复 `old` 文本存在全局冲突；当前写出器只对相同目标确定性去重，对不同目标明确失败并给出两处完整上下文。若未来需要让同一原文按场景使用不同译文，必须引入 Ren'Py 可表达的上下文方案，不能用静默覆盖实现。
- 段模型仍没有完整保存字体、控件尺寸、换行约束和动画上下文，不能单独保证长中文译文不溢出；本轮已在 `VisualHardGatePolicy` 增加按场景/区域的最大行数预算，预算超限会阻断硬门。
- Ren'Py 写出器现在支持可选运行时字体探针；探针字符与译文共同参与联合 Unicode 覆盖检查和显式 `FontGroup` 范围分配，缺字、无字体探针和多字体回退均有自动化回归。

### 范围和验证

- “任何游戏”不能由一个通用文本替换器保证。明文脚本、动态文本、图片文字、视频字幕、加密封包和受保护运行时必须分级处理。
- RPG Maker、Godot、Unity、Unreal 尚缺少与 Ren'Py 同等级别的真实授权项目 `verified` 记录。
- 图片/视频内嵌文字、复杂动态文本和专有封包不属于当前原生适配范围。
- 本次真实验证使用机械测试字典，仍需真实译文、术语表、人工审校和长文本布局回归。
- 已建立仓库自有的文件型 Ren'Py golden corpus manifest，首批 4 个合成 fixture 覆盖对白、菜单、屏幕控件、`_()`、上下文标签、富文本、嵌套插值和重复原文；该 corpus 只证明结构/构建契约，不代表真实项目或中文质量权威。
- 已登记官方 Ren'Py `The Question` 简体中文样例的固定版本和文件哈希，但没有把第三方样例译文复制进 golden corpus；该来源可证明官方项目行为和来源链，不能替代人工语言质量审校。
- 已使用登记来源在隔离候选中生成本地 `zh_cn` 翻译：目录覆盖率为 242/242，v11 内部验证通过且仅剩 2 个非阻断告警（作者署名、语言名称），Ren'Py SDK `8.5.3.26051504` 编译退出码为 0；字体已实际打包且联合覆盖通过。原文/中文客户端模式均完成六场景 runtime smoke，候选树与验证记录一致。
- P1.1 基线相关八个测试模块此前共 127 项通过；后续新增 GLM 基准、图像压缩、Key/默认模型配置、响应契约、模型标识覆盖、OCR 强制组合、受控数据集、人工复核报告读取、renderer 相交阴性/阳性样本、GLM 前短路、v1/v2 兼容、严格报告往返和真实运行 fixture 契约。完整工作区 Python `python -m unittest discover -s tests` 当前为 549/549 项通过，Electron 为 10/10 项通过，TypeScript 检查与 Vite 正式构建通过。

### 桌面端和发布

- 封包页面、单文件结果统计和部分高级工作流仍需补齐。
- Electron 任务取消、重试、恢复、错误状态和多尺寸窗口仍需端到端回归。
- 人工复核证明已用真实 v14 六场景证据完成端到端验证：`1440x920` 首次窗口从 `0/6` 逐场景确认后写入 sidecar 并显示通过，`1120x720` 新窗口通过“打开已有报告”恢复 `6/6`、复核人和锁定状态；两个尺寸均无水平溢出且成对截图加载成功。生成、恢复截图 SHA-256 分别为 `65d374f283e96909131506deec047e7ba48f70f08d40bce575be222ff3b9448c`、`65bf03c5b5c5b44400b14d6b7635834afe3eef37885b45e920a21087bc9808e0`，本机证明文件 SHA-256 为 `7ffefff78faafd12dfc3ef735004a71d3da9078182e4654e77a279893d596f20`。证明不修改机器报告；报告变化会使旧哈希命名的证明不再匹配，图片篡改会在恢复时失败。当前证明没有操作系统签名，只提供本机流程审计，不对拥有证据目录写权限的攻击者提供密码学防伪。
- Windows 安装包尚未完成干净机器安装测试，npm 依赖版本也需要固定。

## 5. 下一步建议

### P1.1：Ren'Py 无感汉化闭环（已完成）

1. [已完成] 增加目标语言激活策略：候选首次运行默认中文，HanEngine 客户端提供原文/中文启动控制，不在游戏内增加语言菜单，并将激活文件纳入验证清单；官方 Ren'Py 项目的两个客户端模式均已完成六场景实际启动和截图验证。
2. [已完成] 扩展 Ren'Py 提取器：已覆盖 `_()`、常见屏幕文本控件、有效 `menu:` 一级选项、同一行多个直接字符串字面量、嵌套动态表达式和富文本标签校验；通用结构化适配器与 Ren'Py AdapterV1 共享平衡占位符扫描和标签顺序校验。无法安全静态翻译的运行时参数和拼接表达式会保留并进入未处理清单，不再静默漏译。
3. [已完成] 在现有 Segment/SegmentDraft metadata 中冻结 Segment V2 最小契约：`schema_version=2`、占位符、富文本标签、原始换行序列和 speaker/kind/文本上下文键/前后语境；契约会校验 metadata 与段字段一致，Ren'Py `{#...}` 文本上下文键已纳入提取。官方文档未发现独立通用的 Ren'Py 复数翻译语法，因此不虚构支持。
4. [已完成] 已建立文件型 Ren'Py golden corpus manifest、4 个仓库自有合成 fixture，以及官方 `The Question` 本地参考源登记；四个 fixture 均通过 Ren'Py SDK 8.5.3 编译（退出码 0、无 traceback）。官方样例中文候选已完成真实运行时启动和主菜单、对白、分支、保存、读取、设置页面的截图回归，动态 UI 文本显示正常；v8 记录的稳定运行时引用中包含 r7 报告 SHA-256 和候选指纹。
5. [已完成] Ren'Py 候选继续打包多字体并生成 `FontGroup`；新增按场景/区域最大行数的长文本质量门、运行时动态字符字体探针、探针缺字失败和多字体显式范围回退测试。无法安全翻译的动态表达式保留源行为并显式报告，重复原文的目标冲突在写出前失败。
6. [已完成] 视觉档案、截图比较、硬门报告和判定结果已支持严格 JSON 往返；A/B PNG 清单、哈希校验、Ren'Py 影子项目成对采集器、renderer observation、受控人工标注和 RapidOCR/Tesseract OCR 均已接入。智谱 `glm-4.6v` 已作为当前默认辅助复核模型接入，CLI 强制与本地 OCR 硬门组合；受控集证明其不能自动放行，因此当前 GLM `pass` 固定升级为人工复核。
7. [已完成] 新增 36 场景可复现受控缺陷集和客户端视觉验收入口；客户端显示发布判定摘要和严格校验后的逐场景原文/候选截图，要求逐场景确认后才能人工放行，并持久化绑定报告、图片和本地复核人的独立证明；Key 保持在渲染进程之外，并完成首次生成与新窗口恢复的双尺寸真实 Electron 检查。

P1.1 在已声明的 Ren'Py 明文项目范围内完成。完成含义是客户端语言控制、静态文本覆盖、未处理项可见、冲突安全、字体交付、编译/运行、六场景 renderer/OCR/布局硬门、GLM 视觉复核、受控缺陷集和客户端验收入口形成闭环；不含复杂动态表达式自动求值、图片/视频文字重绘或大规模跨游戏视觉泛化证明。

### P1.2.1：统一“原生渲染替换”能力（已完成）

1. 已为 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 定义 `native_text_replace`、`dynamic_text`、`raster_text`、`detect_only` 四个能力维度。
2. 统一 schema 为 `hanengine.adapter-capabilities/v1`，每个声明包含 `implemented`、`verified`、`detect_only`、`unsupported` 状态、原因和证据引用，并支持严格 JSON 往返。
3. `AdapterMetadata`、CLI `engines`/`engine inspect` 和 Electron 检测模型共享同一矩阵；封包或二进制输入的写回维度会自动降级为 `detect_only`。
4. Ren'Py 原生文本替换以 The Question 与 Heartfelt Moments 的真实验证记录为 `verified`；其余引擎保持 `implemented`，直到取得真实授权项目证据。
5. 已补充六个内置 AdapterV1 的能力契约测试；完整 Python 回归为 `553/553`，Electron 为 `10/10`，Vite 正式构建通过。

### P1.2.2：跨引擎真实项目认证

1. 所有引擎优先写回原生本地化格式，不使用字幕叠加或进程注入。
2. 对无法原生替换的内容生成清晰的未处理清单和原因。
3. 为 RPG Maker、Godot、Unity、Unreal 准备合规的真实项目、官方工具和运行冒烟证据。

### P2：扩展真实项目认证

1. 为 RPG Maker、Godot、Unity、Unreal 分别准备合规的真实项目、官方工具、字体和运行冒烟环境。
2. 每个引擎至少形成一份脱敏 `verified` 记录和版本兼容性报告。
3. 建立跨引擎 golden corpus，比较提取覆盖率、占位符完整性、编译结果和运行画面。

### P3：资源和发布质量

1. 将 OCR/图片重绘/视频字幕作为独立能力，继续受 HanGuard 门控，不与原生文本替换混淆。
2. 完成桌面端端到端测试、安装包、升级、回滚和多窗口尺寸回归。
3. 固定依赖版本，执行干净机器构建和安装验证。

## 当前结论

HanEngine 已具备多引擎 AdapterV1 基础、Ren'Py 真实项目 `verified` 闭环、客户端语言控制和字体随候选包交付的第一版实现。P1.1 已完成：静态文本覆盖、动态未处理项、重复源文冲突、字体、编译、双模式运行、renderer v2 观测、RapidOCR 英文残留硬门、确定性文本相交硬门、智谱辅助复核、36 场景受控缺陷集、客户端逐场景验收和独立人工复核证明均有实现与证据。v14 历史报告的 140/140 硬门和 6/6 `glm-4.6v` 复核通过；历史相交回归为 133/133 本地硬门通过、renderer 误报 0。新探针的两次真实 v2 六场景采集跨次不稳定项为 0、正常误报为 0；仓库真实覆盖 fixture 被 `renderer_text_overlap` 单独阻断，模型调用为 0。受控门槛复测证明模型会漏检重叠和低对比度，当前不再自动授权 `pass`。P1.1 不再保留 renderer v2 实证缺口，下一阶段进入 P1.2 的跨引擎能力声明统一。
