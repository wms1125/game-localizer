# HanEngine 美术资源汉化流程

更新时间：2026-08-16

本文定义图片和视频内嵌文字的正式汉化流程。它与原生文本共用同一候选构建，不覆盖源项目，也不把 OCR 结果直接视为可发布译文。

## 1. 适用范围

当前清单支持以下明文项目资源：

- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`
- 视频：`.webm`、`.mp4`

加密封包、引擎专有二进制资源、DRM、反编译和运行时注入不在此流程内。栅格流程只处理已经能以普通文件访问且用户有权修改的资源。

## 2. 标准流程

```text
资源发现 -> OCR/人工识别 -> 翻译 -> 风格重建 -> 生成独立产物
        -> 人工审批 -> 候选构建 -> 哈希/残留/运行验证
```

1. **资源发现**：扫描支持的图片和视频，记录项目相对路径、资源类型和源 SHA-256。只发现媒体文件时不伪造 OCR 文本，资源进入人工复核。
2. **文字识别**：OCR 或人工标注生成文字段，保存原文、矩形区域、置信度；视频段还保存起止毫秒。
3. **翻译**：目标文本写入同一个文字段，状态由 `detected` 变为 `translated`。低置信度、遮挡、装饰字或无法判断语义的内容改为 `manual_review`。
4. **风格重建**：记录原字体特征、字号、填充色、描边色、描边宽度和旋转角。重绘必须以原资源为参考，不使用统一白色正楷覆盖所有场景。
5. **产物生成**：图片或视频重制工具把结果写到清单目录下的独立文件。视频工具还必须保持预期分辨率、时长、帧率和音轨；这些项目级检查不由文件复制步骤代替。
6. **人工审批**：确认译文、排版和画面风格后，把段状态改为 `approved`，并登记本地化产物相对路径和 SHA-256。同一资源中只要有一个段未审批，整个资源都不会写入候选。
7. **候选构建**：AdapterV1 先完成原生文本写回，再把审批通过的美术产物合并到同一个独立候选目录。源文件或本地化产物哈希不匹配会阻断整个构建。
8. **验证**：检查源资源未变化、审批状态、产物哈希和候选哈希。未审批资源必须与源资源一致，并在报告中保留 `raster_manual_review_required`。

## 3. 清单契约

清单 schema 为 `hanengine.raster-manifest/v1`。

每个资源至少记录：

- 项目相对路径、`image`/`video` 类型和源 SHA-256
- 本地化产物相对路径和 SHA-256；相对路径以清单所在目录为根
- 资源级人工复核原因
- 所有栅格文字段

每个文字段至少记录：

- 全局唯一 `segment_id`
- 资源路径和资源类型
- 原文、目标文本和审批状态
- 画面矩形区域
- 视频起止毫秒
- OCR 置信度
- 字体、字号、颜色、描边和角度
- 人工复核原因

清单使用严格 JSON 读取：缺字段、多字段、重复资源、重复段、绝对路径、`..` 路径穿越、类型与扩展名不一致都会失败。

## 4. 状态规则

| 状态 | 含义 | 可写入候选 |
| --- | --- | --- |
| `detected` | 已识别原文，尚未翻译 | 否 |
| `translated` | 已有译文，尚未完成画面审批 | 否 |
| `manual_review` | OCR、译文或风格存在不确定性 | 否 |
| `approved` | 译文和画面均已人工确认 | 是 |

`approved` 是人工发布门，不是 OCR 置信度的别名。低置信度段可以在人工核对后批准，但不能由构建器静默提升状态。

## 5. CLI 使用

先生成媒体库存：

```powershell
python cli.py raster prepare <project> --output <raster-manifest.json> --language zh-CN
```

`prepare` 当前只生成图片/视频库存和源哈希。OCR、翻译、风格标注、图片重绘和视频重制工具需要补全清单及产物。

把审批后的清单接入完整汉化：

```powershell
python cli.py engine localize rpg_maker_mv <project> `
  --output <candidate> `
  --dictionary <dictionary.json> `
  --raster-manifest <raster-manifest.json>
```

也可以在已有翻译目录构建时使用同一参数：

```powershell
python cli.py engine build rpg_maker_mv <project> <catalog.json> `
  --output <candidate> `
  --raster-manifest <raster-manifest.json>
```

生成独立验证报告：

```powershell
python cli.py raster verify <project> <raster-manifest.json> `
  --candidate <candidate> `
  --output <raster-verification-report.json>
```

## 6. 能力边界

AdapterV1 的 `raster_text=implemented` 只表示：严格清单、人工审批门、源/产物哈希检查、独立候选写回和候选验证已经接入。

以下内容仍需后续实现或按项目提供：

- 通用 OCR 和视频逐帧文字跟踪
- 自动字体识别、纹理修补和原作风格复刻
- 图片英文残留 OCR 硬门
- 视频分辨率、时长、帧率、音轨和关键帧的通用验证器
- 各引擎和真实项目的运行时认证

因此，Hello Underworld 的项目专用 WebM 重制可以作为清单产物输入，但不能单独把通用视频重制能力提升为 `verified`。
