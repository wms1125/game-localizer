# 本地模型翻译提供方

HanEngine 的 `LocalModelTranslationProvider` 只允许访问本机回环地址，不会发送远程请求或读取翻译令牌。它用于把本地模型运行时接入现有的 `HanPipelineV1`，不负责下载、启动或训练模型。

## 运行时契约

请求使用 `POST` JSON：

```json
{
  "segment_id": "unity:example",
  "text": "Use [move] to move.",
  "source_language": "en",
  "target_language": "zh-CN",
  "context": ["tutorial"],
  "protected_tokens": ["[move]"],
  "reference_translation": "按住 [move] 键就能移动。"
}
```

运行时必须返回：

```json
{
  "translation": "使用 [move] 移动。",
  "provider": "local-runtime",
  "model": "model-name",
  "confidence": 0.92
}
```

`provider`、`model` 和 `confidence` 可省略。`translation` 必须是字符串。HanEngine 会在路由层拒绝丢失 `[move]`、`{name}`、`%s` 和字面量 `\\n` 的结果。

仓库内的 Ollama 桥接层还会拒绝模型凭空加入的物理换行、注释或警告，避免破坏 Unity TSV 单行格式；包含字面量 `\\n` 的文本会分片翻译并原样保留这些 token。

请求可选携带 `reference_translation`。比较报告中的游戏原简中可以逐条传入 Ollama，作为同一游戏的口语、语气、术语和标点风格参考。参考文本被作为独立 JSON 数据发送；模型仍需忠实翻译英文原文，不能照抄参考译文中无关内容。参考文本不会自动替换译文。

## CLI

```powershell
python cli.py engine localize auto `
  "D:\Games\REPO" `
  --output "D:\HanEngine\candidates\repo-zh" `
  --local-model-endpoint "http://127.0.0.1:8080/translate" `
  --local-model-name "local-zh-v1" `
  --state-root "D:\HanEngine\state\repo" `
  --mode player
```

当前命令假设本地模型运行时已经启动。模型权重管理、自动启动、资源检测和桌面端普通模式入口属于后续阶段；没有本地运行时或其他翻译来源时，HanEngine 会明确报告翻译来源缺失，不会伪造汉化结果。

## 第一版本地模型基线

当前按本机 8 GB RTX 4060 Laptop、约 16 GB 内存选择保守基线：

- 运行时：Ollama Portable；只监听本机回环地址。
- 模型：`qwen2.5:3b`（Qwen2.5 3B Instruct，首版以 Ollama 发布的量化标签为准）。
- 目标量化：约 4-bit、Q4_K_M 级别；以 `ollama show qwen2.5:3b` 的实际信息为准。
- 上下文：HanEngine 桥接层固定 8192；翻译请求按单段发送，避免长上下文挤占显存。
- 温度：0.1；翻译场景优先稳定、可复现和占位符完整性。

选择 3B 而不是 7B 以上模型是为了给游戏、Ollama 和显存留出余量。它是工程起点，不是语言质量结论；应先跑 100 条 R.E.P.O. 样本，再决定是否换更大的模型或建立术语库。

## Windows 启动步骤

安装 Ollama 后，在一个终端启动服务并确认模型可用：

```powershell
ollama serve
ollama pull qwen2.5:3b
ollama show qwen2.5:3b
```

再在第二个终端启动仓库内的协议桥接层：

```powershell
python tools\ollama_translation_server.py `
  --model "qwen2.5:3b" `
  --ollama-url "http://127.0.0.1:11434" `
  --host 127.0.0.1 `
  --port 8080
```

桥接层不会自动下载模型；模型不存在时请求会失败并写入基准报告。健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
```

先做 100 条基准，不要直接对整包写回：

```powershell
python tools\benchmark_local_model.py `
  "D:\steammm\steamapps\common\REPO" `
  --engine unity `
  --endpoint "http://127.0.0.1:8080/translate" `
  --model-name "qwen2.5:3b" `
  --sample-count 100 `
  --output "C:\Users\23256\Documents\汉化\.tmp\repo-local-benchmark.json"
```

只有基准报告中失败数为 0、延迟可接受，并完成人工抽查后，才进入 `cli.py engine localize` 的候选构建。报告中的译文仍需检查术语、语气、长文本布局和游戏内实际显示；模型响应成功不代表汉化完成。

### 使用游戏原中文指导重译

Unity 项目已有 `engine compare` 生成的对比报告时，可用 `--reference-report` 让本地模型逐条参考游戏原中文。报告必须与当前项目指纹一致。重译已有项目时同时传 `--no-resume`，否则 HanStore 中先前保存的译文会被直接复用：

```powershell
Set-Location 'C:\Users\23256\Documents\汉化\.worktrees\game-localizer'
py -3.12 cli.py engine localize unity `
  "D:\steammm\steamapps\common\How to Fish\How to Fish" `
  --output "D:\HanEngine\candidates\project-zh-style" `
  --local-model-endpoint "http://127.0.0.1:8080/translate" `
  --local-model-name "qwen2.5:3b" `
  --reference-report "D:\HanEngine\reviews\comparison.json" `
  --no-resume `
  --translated-catalog "D:\HanEngine\reviews\translated-style.json" `
  --review-queue "D:\HanEngine\reviews\review-style.json" `
  --state-root "D:\HanEngine\state\project" `
  --mode player
```

修改过 Ollama 桥接脚本后，先在运行桥接的终端按 `Ctrl+C` 停止旧进程，再从仓库根目录重新启动 `tools\ollama_translation_server.py`。否则旧进程仍会使用旧提示词，不会读取参考译文。

质量报告会把缺少官方译文句末标点的模型结果记为待审阅警告，不会一律阻断或机械补标点，因为菜单按钮、标题和短标签通常不需要句号。风格相似度、术语准确度和口语自然度仍需人工抽查。

## 质量门与断点恢复

`HanPipelineV1` 会在每个段完成后写入 `HanStore` 检查点。模型返回异常时，当前段不会写入候选，已经完成的段会保留；修复运行时或更换 Provider 后重新执行同一命令即可继续。

路由层会给失败标记稳定错误码，例如 `placeholder_mismatch`、`physical_newline_mismatch`、`metadata_contamination`、`residual_english`、`invalid_response` 和 `http_error`。Ollama 桥接对请求格式、占位符、换行、空响应、传输和上游 HTTP 错误分别返回 `error_code`；HanEngine 会把这个类别和桥接实际重试次数保留到任务 warning、命令行错误和质量报告中，不会把模型的坏结果静默写入资源。明确的请求格式错误不会重试。

建议为实际运行保存审阅队列：

```powershell
python cli.py engine localize unity `
  "D:\Games\AuthorizedProject" `
  --output "D:\HanEngine\candidates\project-zh" `
  --local-model-endpoint "http://127.0.0.1:8080/translate" `
  --local-model-name "qwen2.5:3b" `
  --translated-catalog "D:\HanEngine\reviews\project-translated.json" `
  --review-queue "D:\HanEngine\reviews\project-review.json" `
  --state-root "D:\HanEngine\state\project" `
  --mode player
```

`<output>.quality.json` 会包含完整摘要和同一份审阅队列；`--review-queue` 用于单独交给人工审阅。翻译中断时，报告和队列会保留已经完成段的质量元数据，并在失败段条目上写入 `failure`（包括错误类别、消息、段 ID 和任务 ID）。队列中的 `missing_translation`、`low_confidence`、`source_text_unchanged` 和结构控制符问题必须在构建候选前处理。`--quality-report` 与 `--review-queue` 必须使用不同路径，且两个文件都必须位于源项目和候选输出之外。
