# HanEngine 适配器接口契约 v1

日期：2026-08-05

状态：设计契约，等待书面规格最终审阅

## 1. 目的

本契约定义 HanEngine 引擎适配器的稳定边界。适配器只负责特定引擎或输入类型的检测、提取、校验、候选输出构建、验证和回滚；翻译路由、任务调度、风险策略、数据库和 GUI 不得进入适配器实现。

契约标识为 `hanengine.adapter/v1`。所有适配器必须声明唯一 `adapter_id`、契约版本、适配器版本、支持的引擎版本范围、能力和成熟度。

## 2. 共同类型

### 2.1 枚举

| 类型 | 允许值 |
| --- | --- |
| `AdapterMaturity` | `DETECT_ONLY`、`EXTRACT_READY`、`BUILD_READY`、`VERIFIED` |
| `AdapterCapability` | `DETECT`、`EXTRACT`、`VALIDATE`、`BUILD`、`VERIFY`、`ROLLBACK` |
| `Operation` | `DETECT`、`EXTRACT`、`VALIDATE`、`BUILD`、`VERIFY`、`ROLLBACK` |
| `IssueSeverity` | `INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `ArtifactKind` | `PATCH`、`MANIFEST`、`BACKUP`、`REPORT`、`UNTRANSLATED_LIST` |

### 2.2 `AdapterMetadata`

必须包含：

- `adapter_id`：反向域名风格的稳定标识，例如 `hanengine.renpy`。
- `contract_version`：固定为 `hanengine.adapter/v1`。
- `adapter_version`：语义化版本。
- `engine_name` 和 `supported_engine_versions`。
- `capabilities` 和 `maturity`。
- `platforms`：明确支持的操作系统。
- `known_limitations`：用户可读限制；没有已知限制时允许空数组，存在适用限制时不得省略。

### 2.3 `Evidence`

字段为：`code`、`source`、`value`、`weight`、`description`。`source` 只能是文件名/目录结构、项目清单、引擎标记、用户声明或 HanGuard 提供的非侵入式环境信号。不得把读取进程内存作为检测证据。

### 2.4 `SourceLocation`

字段为：`relative_path`、`logical_path`、`line`、`column`、`byte_offset` 和 `screen_region`。不适用字段必须为 `null`，不能使用伪造的零值。

### 2.5 `SegmentDraft`

字段为：

- `segment_id`：相同源版本中稳定且唯一。
- `source_text`、`source_language`、`speaker`。
- `context_before`、`context_after`。
- `placeholders`、`tags`、`constraints`。
- `source_location`、`source_fingerprint`。
- `ocr_confidence` 和 `region_confidence`；文件适配器中为 `null`。
- `metadata`：只允许 JSON 可序列化值。

## 3. 操作契约

### 3.1 `detect`

输入 `DetectionRequest`：

- `input_root`：已解析的绝对路径。
- `declared_mode`：`PLAYER` 或 `STUDIO`。
- `project_id`。
- HanGuard 第一阶段产生的临时 `risk_level`；此时 `allowed_operations` 只能包含只读 `DETECT`。
- `context`：由 `TaskRunner` 为当前步骤创建的活动 `TaskContext`。

输出 `DetectionResult`：

- `matched`、`engine_name`、`engine_version`。
- `confidence`，范围 `[0.0, 1.0]`。
- 非空 `evidence`（未匹配时可为空）。
- `maturity`、`capabilities`、`limitations`。
- `recommended_operation`，必须包含在 HanGuard 允许列表中。

`detect` 必须只读、可重复且不创建临时文件。

### 3.2 `extract`

输入 `ExtractRequest`：`source_root`、`working_root`、候选编码列表、过滤规则、项目 ID，以及由 `TaskRunner` 创建的活动 `TaskContext`。

输出 `ExtractResult`：`segments`、源树指纹、读取文件清单、跳过文件清单、警告和统计。若只提取了部分支持范围，必须返回 `EXTRACT_PARTIAL`，不能用成功状态掩盖缺失。

`extract` 只能读取 `source_root`，临时数据只能写入 `working_root`。

### 3.3 `validate`

输入 `ValidationRequest`：源树指纹、原始文本段、候选翻译文本段、目标编码、项目规则，以及由 `TaskRunner` 创建的活动 `TaskContext`。

输出 `ValidationResult`：`valid`、问题列表、自动修复列表、阻断问题数量和警告数量。每个 `ValidationIssue` 包含稳定问题码、严重度、文本段 ID、来源位置、消息、是否可自动恢复和建议操作。

同一输入必须产生相同验证结果。`CRITICAL` 或 `ERROR` 不得被适配器静默降级。

### 3.4 `build`

输入 `BuildRequest`：只读源目录、独立暂存目录、已验证文本段、源树指纹、输出选项，以及由 `TaskRunner` 创建的活动 `TaskContext`。

输出 `BuildResult`：生成文件清单、删除/新增/修改分类、产物、候选输出指纹、警告和统计。

`build` 只能写入暂存目录。所有输出路径解析后必须仍位于暂存根目录内；拒绝绝对路径、`..` 逃逸和指向根目录外的符号链接。适配器不得直接覆盖游戏或项目目录。

### 3.5 `verify`

输入 `VerifyRequest`：源树指纹、暂存目录、构建清单、验证级别，以及由 `TaskRunner` 创建的活动 `TaskContext`。

输出 `VerifyResult`：总体结果、逐项检查、语法/编码结果、产物哈希、启动冒烟结果和问题列表。实际启动冒烟仅允许对仓库自有的合法基准项目执行。

### 3.6 `rollback`

输入 `RollbackRequest`：项目 ID、安装清单、备份清单、目标根目录、预期原始哈希，以及由 `TaskRunner` 创建的活动 `TaskContext`。

输出 `RollbackResult`：恢复文件、未改变文件、失败文件、恢复后哈希验证和问题列表。

回滚失败时不得删除备份；必须返回 `ROLLBACK_FAILED` 和可恢复证据。

## 4. 错误模型

所有失败都通过 `AdapterError` 返回，字段为：

- `code`：下表中的稳定错误码。
- `operation`、`message`、`recoverable`。
- `segment_id` 或 `relative_path`（适用时）。
- `evidence` 和 JSON 可序列化 `details`。
- `cause_type`：底层异常类型名称，不包含密钥或敏感请求正文。

允许的错误码：

| 错误码 | 含义 | 默认可恢复 |
| --- | --- | --- |
| `UNSUPPORTED_INPUT` | 输入类型不属于适配器范围 | 否 |
| `ENGINE_NOT_DETECTED` | 未检测到目标引擎 | 否 |
| `UNSUPPORTED_VERSION` | 引擎版本不在支持范围 | 否 |
| `RISK_POLICY_BLOCKED` | HanGuard 禁止该操作 | 否 |
| `READ_FAILED` | 文件读取失败 | 是 |
| `DECODE_FAILED` | 编码检测或解码失败 | 是 |
| `PARSE_FAILED` | 资源语法无法解析 | 是 |
| `EXTRACT_PARTIAL` | 支持范围内未完整提取 | 是 |
| `VALIDATION_FAILED` | 候选翻译未通过验证 | 是 |
| `STAGING_ESCAPE_BLOCKED` | 输出试图逃逸暂存目录 | 否 |
| `BUILD_FAILED` | 候选输出构建失败 | 是 |
| `VERIFY_FAILED` | 构建产物验证失败 | 是 |
| `BACKUP_FAILED` | 安装前备份失败 | 是 |
| `ROLLBACK_FAILED` | 回滚或哈希复核失败 | 是 |
| `CANCELLED` | 用户或系统取消 | 是 |
| `INTERNAL_ERROR` | 未分类内部错误 | 视证据决定 |

适配器不得返回裸异常给 GUI，也不得把 `INTERNAL_ERROR` 用作已知失败的通用替代。

## 5. 任务事件与取消

- 六类请求只接收由 `TaskRunner` 为当前步骤创建的活动 `TaskContext`，不得包含独立的 `event_sink` 或 `cancellation_token` 字段。
- 适配器只能通过请求的 `TaskContext` 方法报告进度、日志、警告和产物，并通过同一上下文执行协作式取消检查。
- `TaskRunner` 独占任务级单调递增事件序列、UTC 时间戳、`TaskEvent` 构造以及向 `EventSink` 的投递。适配器不得接收原始 `EventSink`、自行构造 `TaskEvent`，也不得选择事件序号或时间戳。
- 适配器在存在可量化进度、需记录的日志或警告、产物生成以及取消检查点时使用活动上下文；步骤开始、完成和失败事件由 `TaskRunner` 负责。
- 事件摘要不得包含 API 密钥、完整在线请求、完整游戏截图或模型内部推理。
- 取消检查必须出现在文件边界和耗时循环内。原子写入开始后可延迟取消，但必须在事件中说明。

以上调整是在实现前对已审阅 v1 设计的校正，不是已发布契约的破坏性变更；契约标识继续为 `hanengine.adapter/v1`。

## 6. 不变量

1. `detect`、`extract`、`validate` 和 `verify` 不修改源目录。
2. `build` 只写独立暂存目录。
3. 安装候选补丁由 HanCore 执行，适配器只提供清单和产物。
4. HanGuard 的禁止操作不可由适配器或用户配置覆盖。
5. 同一源指纹、文本段集合、适配器版本和选项必须产生确定的清单。
6. 失败不得被报告为低置信度成功。
7. 所有用户可见路径使用相对路径；绝对路径只保存在本地受控数据中。

## 7. 成熟度晋级

- `DETECT_ONLY`：只要求 `detect` 契约测试通过。
- `EXTRACT_READY`：增加 `extract`、稳定 ID 和完整性测试。
- `BUILD_READY`：增加 `validate`、`build`、`verify` 和暂存边界测试。
- `VERIFIED`：增加合法基准项目的端到端、启动冒烟、备份与回滚测试，并达到主规格发布指标。

适配器不能自行声明晋级；成熟度由兼容性测试报告生成。

## 8. 契约测试

每个适配器必须通过同一测试套件：

- 元数据与契约版本校验。
- 检测确定性、证据完整性和未匹配行为。
- 文本段稳定 ID、来源位置和部分提取错误。
- 占位符、标签、编码和语法验证。
- 暂存目录路径逃逸、符号链接和只读源目录保护。
- 取消、事件顺序、错误码和敏感信息清理。
- 构建清单确定性、产物哈希和回滚哈希一致性。

契约发生破坏性变化时必须发布 `hanengine.adapter/v2`；v1 新增可选字段时，旧消费者必须能忽略它们。
