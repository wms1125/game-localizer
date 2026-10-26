# HanEngine 引擎资源矩阵

更新时间：2026-08-21

本矩阵描述代码已实现的能力边界，不把合成样例通过等同于真实授权项目认证。

## 能力等级

- `仅检测`：只读取文件系统或项目标记，不提取、解包或修改资源。
- `可提取`：可把明确支持的明文资源转换为统一 `SegmentDraft`。
- `可构建`：可通过 AdapterV1 完成提取、翻译、校验、独立构建和内部验证。
- `已验证`：除代码和合成样例外，还必须具有真实授权项目、版本、许可、源树哈希、输出哈希和验证结果记录。

## 当前矩阵

| AdapterV1 | 明文输入 | 代码级能力 | 内部验证 | 真实项目认证 | 明确不支持 |
| --- | --- | --- | --- | --- | --- |
| Ren'Py | `game/**/*.rpy`，排除 `game/tl/` | 可构建 | 占位符、UTF-8、生成结构、产物哈希、完整源树保护；合成样例验证记录通过 | The Question 与 Heartfelt Moments 已形成真实项目 `verified` 记录 | `.rpa`、`.rpyc` 仅检测 |
| RPG Maker MV | `data/*.json` | 可构建 | JSON 解析、UTF-8、占位符、产物哈希、完整源树保护和字体构建；Hello Underworld 固定提交以审校目录写回 `1954/1954` 段 | Hello Underworld v15 是只含结构化文字和字体的 `build_ready` 候选，包含角色/敌人名、物品、技能、菜单、事件和小游戏文本，并有隔离人工运行冒烟引用；未配置官方验证器或栅格清单，不能标为 `verified` | 加密资源和专有封包仅检测；通用自动 OCR、重绘和跨项目视频认证尚未实现 |
| RPG Maker MZ | `data/*.json` | 可构建 | JSON 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | 加密资源和专有封包仅检测 |
| Godot | 原始项目 PO/CSV | 可构建；CSV 目标语言规范为 Godot 原生标识；可保守发现明确 `tr()` 类型流中的稳定场景节点名 | PO/CSV 解析、UTF-8、占位符、完整项目上下文指纹；CJK 字体注入保留源字号/颜色/描边，7 项样式硬门；官方验证执行冷导入和第二遍错误标记检查 | 官方 Dodge the Creeps 派生项目已通过 Godot 4.7.1、CJK 字体、源样式硬门和原文/中文运行对照认证；PO 写回为 `verified` | `.pck` 仅检测；通用动态文本仍为 `detect_only`；CSV、Godot 3.x 尚无同等级真实项目证据 |
| Unity | 原始工程 XLIFF/CSV；匹配英文与简体中文 Unity Localization String Table、`catalog.bin` CRC 的已打包 Addressables | 可构建 | 明文格式沿用 XML/CSV 校验；Addressables 只写简体中文表、保留英文 bundle，并检查表 ID、catalog CRC 和文件哈希；当前只完成合成 AdapterV1 测试 | 尚无真实授权 Addressables 项目 `verified` 记录；候选不执行游戏启动 | 未知 Addressables 布局、Unity Player 其他资源和 Asset 二进制仅检测 |
| Unreal Engine | 原始工程 PO | 可构建 | PO 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | `.pak`、`.ucas`、`.utoc` 仅检测 |

所有构建输出必须位于源项目之外。加密、DRM、二进制解包、反编译、进程注入、内存读写和协议拦截不属于支持范围。

六个 AdapterV1 已接入 `hanengine.raster-manifest/v1`：审批通过的普通图片/视频产物可经过源哈希、产物哈希和路径边界检查后合并到独立候选；未审批资源保持原样并进入复核报告。该 `implemented` 声明不包含通用自动 OCR、重绘或运行认证；根据 [v1 发布范围](release-scope-v1.md)，它不是 v1 默认流程。

六个合成样例已通过 `project validate` 代码闭环并生成 `build_ready` 证据。真实项目认证只提升其实际覆盖的范围；Godot 当前证据覆盖 4.7.1 的 PO 写回，不外推到 CSV、Godot 3.x、通用动态文本或 PCK。RPG Maker MV 的当前 Hello Underworld v15 只覆盖明文 `data/*.json` 和字体交付，图片、标题图、脚本、音频和 WebM 均保持源版本；旧 v9/v10/v12/v13 栅格候选是历史实验，局部视频替换造成播放卡顿，不能作为当前 `verified` 证据。Open RPG 的敌人名和视觉验证不能覆盖原始上游在指定 Godot 4.6.2 下同样复现的 Dialogic 官方校验失败，因此不构成第二份 Godot `verified` 记录。

## 新引擎接入清单

1. 实现 `AdapterV1` 元数据和 `detect/extract/validate/build/verify/rollback` 契约；不支持的操作必须返回结构化错误。
2. 把明文原始项目证据与封装或二进制证据分开；后者默认只返回 `detect` 能力。
3. 将引擎资源转换为统一 `SegmentDraft`，保留稳定段 ID、源位置、源指纹、上下文、占位符和引擎定位元数据。
4. 校验源文本和定位元数据不可变、占位符守恒、目标编码可用，并在任何阻断问题出现时停止构建。
5. 构建到独立临时目录，成功后原子发布；失败不得修改源项目或留下半成品输出。
6. 验证产物路径、哈希、编码和资源语法；没有官方验证器或运行冒烟时必须明确记录，成熟度不得标为 `VERIFIED`。
7. 注册到 `get_adapters_v1()` 和 `StructuredWorkflowSession`，不得在 HanPipelineV1、HanTask、HanStore、HanGuard 或桌面端新增引擎专属旁路。
8. 增加 AdapterV1 契约测试、`detect_only` 测试、占位符失败测试、原子构建测试、合成样例和普通模式端到端测试。
9. 更新本矩阵，并按 `authorized-project-validation.md` 完成真实授权项目认证后再提升公开能力等级。
