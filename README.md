# 本地游戏汉化辅助工具

这是一个无需联网、无需第三方依赖的本地翻译辅助工具。它使用 JSON 字典翻译你合法拥有或已获授权的游戏明文资源，并生成汉化结果和待翻译清单。

仅用于合法拥有或已获授权的游戏资源；不支持破解、解密、绕过保护或用于传播盗版内容。

## 快速开始

示例文件位于 `examples/`。运行后会匹配四个字典条目，`Options` 会作为未匹配条目写入待翻译清单。

```powershell
python cli.py examples/game.json examples/dictionary.json
python cli.py game.csv dictionary.json --output translated.csv
python cli.py game.txt dictionary.json --untranslated todo.json
python gui.py
python -m unittest discover -s tests -v
```

命令行的 `--output` 用于指定汉化资源输出位置，`--untranslated` 用于指定待翻译 JSON 清单的位置。运行 `python cli.py --help` 可查看参数说明和授权提示。`python gui.py` 启动提供相同处理能力的本地图形界面。

## 项目引擎检测（Phase 1）

可先对你合法拥有或获明确授权的游戏项目目录进行只读检测：

```powershell
python cli.py engines
python cli.py detect "C:\Games\AuthorizedProject"
python cli.py detect "C:\Games\AuthorizedProject" --json
```

Phase 1 **仅扫描文件名和目录结构**，用于识别 Ren'Py、RPG Maker MV、RPG Maker MZ、Godot、Unity 与 Unreal Engine 的证据；它不会读取或解析资源内容。退出码 `0` 表示自动选定了一个高置信度引擎；退出码 `2` 表示未知、不确定或证据冲突，且项目不会被修改。

本版本的所有适配器均为 `experimental`，能力均为 `detect_only`。检测不会创建、修改、解包、执行或删除项目资源；Unity、Unreal、Godot 的封包容器，以及 Ren'Py 归档，均不会被解包或修改。

原有的单文件翻译命令仍然可用，例如 `python cli.py game.json dictionary.json`；它们仅面向前述受支持的明文资源，且同样只应处理你拥有合法权利或已获授权修改的内容。

## 翻译字典

字典必须是 UTF-8 编码的 JSON 对象：键是原文，值是简体中文译文。例如：

```json
{
  "New Game": "新游戏",
  "Hello, {name}!": "你好，{name}！"
}
```

也就是 `{ "原文": "中文" }` 的格式。键和值都必须是字符串，键不能是空字符串。项目提供的 `examples/dictionary.json` 以英文→简体中文为主，并保留一个日文条目，方便确认多语言字典兼容性。

请保留原文中的占位符，例如 `{name}`、`{0}`、`%1`、`%s` 与换行标记 `\\n`。工具会报告译文缺少的占位符，但不会自动修复；请在交付前人工核对所有警告。

## 支持的资源与输出

只处理以下**明文**资源扩展名：`.txt`、`.ks`、`.rpy`、`.script`、`.csv`、`.json`。输入会依次识别 UTF-8 BOM、UTF-8、CP932 和 Shift-JIS；无论输入编码为何，输出一律为无 BOM 的 UTF-8。

默认情况下，工具不会覆盖源文件：

- `game.json` 会生成 `game.zh.json`
- 同时生成 `game.untranslated.json`，其中包含可补充进字典的未翻译原文

汉化文件和待翻译清单会作为一对事务写入：任一写入失败时会回滚两者，避免只更新其中一个。重新执行可覆盖已有输出；本次实际覆盖的每个目标都会在 CLI 和 GUI 日志中逐项提示。

对于 JSON，仅翻译字符串值，绝不改动对象键；CSV 按完整单元格精确匹配；纯文本按最长键优先进行单次行内替换。压缩包、二进制、加密、受保护或需要反编译的游戏资源不在支持范围内。

## 本地与授权限制

所有处理都在本机离线完成：本工具不会调用网络服务、上传资源或下载翻译。请先备份原始游戏文件，并仅处理你拥有合法权利或明确授权修改的资源。使用本工具不提供破解、解密、规避 DRM 或其他保护措施的能力或指导。
