# Renderer 文本相交硬门审计

日期：2026-08-14

## 前提审计

历史 `hanengine.renpy-renderer-observation/v1` 节点包含 `text`、`x`、`y`、`width`、`height`、`line_count` 和 `baseline`，但没有稳定区域 ID、Render 路径或绘制顺序。真实 v14 六场景中，部分矩形是 Render 节点的剩余布局空间，不是字形墨迹框；参考和候选各有大量正常相交。简单使用“矩形相交即失败”会产生确定性误报。

新采集使用 `hanengine.renpy-renderer-observation/v2`，增加：

- `region_id`：由 child-index Render 路径和 Text displayable 索引组成。
- `render_path`：从 surftree 根节点到当前 Render 节点的 child index 序列。
- `z_index`：探针遍历时记录的确定性绘制顺序。

v1 仍可读取和回归，但层级与绘制顺序明确为未知，不从几何伪造。

## 判定规则

硬门先建立参考和候选的可疑相交关系，再只阻断候选新增或显著恶化的关系。候选关系必须同时满足：

- 相交面积至少 16 平方像素。
- 较小区域至少 20% 被覆盖。
- 垂直相交和绝对文本基线支持同一行或相邻字形冲突。
- 两个区域不是 render path 父子关系。
- 两个区域不是相同文本、两像素内同几何的阴影/重复绘制层。
- 区域对没有登记在场景允许名单。

参考侧已有关系只有在候选相交面积至少增加 16 平方像素，且较小区域覆盖比例至少增加 0.15 时才视为显著恶化。v1 没有稳定 ID时，先用相同文本和最近几何执行确定性一对一匹配；该映射只用于历史参考比较，不宣称拥有层级证据。

失败检查代码为 `renderer_text_overlap`。`details` 记录场景、两个区域 ID、文本摘要、矩形、绝对基线、Render 路径、绘制顺序、前景区域、交叠矩形、面积、双向覆盖比例、双向可见比例和参考交叠。智谱判官启用时，`renderer_observation_coverage` 要求每个场景都有 renderer observation；失败会在 GLM 调用前直接 `blocked`。

## 测试样本

阴性样本覆盖父容器包含子文本、相同文本阴影/重复绘制层、不同基线的大布局框、参考与候选未恶化的既有相交，以及按场景允许的区域对。阳性样本覆盖候选新增同基线高比例文字冲突和前景绘制层覆盖，并断言 GLM 调用次数为 0。已有 `overflow` 与 `clipped` 硬门继续独立阻断。

## v14 回归

证据目录：`.tmp/visual-evidence-renpy-the-question-v14-renderer-zhcn-six/`

- manifest：`visual-manifest-renderer-overlap-regression.json`
- manifest SHA-256：`a58d0ff58fe15d778dabdb894c38406b73fcd40563464a2240aef76c741e99ce`
- report：`visual-report-renderer-overlap-regression.json`
- report SHA-256：`f1ea629c3fab0f6a46eb67ce5813806f76c42406ed22e1503a079ddac2616377`
- renderer 检查：6/6 通过，失败 0。
- 全部本地硬门：133/133 通过。
- 设置页参考/候选可疑关系：26/26，同构且无显著恶化，误报 0。
- 最终决定：`escalate`，唯一原因是回归刻意没有配置视觉模型；本次没有产生 GLM 费用。

磁盘报告由 `VisualEvidenceReport.from_dict` 严格读取后重新序列化，与原 JSON 对象完全一致；Electron 报告读取器也成功返回六场景摘要。

## 真实 renderer v2 验收

使用新探针对官方 SDK `The Question` 原文项目和已验证 v11 中文候选连续采集两次。两次报告分别位于：

- `.tmp/visual-evidence-renpy-the-question-v15-renderer-v2-run1-r2/capture-report.json`，SHA-256 `e5f778b5ffae31c7b531aaa172853bf54d566950d1218c45c76488d76793fc47`。
- `.tmp/visual-evidence-renpy-the-question-v16-renderer-v2-run2/capture-report.json`，SHA-256 `111f7df6272b752c5789abe04a1521c3f6fe390c5cc52ce71c411af9b3e60f2e`。

