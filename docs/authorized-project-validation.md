# 真实授权项目验证记录

更新时间：2026-08-08

此文件定义 HanEngine 从“可构建”升级到“已验证”所需的证据。仓库当前没有可公开记录的真实授权项目认证；合成样例只能验证代码闭环，不能填写为真实项目认证。

## 验证命令

`project validate` 强制显式提供授权确认，按统一 AdapterV1 执行 `detect -> extract -> translate -> validate -> build -> verify`，并将候选输出和 JSON 记录写在源项目之外。

```powershell
python cli.py project validate renpy "C:\Games\AuthorizedProject" `
  --output "D:\HanEngine\candidates\project-zh-CN" `
  --dictionary "D:\HanEngine\dictionaries\project.zh-CN.json" `
  --state-root "D:\HanEngine\state" `
  --record "D:\HanEngine\records\project-renpy-001.json" `
  --record-id "project-renpy-001" `
  --project-label "authorized-project-alias" `
  --authorized `
  --authorization-reference "internal-ticket-1234" `
  --renpy-sdk "C:\renpy-sdk\renpy.exe" `
  --font "D:\HanEngine\fonts\project-zh-CN.ttf" `
  --runtime-smoke passed `
  --runtime-smoke-reference "manual-smoke-run-2026-08-08"
```

Ren'Py 便捷参数按官方启动器的 `<launcher> <project> compile` 形式调用。仓库没有内置或假定 SDK 路径；只有实际提供 `--renpy-sdk` 且退出码为 `0` 时才记录通过。其他引擎使用通用验证器入口：

```powershell
python cli.py project validate unity "C:\Games\AuthorizedUnityProject" `
  <其他必填参数> `
  --validator "C:\Tools\official-validator.exe" `
  --validator-arg "--batch" `
  --validator-arg "{output}"
```

`{output}` 必须作为一个完整参数出现，运行时替换为候选目录。`--runtime-smoke` 是已经在授权环境中完成的人工或外部运行记录声明，CLI 不会自行启动游戏；标记为 `passed` 时必须附带稳定引用。

## 结论语义

| JSON 结论 | 含义 |
| --- | --- |
| `failed` | 内部流程失败、翻译不完整、源树变化，或已配置的官方验证、字体覆盖、运行冒烟失败；CLI 返回 `1` |
| `build_ready` | AdapterV1 内部闭环通过，但官方验证器、字体覆盖或运行冒烟至少一项未配置；CLI 返回 `0` |
| `verified` | 内部闭环、官方验证器、字体 Unicode 覆盖、运行冒烟全部通过，且外部验证器未修改候选树；CLI 返回 `0` |

`build_ready` 不等于真实项目认证。只有来自真实授权项目且结论为 `verified` 的记录，才可作为该项目、引擎版本和资源范围的认证证据。

## JSON 记录

记录版本当前为 `hanengine.validation/v1`，包含：

- 稳定记录 ID、UTC 时间、授权引用和脱敏项目标签；
- 操作系统、Python 版本、AdapterV1 元数据、引擎版本和检测证据；
- HanGuard 最终路线、相对资源路径、段统计和持久化任务 ID；
- 完整源树哈希、支持资源指纹、构建清单、候选树哈希和内部验证结果；
- 官方验证器工具名、类型、退出码或失败类别，字体文件名、字体哈希和缺失码点；
- 运行冒烟引用、已知偏差和最终结论。

记录不保存源项目、输出目录、状态目录或字典的绝对路径，不保存原始或翻译文本，也不保存外部验证器的 stdout/stderr。验证器运行前后的候选树均计算哈希；验证器修改候选内容会使记录失败。

## 必填字段

| 字段 | 要求 |
| --- | --- |
| 验证记录 ID | 稳定、唯一，不包含项目密钥或个人信息 |
| 引擎与版本 | 精确到能够复现资源格式差异的版本 |
| AdapterV1 ID 与版本 | 例如 `hanengine.renpy` / `1.0.0` |
| 项目授权 | 许可名称、授权人或内部授权记录引用；不提交保密正文 |
| 资源类型 | 本次实际处理的明文格式和路径范围 |
| 平台 | Windows、Linux 或 macOS，以及必要的运行时版本 |
| 源树哈希 | 提取前受支持资源集合的 SHA-256 指纹 |
| 输出哈希 | 构建清单和最终候选的 SHA-256 指纹 |
| 执行流程 | 记录标准操作序列和语言；实际命令仅在外部工单中保存脱敏版本 |
| HanGuard 结果 | 最终风险等级、允许操作和决策原因 |
| 内部验证 | 语法、编码、占位符、哈希和源树一致性结果 |
| 官方验证 | 官方编译器、导入器或编辑器验证结果；不可用时写明原因 |
| 运行冒烟 | 只在授权允许且环境隔离时执行，记录范围和结果 |
| 已知偏差 | 插件、字体、版本、语言包或运行时限制 |
| 结论 | `失败`、`可提取`、`可构建` 或 `已验证` |

## 人工补充模板

```text
验证记录 ID:
验证日期:
验证人员:
引擎与版本:
AdapterV1 ID / 版本:
项目授权引用:
资源类型与路径范围:
平台与工具链:
源树 SHA-256:
输出 SHA-256:
执行命令:
HanGuard 最终结果:
内部验证结果:
官方验证器结果:
运行冒烟结果:
已知偏差:
最终结论:
```

任何令牌、账号、私有项目内容、未脱敏绝对路径和原始游戏资产都不得写入 JSON 记录或人工补充记录。
