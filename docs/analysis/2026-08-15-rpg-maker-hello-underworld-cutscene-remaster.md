# Hello Underworld 过场视频项目专用重制记录

日期：2026-08-15

## 结论

Hello Underworld 中文候选 v4 已重制三段已知 WebM 过场。视频内嵌英文不是 RPG Maker JSON 提取遗漏，而是烘焙在美术帧中的栅格文字；本轮采用按镜头清除英文笔画、手绘字体重绘中文、保留逐字节奏和原 Opus 音轨的项目专用流程。

在 2026-08-15 的项目专用重制阶段，这项结果尚未形成 AdapterV1 通用 `raster_text` 流程，也不把 RPG Maker MV 真实项目结论从 `build_ready` 提升为 `verified`。2026-08-16 后续已把“审批产物安全写回”抽象为通用清单；自动 OCR、重绘和视频运行认证仍未因此获得通用证据。

## 2026-08-16 正式流程登记

三段项目专用产物已登记到 `hanengine.raster-manifest/v1`，共 14 个审批文字段；每段记录源文、译文、区域、3 fps 时间轴、站酷快乐体字号/角度和人工审批状态。

- 清单：`.tmp/rpg-maker-hello-underworld-raster-manifest-v1.json`
- 清单 SHA-256：`eb50362cae8b3431692ae58f629dd24f3f933afad3e28c25224c4ec71f3b9438`
- 验证报告：`.tmp/rpg-maker-hello-underworld-raster-verification-v1.json`
- 报告 SHA-256：`12bda767a397d27838ea80f9941426469f4d9400276ebf643c3fb53b023fac44`
- 验证结果：`passed=true`、`issues=[]`

验证器重新核对了授权固定源项目中的三个 WebM 源哈希、v4 产物哈希和 v4 候选哈希。该结果证明现有产物能进入正式候选写回/验证契约；它仍不替代 NW.js 运行验证，也不证明通用自动视频重制。

2026-08-16 已进一步用 `project validate --font --raster-manifest` 一次性生成 v6，三段 WebM、完整 CJK 字体和 `1954/1954` 个原生文本段同时进入 27 项构建清单。栅格验证仍为 `passed=true`、`issues=[]`，不再依赖项目专用复制脚本生成最终候选。

## 输入与输出

- 源项目：`CMPUT250HU/HelloUnderworld`
- 固定提交：`afbb145ca626a43ae73432c64724d9be17e9ae82`
- 项目许可：Apache-2.0
- 基础中文候选：`.tmp/rpg-maker-hello-underworld-zh-cn-v3`
- 过场中文候选：`.tmp/rpg-maker-hello-underworld-zh-cn-v4`
- 重制脚本：`.tmp/rebuild_hello_underworld_cutscenes.py`
- 字体：站酷快乐体，SIL Open Font License 1.1

三段输出继续使用 VP9 Profile 0、`1500x1250`、3 fps、`yuv420p`；原 Opus 48 kHz 立体声音轨按流复制保留。

| 文件 | 帧数 | 时长 | SHA-256 |
| --- | ---: | ---: | --- |
| `movies/cut scene 1 Final.webm` | 101 | 33.666 s | `c95fe06d52c009597fc3b3fa4a3d249dacbf3faa23e48f05fe5894939991a3b1` |
| `movies/cut_scene_2_Final.webm` | 73 | 24.333 s | `e34562c0c425ac4fbf5dfa8dd538f86d90299610782ad609cf745dfa2d08605d` |
| `movies/cut_scene_3_Final.webm` | 57 | 19.000 s | `8abbe9e04c3fa53dc283e66c50f9f7dd09ce8c4541ef48e92e3732d5d5b0153b` |

## 视觉处理

- 第一段使用无字镜头底板和局部黑色笔画修复，末句在火焰转场前结束。
- 第二段按六个真实镜头范围逐帧清除英文，不再粘贴包含人物残影的大矩形底板；淡出阶段使用相对亮度阈值清除残余英文。
- 第三段分别处理“里”“奥鲁斯”和“终”，校正姓名横向位置和片尾清除范围。
- 中文使用黑色手绘字形、轻微旋转和多行排版，不采用纯白正楷覆盖。
- 逐帧检查英文残留、人物遮挡、底板接缝、裁切、镜头边界和淡出边界。

关键帧证据位于 `.tmp/rpg-maker-hello-underworld-cutscene-qa-v4/`：

- `cut1-final-encoded.png`
- `cut2-final-encoded.png`
- `cut3-final-encoded.png`

## 运行验证

本地 HTTP 预览使用已安装的 Microsoft Edge，通过 Playwright 驱动实际进入标题菜单并点击“新游戏”。

- Source Han Sans Lite 请求：HTTP 200
- 第一段重制视频请求：HTTP 200
- 视频元素：`paused=false`、`readyState=4`
- 运行时分辨率：`1500x1250`
- 运行时报告时长：33.666 秒
- 控制台错误：0
- 运行截图：`.tmp/rpg-maker-hello-underworld-cutscene-qa-v4/cutscene1-runtime-v4.png`

浏览器报告一次旧播放请求被新媒体加载中断；随后第一段过场正常加载并持续播放。这是浏览器媒体切换备注，不等同于脚本异常，也不替代官方 NW.js 验证。

2026-08-16 又使用 NW.js 0.29.4 对原版和 v6 执行同口径探针。两者都进入 `Scene_Title` 和地图 12，三段视频均读取 `1500x1250` 元数据，运行事件为 0；v6 运行时数据库读取到中文角色名和 5 个中文敌人名。第一段视频固定到 5 秒后，原版仍显示英文 `YOU'VE BROKEN OUR DEAL ORUS`，v6 同画面显示黑色手绘中文。完整证据和边界见 `docs/analysis/2026-08-16-rpg-maker-hello-underworld-nwjs-validation.md`。

## 边界

- 证据只覆盖此固定项目的三个已知 WebM，不可外推为通用 OCR、图片修复或视频字幕能力。
- 启动徽标和标题徽标中的栅格英文不在本轮“过场动画”范围内。
- 已执行独立 NW.js 0.29.4 原版/候选冒烟，但探针尚未接入正式验证器，且第二、三段只验证元数据、未按剧情事件完整播放，因此结论保持 `build_ready`。
- 正式单流水线记录见 `.tmp/rpg-maker-hello-underworld-validation-record-v4-raster-full-font.json`；NW.js 报告位于 `.tmp/nwjs-rpg-maker-evidence/`。
