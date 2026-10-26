# Hello Underworld NW.js 原版/候选验证记录

日期：2026-08-16

## 结论

RPG Maker MV Hello Underworld v10 已完成一次正式的“原生文本 + 完整 CJK 字体 + 标题图片 + 三段栅格视频”联合构建，并通过集成在 `project validate` 中的 NW.js 0.29.4 原版/候选运行验证。结构化验证、字体覆盖、样式硬门、4 个栅格资源哈希、标题场景、起始地图、中文角色/敌人名，以及三段视频的 14 个审批时间段均通过，源树和候选树在运行验证前后均未改变。正式标题截图显示重绘后的“冥界”，不再加载英文 `ASPHODEL` 美术。

固定项目、固定提交和固定资源范围的结论提升为 `verified`。这里的运行覆盖是通过真实 `Game_Interpreter.command261` 路径逐一加载三个审批 WebM，并在 14 个时间段中点采集画面；它不等同于玩家从头到尾自然推进完整剧情。

## 固定输入

- 上游：`CMPUT250HU/HelloUnderworld`
- 提交：`afbb145ca626a43ae73432c64724d9be17e9ae82`
- 许可：Apache-2.0
- 源树 SHA-256：`1fedc798d183cbdc8e9cdbe45d2872e529f05ffbba99b833b51509c35700947d`
- 栅格清单：`.tmp/rpg-maker-hello-underworld-raster-manifest-v2.json`
- 清单 SHA-256：`6adb2a37f2e1758d3aba1adc5a6cdc32f1f2fd14be6c368eb48beddf8863bc60`
- 标题本地化产物：`.tmp/rpg-maker-hello-underworld-title-art-v3/Asphodel_v3.zh-CN.png`
- 标题产物 SHA-256：`9a479d5c2554b2e01bc067490402a73c6cf2b9d003584c775e6cd57cfc0ce881`
- 标题显示字体：ZCOOL KuaiLe 2.001，SIL OFL 1.1，SHA-256 `812a6fc1fe54b6d73a419245c32dfeba8aa33104d5be90d1cf6af082007cb71d`
- 确定性重绘脚本：`tools/render_hello_underworld_title.py`；独立复跑产物与审批产物哈希一致，下方图腾保护区域逐像素一致
- 字典 v2 SHA-256：`50fb33e1b658a28af56bc73c8e7a095bcddbc7bb80235cba67aee0cf40acfb8f`
- 字体：Adobe Source Han Sans SC Regular，固定提交 `a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2`，SIL OFL 1.1
- 字体 SHA-256：`f1d8611151880c6c336aabeac4640ef434fa13cbfbf1ffe82d0a71b2a5637256`

字典 v2 与 v1 只有一处差异：从“你是什​​么”中移除两个误入的 `U+200B` 零宽空格。中点 `U+00B7` 和音乐符号 `U+266B` 是可见内容，继续保留并由完整字体覆盖。

## 最终联合构建

- 候选：`.tmp/rpg-maker-hello-underworld-zh-cn-v10`
- 候选树 SHA-256：`8c649b631b762f50d23ff542a5227036e235866aa31b49a5a2b1844a11bfc333`
- 验证记录：`.tmp/rpg-maker-hello-underworld-validation-record-v8-nwjs-title-art.json`
- 记录 SHA-256：`042d41169ec336e4dcb328ac5ee609a06595b635b5a90a158a5f24cbc9796c75`
- 记录结论：`verified`
- 文本：`1954/1954` 写回，`untranslated_count=0`
- 构建清单：28 项，包含 22 个 JSON/样式资源、完整字体、标题 PNG 和 3 个 WebM
- 字体覆盖：`passed`，缺失码位 0
- RPG Maker 样式硬门：4/4 通过
- 栅格验证：4 个资源、15 个审批文字段，`passed=true`、`issues=[]`
- NW.js 正式验证：`passed`，29/29 检查通过，运行问题 0
- 候选验证：语法、UTF-8、路径和产物 SHA-256 全部通过
- 源树保护：构建前后均为 `1fedc798...00947d`
- 候选树保护：运行验证前后均为 `8c649b63...c333`

首次联合构建 v5 被字体覆盖硬门正确阻断：Source Han Sans Lite 缺少 `U+00B7`、`U+200B` 和 `U+266B`。该候选和失败记录保留用于证明硬门有效，没有覆盖成通过结果。

