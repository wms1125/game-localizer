# Godot Dodge the Creeps 真实项目认证

日期：2026-08-14  
结论：`verified`（Godot 4.7.1、明文 PO 原生写回和源样式保留范围）

## 来源与授权

- 上游：`godotengine/godot-demo-projects` 的 `2d/dodge_the_creeps` 官方样例。
- 固定提交：`34fc99545fc41520a958248f607101e7d0b95b05`。
- 获取方式：GitHub API 按目录下载 45 个文件，未使用不完整的仓库克隆作为来源。
- 许可证：样例随附 MIT `LICENSE`，Copyright 2017 KidsCanCode。
- 本地派生：在授权副本中注册 `locale/game.po`，将四个 HUD 文本接入 `tr()`，并配置 `SourceHanSansLite.ttf`。源 PO 的四个目标字段保持为空，由 HanEngine 候选写入中文。

该认证不覆盖 Godot 3.x、CSV、通用动态文本、栅格文字或 PCK 修改。

## 工具与输入

- 官方工具：Godot `4.7.1.stable.official.a13da4feb`。
- 源项目：`.tmp/godot-official-dodge-the-creeps`。
- 字典：`.tmp/godot-dodge-dictionary.zh-CN.json`，4 个条目。
- 最终候选：`.tmp/godot-official-dodge-candidate-v3-style-final`。
- 最终记录：`.tmp/record-godot-dodge-the-creeps-v3-style-final.json`。
- 记录 ID：`godot-dodge-the-creeps-v3-style`。
- 运行证据：`.tmp/godot-evidence-v2-style/`；从与最终候选树哈希一致的预检候选采集。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 源树 SHA-256 | `a3b8d262a8f04ff171fd4836ba478208cd7e67c344c7c16ec6af87b691fd3cf7` |
| 候选树 SHA-256 | `1cd839eb354345fe42fad4254497c34367eb93b6f5fc98638336194b065e837b` |
| 源树保持不变 | 通过 |
| 翻译完整性 | `4/4`，未翻译 `0` |
| 候选 PO | UTF-8、PO 语法和产物哈希通过 |
| 官方校验 | 同一影子候选冷导入 + 第二遍干净检查，Godot 退出码 `0`，错误标记 `0` |
| 字体覆盖 | `SourceHanSansLite.ttf`，缺失码点 `0` |
| 视觉样式硬门 | `7/7`；源 `.theme/.tres/.tscn`、字号、颜色和描边保持不变，字体与 autoload 通过 |
| 运行冒烟 | Windows OpenGL 3.3，原文/中文各录制 2 帧，退出码 `0` |
| 已知偏差 | 无 |

候选新增 `hanengine/locale_style.gd`、`hanengine/fonts/SourceHanSansLite.ttf`，并在 `project.godot` 注册 `HanEngineLocaleStyle`。autoload 只选择语言并设置完整 CJK 字体，不覆盖字号、颜色或描边；源场景中的 60px 字号、白色文字和按钮样式保持原样。

官方校验在临时影子候选中生成 `.godot`、UID 和字体导入缓存，因此记录中的 `validator_tree_preserved` 为 `false`；这些路径没有写回正式候选，`output_tree_preserved` 为 `true`，校验前后候选树哈希一致。第二遍输出未出现 `SCRIPT ERROR:`、`FATAL ERROR:` 或 `CRASH HANDLER:`。

运行冒烟使用预检候选完成就地资源导入。该候选在导入前的树哈希与最终候选完全相同，均为 `1cd839eb354345fe42fad4254497c34367eb93b6f5fc98638336194b065e837b`。源帧显示 `Dodge the Creeps` / `Start`，候选帧显示“躲避敌人”/“开始”，中文无方框、裁切或重叠。两帧的背景像素均为 `(56, 95, 97)`，按钮像素均为 `(37, 53, 54)`，证明候选没有改写原作背景和按钮颜色。

## 证据哈希

| 证据 | SHA-256 |
| --- | --- |
| `.tmp/record-godot-dodge-the-creeps-v3-style-final.json` | `129f1ee25c8f9f38c80450696544a80ee02bccddb103a1fbf258dc07b629d940` |
| `.tmp/godot-evidence-v2-style/import.log` | `b7e8693d1a38ba3e28de0e5938ed2d5775dfe17f812e63a7879a922bf1e99c67` |
| `.tmp/godot-evidence-v2-style/source-runtime.log` | `34ef427ae5f9f3c7f6fc2e1f21d2b101f19ccc7b5870b30dfa6a03a2199877a0` |
| `.tmp/godot-evidence-v2-style/candidate-runtime.log` | `0157b5f5bdef5a02399e2f37fcbe555828687703beb05fd52b1830d25ebc6948` |
| `.tmp/godot-evidence-v2-style/source-frame00000001.png` | `1d5fd35a5097f7fc7135e2cc3c1e1dd344b55862ee3de5136721bc2ee085aba4` |
| `.tmp/godot-evidence-v2-style/candidate-frame00000001.png` | `c999d1ec0b2825d4c914ddff50562d5c185999c0036b274086afface0fabb399` |

## 判定

`hanengine.godot` 的 `native_text_replace` 在 Godot 4.7.1 明文 PO 范围内保持 `verified`，当前证据引用更新为 `godot-dodge-the-creeps-v3-style`。其他能力状态不变：动态文本仍为 `detect_only`，栅格文字仍为 `unsupported`，PCK 仍仅检测。