两次均为原文/中文 `6/6 + 6/6` screen 断言通过，且 12 组 observation 全部使用 `hanengine.renpy-renderer-observation/v2`。逐场景比较 `region_id`、`render_path`、`z_index`、文本、坐标、尺寸、行数和 baseline，不稳定项为 0；12 张 PNG 的 SHA-256 也跨次一致。每侧六场景区域数依次为 `8/9/11/37/30/30`，所有 ID 和 z-order 均唯一。用 v2 数据执行相交硬门时六场景误报为 0；设置页保留 26 个参考/候选同构关系而不误报，其余五场景为 0。

仓库自有真实运行 fixture 位于 `tests/fixtures/renpy_renderer_overlap/`。参考和候选只存在一个受测试锁定的差异：第二段文字从 `xpos 650` 移到 `xpos 250`。SDK 8.5.3 实际采集、`visual prepare` 和 `visual verify` 全链路结果：

- capture report SHA-256：`817f61221bc6bb2e901e0ebc6ad62eed6518d9fc791ce37f6fd876319307048b`。
- visual manifest SHA-256：`5750ad1f8f109540884825709d764cf5f458ad12a200cdf25a936b634980b13b`。
- visual report SHA-256：`ef11cded850d03eb5d01f2dcf751074a305908fa9499b47b44b99fb09f66afd8`。
- 最终决定为 `blocked`，唯一失败码为 `renderer_text_overlap`；交叠矩形为 `(258, 251, 386, 48)`，面积 `18528 px²`，较小区域覆盖率 `69.42%`。
- 报告记录两侧区域 ID、文本、坐标、绝对 baseline `289`、render path、z-order 和前景区域；严格 JSON 往返通过。
- 验收使用一旦调用即失败的 `ZhipuImageVisualJudge` 计数子类，并同时启用固定本地 OCR 帧以满足生产组合契约；报告提供方为 `zhipu:glm-4.6v`，GLM 调用次数为 0，证明硬门发生在模型费用之前。该短路报告 SHA-256 为 `d2e5e9699fc24c9f5a27a2a113ebabf8163133ca725093e4bf69908ef9cc80f8`，没有发出网络请求。

最终采集从仅包含四个受版本控制 `.rpy` 文件的干净临时树运行，参考/候选源树指纹分别为 `578c258cd3e487216aa82ffecf1ed30b00d014ed21e8eda4cb1ecd017b9fbb20` 和 `a6c641d907a70a8c6b274798e22be705c068354a107deded4928c6c4aae53705`，不把本机 `.rpyc`、cache 或 saves 当作 fixture 身份。

本里程碑另形成机器可读汇总报告 `.tmp/renderer-v2-milestone-report.json`，schema 为 `hanengine.renderer-v2-milestone-report/v1`，SHA-256 为 `62056f6bc2de15ed4d521cb3369b64ce2282d52ff0bbc12cdb04956711b3145b`。报告绑定上述两次真实采集、真实覆盖 capture/manifest/report 和智谱短路报告的六个哈希，逐场景记录五类稳定性断言、误报数、反算后的交叠几何、GLM 零调用和本轮完整测试结果；六个引用哈希与 JSON 对象往返已重新校验。

## 验证

- Python：549/549 通过。
- Electron：10/10 通过。
- TypeScript 与 Vite 正式构建通过。
- `git diff --check` 通过。
- 扫描的源码与文档中未发现 API-key 形状字面量。

## 剩余风险

本轮已经消除 v2 路径/绘制顺序未经过真实 Render 树验证的风险。当前证据覆盖 Ren'Py 8.5.3、官方 `The Question` 六场景和仓库自有覆盖 fixture；它不证明其他 Ren'Py 版本、第三方自定义 displayable 或所有动画状态都具有相同稳定性，这些应在新增版本兼容范围时分别验收。