运行验证开发中还保留了两份不可作为通过证据的记录：`validation-record-v5-nwjs.json` 是一次 NW.js 启动失败；`validation-record-v6-nwjs.json` 虽曾输出 `verified`，但审计发现旧探针复用了前一视频的 `readyState`，第二、三次命令没有证明切换到目标文件，因此该记录已撤销。最终探针要求 `Graphics._videoLoading=false` 且规范化 `currentSrc` 精确匹配当前清单路径，报告 schema 升级为 `hanengine.nwjs-rpg-maker-validation/v2`。

## NW.js 证据

运行时从官方 `https://dl.nwjs.io/v0.29.4/` 下载：

- 包：`nwjs-v0.29.4-win-x64.zip`
- 本地下载 SHA-256：`806cb45519af60b184ce3a4e0f573b4d64e43d9758e552787a965ac18b821b1b`
- NW.js：0.29.4
- Chromium：65.0.3325.181
- `nw.exe` SHA-256：`141dd6c7281ff31f31aa1ad01913d32dd4ae679b27031cccd95b88fdbea0cd0b`

该历史目录的 `SHASUMS256.txt` 只列 `nw-headers-v0.29.4.tar.gz`，不列 Windows ZIP；以上 ZIP 哈希是本次下载证据，不表述为上游签名。

| 检查 | 原版 | v10 |
| --- | --- | --- |
| 标题场景 | `Scene_Title` | `Scene_Title` |
| 游戏标题 | `Main` | `冥界` |
| 标题美术 | `ASPHODEL` | 符文轮廓“冥界” |
| 起始地图 | 地图 12，玩家 `(1,1)` | 地图 12，玩家 `(1,1)` |
| 角色名 | 6 个英文名 | 6 个中文名 |
| 敌人名 | 5 个英文名 | 蝙蝠、史莱姆、兽人、弥诺陶洛斯、刻耳柏洛斯 |
| 字体就绪 | `true` | `true` |
| 三段视频 | 三条 `loaded_path` 精确匹配 | 三条 `loaded_path` 精确匹配 |
| 视频尺寸 | 均 `1500x1250` | 均 `1500x1250` |
| 视频时长 | 约 33.67 / 24.34 / 19.01 秒 | 约 33.67 / 24.33 / 19.00 秒 |
| 14 个审批区间 | 英文原画帧 | 黑色手绘中文，14/14 已人工检查 |
| 运行事件 | 0 | 0 |

最终机器报告：

- 目录：`.tmp/rpg-maker-hello-underworld-nwjs-evidence-v6-title-art/`
- 候选绑定报告：`validation-report.json`
- 报告 SHA-256：`e094b0bb1ab5b2199927b08947291fb7aff3d4b44308daa2cc866d3e3020155e`
- 证据文件：35 项，包含原版/候选各自的原始报告、标题、地图和 14 个视频区间截图，以及候选绑定总报告

早期单帧机器报告保留为历史证据：

- 原版：`.tmp/nwjs-rpg-maker-evidence/original-v2-report.json`，SHA-256 `01173f23ad07a559025fb0489a872549c235a6789a623cd204207a759b2f6213`
- v6：`.tmp/nwjs-rpg-maker-evidence/v6-v2-report.json`，SHA-256 `2ec79f522d0ee311c05e2d46b7212707cab6be28fb00bc003820b3b08a6b7319`
- 原版 5 秒截图：`.tmp/nwjs-rpg-maker-evidence/original-v2-cutscene-5s.png`，SHA-256 `c03978f40890562025b9952d955e60b23fcdee62a7522e60adb417d11cc3b369`
- v6 5 秒截图：`.tmp/nwjs-rpg-maker-evidence/v6-v2-cutscene-5s.png`，SHA-256 `f16e4fa3a906f848c5e7a52ea3166f11dbdcd8697f3598d8caba161f302db88b`

最终探针打包在 `game_localizer/hanengine/nwjs_rpg_maker_probe.js`。影子包只硬链接只读资源，使用独立 `save` 和一次性 `--user-data-dir`；标题和 14 个视频区间截图必须存在、哈希匹配且非空白。起始地图在此项目的开场时刻本来就是纯黑画面，因此地图截图只检查文件、哈希和尺寸，同时用 `Scene_Map` 与地图 12 的运行状态证明加载成功。

## 剩余边界

- 直接 `command261` 逐资源验证不证明玩家自然推进了全部地图、战斗、分支和结局。
- 本记录只覆盖固定提交、固定候选、一个已审批标题图片和三个已审批 WebM，不外推到其他 RPG Maker MV 项目、MZ、通用 OCR 或自动图片/视频重绘能力。
- 通用 `raster_text` 能力仍保持 `implemented`；本次 `verified` 只属于 Hello Underworld 的固定项目范围。
