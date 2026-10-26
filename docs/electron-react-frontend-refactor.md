# HanEngine Electron + React 前端重构交付说明

本次重构把原 Tkinter 视图层替换为桌面端 Electron + React。Python 业务层保持原有边界：`cli.py`、`translator.py` 和 `game_localizer/` 继续负责扫描、提取、翻译、验证、构建和任务持久化，Electron 只负责窗口、路径选择、安全 IPC 和进程状态展示。

> 当前产品范围：HanEngine 是多引擎工具，不以 Ren'Py 为唯一目标。桌面端通过 `engine inspect`、AdapterV1 与 HanGuard 显示并执行 Ren'Py、RPG Maker MV/MZ、Godot、Unity、Unreal 等结构化项目工作流；旧 Ren'Py 明文提取/构建命令仅作为 CLI 兼容入口保留。任何引擎的封装、加密或未授权资源均只允许检测。

## 可直接使用的 Codex 提示词

```text
你正在维护一个本地游戏汉化工具。仓库根目录包含 Python 业务层：cli.py、translator.py、game_localizer/、tests/。请把桌面 GUI 从 Tkinter 迁移到 Electron + React，不得改变 Python 业务契约。

目标技术栈：
- Electron 主进程 + contextIsolation=true + nodeIntegration=false；
- preload 使用 contextBridge 暴露最小 IPC API；
- React + TypeScript + Vite；
- lucide-react 图标；
- CSS 使用 CSS variables，桌面优先，默认窗口 1440x920，最小窗口 1120x720；
- electron-builder 打包 Windows 安装包；
- 不引入浏览器端直接读写游戏项目的能力，所有文件系统和 Python 子进程操作只能由主进程完成。

必须保留的后端兼容性：
1. 单文件翻译继续调用 `python cli.py <resource> <dictionary> [--output ...] [--untranslated ...]`。
2. 引擎工作流继续调用 `python cli.py engine extract|build|localize ...`，保留 `--mode`、`--risk-level`、`--state-root`、`--dictionary`、`--cloud-endpoint` 等参数。
3. 任务中心继续调用 `python cli.py tasks list|show|retry|cancel`。
4. 不在 Electron 中复制翻译算法，不修改原项目资源，输出默认写入独立目录。
5. 所有 Python stdout/stderr 按任务 ID 推送到 React，显示开始、进度、完成、失败、取消状态。

界面结构：
- 顶部深色应用栏：品牌、工作模式 segmented control（普通 / 专业）、刷新和设置图标。
- 左侧工作栏：普通模式显示快速汉化与任务中心；专业模式额外显示工作台、单文件、封包输出与任务中心。
- 右侧工作区：面包屑、当前项目标题、动作栏、统计条、搜索过滤、翻译表、下方选中条目编辑器、底部任务状态栏。
- 翻译表列：ID、上下文、原文、译文、状态；行可选择，译文在下方 textarea 编辑，不把大量输入框塞进表格造成拥挤。
- 状态颜色：绿色已完成、琥珀色待定、红色草稿/需检查。颜色必须同时有文字，不得只依赖颜色。

请按以下顺序实现：
1. 新建 desktop/ 工程和 package scripts；
2. 编写 electron/main.cjs 和 electron/preload.cjs；
3. 编写 React 页面和 CSS；
4. 接入项目树扫描、catalog JSON 读取/保存和 Python CLI 运行；
5. 使用 `npm run build` 验证；
6. 在 1440x920 和 1120x720 截图检查：没有横向溢出、标题栏拖拽区不遮挡按钮、侧栏收起后工作区扩展、编辑器和表格互不重叠。

交付时报告：新增文件、IPC 契约、Python 命令映射、构建命令、未解决的环境依赖。不要删除或回滚用户已有改动。
```

## 布局示意

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ HanEngine     [ 普通 | 专业 ]                                ↻   设置     │
├───────────────┬────────────────────────────────────────────────────────────┤
│ [打开项目]    │ 专业 / Project / catalog.json             本地模式  打开目录 │
│               │ 翻译工作区                                                  │
│ 工作台        ├────────────────────────────────────────────────────────────┤
│ 单文件        │ [提取文本] [运行汉化] [保存]       引擎 [自动识别]           │
│ 封包输出      ├────────────────────────────────────────────────────────────┤
│ 任务中心      │ 总条目 1245   已完成 900   待翻译 345       catalog.json      │
│               ├────────────────────────────────────────────────────────────┤
│ 项目结构      │ 搜索 ID、上下文或文本      仅看待翻译                       │
│  ▾ project/   │ ┌────┬─────────────┬──────────────┬──────────────┬───────┐ │
│    ▾ locale/  │ │ ID │ 上下文       │ 原文         │ 译文         │ 状态  │ │
│       a.json  │ ├────┼─────────────┼──────────────┼──────────────┼───────┤ │
│       b.json  │ │... │ ...         │ ...          │ ...          │ ...   │ │
│               │ └────┴─────────────┴──────────────┴──────────────┴───────┘ │
│ 仅处理合法资源│ 当前条目 / dialogue/intro   原文 [只读]  译文 [textarea]    │
├───────────────┴────────────────────────────────────────────────────────────┤
│ ● HanEngine Core   模式：专业     Python CLI 已连接                     就绪 │
└────────────────────────────────────────────────────────────────────────────┘
```

## 技术实现要点

- `electron/main.cjs` 是唯一文件系统和子进程边界；React 不接触 Node API。
- `preload.cjs` 只暴露选择路径、扫描目录、读取/保存 catalog、运行 Python 任务、任务列表/详情/重试/取消和订阅事件。
- 开发环境使用仓库根目录作为 Python backend；打包环境通过 `extraResources` 放入 `hanengine-backend`，确保安装包仍能找到 `cli.py` 和 `game_localizer/`。
- `catalog:write` 先写临时文件再 rename，避免保存过程中产生半成品。
- 项目树只扫描有限深度，并跳过 `.git`、`node_modules`、构建产物和测试运行目录，避免大型游戏目录阻塞 UI。
- Python 输出通过任务 ID 归属，React 只更新当前任务的日志和状态；取消通过 `tasks cancel` 写入协作式取消请求，业务侧以 HanTask 持久化状态为准。
- 视觉上用 8px 间距基线、低对比边框和一个主强调色。翻译表不内嵌多行编辑框，改用下方编辑器，解决参考图信息拥挤问题。

## 本地运行

```powershell
cd desktop
npm install --registry=https://registry.npmjs.org
npm run build
npm run dev
```

如果 Electron npm 包已安装但 `electron/dist/electron.exe` 不存在，可使用镜像补齐运行时：

```powershell
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
node node_modules/electron/install.js
```

若运行时下载源仍不可用，可先执行 `npm run preview -- --host 127.0.0.1` 查看同一份 React UI；它不包含 Electron IPC，但布局和交互骨架完全一致。
