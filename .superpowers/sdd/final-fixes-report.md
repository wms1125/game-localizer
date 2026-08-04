# Final fixes report

- 基线：`1132253`（审查范围 `b8c4901..1132253`）
- 提交：`fix: harden translation edge cases`（本报告随该提交一并入库）
- 方法：系统化调试定位根因；每个缺陷先写回归测试并观察 RED，再做最小实现至 GREEN。

## RED / GREEN 记录

1. CSV 安全处理
   - RED：单列文本被空格误判为分隔符，完整单元格无法命中；未闭合引号未作为解析错误；`csv.Error` 从 writer 直接泄漏；单引号方言写出的含 `|` 与 `"` 译文无法按安全双引号规则读回。
   - GREEN：Sniffer 仅允许 `,`、`;`、Tab、`|`；解析使用 strict reader，解析/写出 `csv.Error` 统一包装为 `TranslationError`；writer 固定安全双引号、双写引号和最小引用规则。

2. 输入文件保护
   - RED：汉化输出或未翻译输出通过解析后的别名指向翻译字典时未被拒绝；其中一个分支实际覆盖了字典。
   - GREEN：两个输出角色均与资源及翻译字典的 `resolve()` 结果比较；资源/字典、两个输出角色的别名组合均有测试。

3. 纯文本未翻译键
   - RED：`strip()` 删除了 LF/CRLF 行的开头缩进和尾空格。
   - GREEN：仅移除行结束的 LF/CR，完整原始行的水平空白保留；完整空白行保持原样且不进入清单。

4. 半角片假名候选
   - RED：`ｶﾀｶﾅ` 未进入未翻译清单。
   - GREEN：候选字符范围加入 U+FF66–U+FF9F。

5. UTF-8 与事务错误
   - RED：含孤立代理项的字典键/值通过验证；`atomic_write_many` 泄漏 `UnicodeEncodeError` 并遗留 tmp；CLI 输出 traceback 而非用户错误。
   - GREEN：字典键值显式验证 UTF-8 可编码；事务统一捕获 `UnicodeError`/`OSError` 并走同一回滚清理；直接事务与 CLI 均有回归测试，tmp/bak 均为空。

6. 实际覆盖提示
   - RED：事务返回 `None`，`ProcessingResult` 无覆盖字段，CLI/GUI 无逐项目标提示。
   - GREEN：事务成功返回实际备份并覆盖的目标；`ProcessingResult.overwritten_paths` 以尾部默认字段保持已有构造兼容；CLI 逐项输出 `[覆盖]`，GUI 复用同一 formatter；混合已有/新建目标有测试。

7. 真实边界与委托
   - RED：负数 `preview_limit` 产生负切片和错误省略数；GUI 成功日志缺覆盖提示。
   - GREEN：负数归一为 0；GUI 成功/失败均验证核心调用、日志与弹窗。单列 CSV、引号/分隔符、半角日文、完整空白行、字典碰撞、Unicode 清理和混合目标均纳入真实边界测试。

## 测试证据

- 基线：`python -m unittest discover -s tests -v` → 20/20 GREEN。
- RED（核心）：25 项运行 → 10 failures、3 errors，均为上述缺失行为。
- RED（CLI/GUI）：12 项运行 → 4 failures，覆盖 Unicode 用户错误、覆盖日志、负数预览和 GUI 同步日志。
- Focused GREEN：37/37 GREEN。
- 全量 GREEN：`python -m unittest discover -s tests -v` → 37/37 GREEN，0 failures，0 errors。
- 示例：4 个不同字典键命中、4 次替换、1 个未翻译项；已有两个示例输出均逐项显示覆盖提示。
- `python -m json.tool examples/game.zh.json` → exit 0。
- `python -m json.tool examples/game.untranslated.json` → exit 0。
- `python cli.py --help` → exit 0，参数与授权提示完整。
- Tk smoke → exit 0，窗口几何 `900x620+208+208`。
- `git diff --check` → exit 0。

## 关注项

- CSV 写出会规范化引用与行结束符，这是设计允许的行为；分隔符仍保留为识别到的常用分隔符。
- 覆盖记录只包含本次事务开始时实际存在并成功备份的目标；新建目标不会误报为覆盖。
- 输出保护基于 `Path.resolve()`，覆盖路径别名/符号链接解析语义，不改变原有默认输出规则。
