# HanEngine 引擎资源矩阵

更新时间：2026-08-08

本矩阵描述代码已实现的能力边界，不把合成样例通过等同于真实授权项目认证。

## 能力等级

- `仅检测`：只读取文件系统或项目标记，不提取、解包或修改资源。
- `可提取`：可把明确支持的明文资源转换为统一 `SegmentDraft`。
- `可构建`：可通过 AdapterV1 完成提取、翻译、校验、独立构建和内部验证。
- `已验证`：除代码和合成样例外，还必须具有真实授权项目、版本、许可、源树哈希、输出哈希和验证结果记录。

## 当前矩阵

| AdapterV1 | 明文输入 | 代码级能力 | 内部验证 | 真实项目认证 | 明确不支持 |
| --- | --- | --- | --- | --- | --- |
| Ren'Py | `game/**/*.rpy`，排除 `game/tl/` | 可构建 | 占位符、UTF-8、生成结构、产物哈希、完整源树保护；合成样例验证记录通过 | 验证运行器已接入可选 Ren'Py SDK、字体和冒烟证据；尚无真实授权项目 `verified` 记录 | `.rpa`、`.rpyc` 仅检测 |
| RPG Maker MV | `data/*.json` | 可构建 | JSON 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | 加密资源和专有封包仅检测 |
| RPG Maker MZ | `data/*.json` | 可构建 | JSON 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | 加密资源和专有封包仅检测 |
| Godot | 原始项目 PO/CSV | 可构建 | PO/CSV 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | `.pck` 仅检测 |
| Unity | 原始工程 XLIFF/CSV；匹配英文与简体中文 Unity Localization String Table、`catalog.bin` CRC 的已打包 Addressables | 可构建 | 明文格式沿用 XML/CSV 校验；Addressables 只写简体中文表、保留英文 bundle，并检查表 ID、catalog CRC 和文件哈希；当前只完成合成 AdapterV1 测试 | 尚无真实授权 Addressables 项目 `verified` 记录；候选不执行游戏启动 | 未知 Addressables 布局、Unity Player 其他资源和 Asset 二进制仅检测 |
| Unreal Engine | 原始工程 PO | 可构建 | PO 解析、UTF-8、占位符、产物哈希、完整源树保护；合成样例验证记录通过 | 通用官方验证器、字体和冒烟证据入口已具备；尚无真实授权项目 `verified` 记录 | `.pak`、`.ucas`、`.utoc` 仅检测 |

所有构建输出必须位于源项目之外。加密、DRM、二进制解包、反编译、进程注入、内存读写和协议拦截不属于支持范围。

六个合成样例已通过 `project validate` 代码闭环并生成 `build_ready` 证据。由于合成样例没有实际官方工具验证、目标字体和游戏运行冒烟，这些结果不会升级为 `verified`。

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
