# Godot Open RPG 4.6.2 基线校验

日期：2026-08-14  
结论：汉化候选保持 `failed`；官方校验阻断可在原始上游项目中独立复现。

## 输入与工具

- 上游：GDQuest `godot-open-rpg`，固定提交 `19bd328fae9e4b534d3bb6db380a3d871d6ea58f`，MIT License。
- 上游 README 明确要求 Godot `4.6.2`，`project.godot` 声明特性版本 `4.6`。
- 官方工具：`Godot 4.6.2.stable.official.71f334935`。
- Windows ZIP：`.tmp/Godot_v4.6.2-stable_win64.exe.zip`。
- ZIP SHA-512 与 Godot 官方 `4.6.2-stable` 发布资产 `SHA512-SUMS.txt` 一致。
- 原始上游项目树 SHA-256：`4ae71b13ce6738ba17ba511f5f19400cac2be55f393a3739739ff5bd0d2b8091`。
- 本地化源树 SHA-256：`00c1853ca595f8cb391efa13370543b184f2d8f27a381f02c468b78b379fcd27`。

## 对照方法

对下列三个项目分别创建独立影子副本，并连续执行两遍：

```text
Godot_v4.6.2-stable_win64_console.exe --headless --editor --path <shadow> --quit
```

1. 下载后未做本地化准备的原始上游项目。
2. 注册了本地化资源、但目标字段仍为空的本地化源项目。
3. HanEngine 中文候选。

三个正式目录在校验前后均保持原树哈希，Godot 导入缓存只写入影子副本。

## 结果

原始上游、派生源和中文候选都在第二遍报告同一错误：

```text
SCRIPT ERROR: Invalid access to property or key 'PortraitContainers' on a base object of type 'Nil'.
   at: DialogicNode_PortraitContainer._ready (res://addons/dialogic/Modules/Character/node_portrait_container.gd:89)
```

原始上游与中文候选的第二遍日志逐字节相同，SHA-256 均为 `13d9d1981d94291540c99f71ef784cb924b3199bce2897d792a705364b816679`。本地化源日志还包含尚未导入的 `.translation` 资源告警，但决定性 `SCRIPT ERROR:` 与另外两边相同。

本轮同时发现并修复了 Godot CSV 新目标列使用公共标识 `zh-CN` 的问题。HanEngine 现在保留工作流语言 `zh-CN`，写入 Godot CSV 时规范为原生列名 `zh_CN`。修复后的 v8 候选树与已人工查看的 v6 候选树完全相同：

```text
c1705a618979e20dc82ad3b7d1b9386d62c91d4046901bd4029947af38a5873e
```

v8 记录结果：

| 检查 | 结果 |
| --- | --- |
| 翻译完整性 | `97/97`，未翻译 `0` |
| 运行时名称 | `Bugcat/Wolf/Baloo/Nutsy` 等稳定实体名已写入 |
| 字体覆盖 | 通过，缺失码点 `0` |
| 视觉样式硬门 | `7/7` 通过 |
| Godot 两遍官方校验 | 失败，第二遍命中 `SCRIPT ERROR:` |
| 原主场景认证冒烟 | 未执行；被官方校验硬门阻断 |
| 最终结论 | `failed` |

战斗预览截图仍可证明中文名称、像素字体、黑色描边和布局效果，但不能替代原主场景运行冒烟或官方校验。

## 证据哈希

| 证据 | SHA-256 |
| --- | --- |
| Godot 4.6.2 Windows ZIP | `14293422efb54b24a51f79d4cb55ab4001ef3d936e064a6c8af32e1f984024be` |
| 官方 `SHA512-SUMS.txt` | `2f8e1f5e146b2125855798cf0914cf7bef8f49de071b216e59b99434e69cd18d` |
| `.tmp/godot-open-rpg-validation-record-v8-godot-4.6.2.json` | `39c31caa2711db1bf2fe2dd50ceaa99c34f020f3e1a5e24fe8b7ce046466b5ca` |
| 原始上游第二遍日志 | `13d9d1981d94291540c99f71ef784cb924b3199bce2897d792a705364b816679` |
| 本地化源第二遍日志 | `e92db290e3f493564905b31e5f6175d6d9de8cb90ceac2509ab8de337f529163` |
| 中文候选第二遍日志 | `13d9d1981d94291540c99f71ef784cb924b3199bce2897d792a705364b816679` |
| 中文战斗预览截图 | `857df5101f924af981900f22a42fd54790ba260543b3d1145b8063e17bb5bedc` |

## 判定

该结果证明 Open RPG 的官方编辑器校验阻断不是汉化候选独有回归。不能修改验证规则绕过 `SCRIPT ERROR:`，也不能把预览画面通过写成 `verified`。Godot 的正式认证仍由 `godot-dodge-the-creeps-v3-style` 提供；Open RPG 只作为大项目名称发现和样式保留证据。
