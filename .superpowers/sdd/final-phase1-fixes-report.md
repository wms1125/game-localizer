# Final Phase 1 reliability fixes

## RED

在生产代码修改前，新增并运行了针对以下问题的回归：输出目录身份替换、第二次提交时的 `KeyboardInterrupt`、`resolve()`/`lstat()` 异常、扫描队列目录替换、JSON 重复键/非有限数/浮点精度损失、失败时不落盘，以及 RPG Maker `www/package.json` 证据路径。聚焦运行共 63 项，旧实现出现 12 个失败和 2 个未包装异常。最初目录替换夹具在打开临时文件时触发 Windows 拒绝重命名，随后调整为句柄关闭后替换，使测试精确命中目录身份变化。

## GREEN

- 写入事务记录输入文件、输出父目录、临时文件和备份文件的 `(st_dev, st_ino)` 身份；在创建临时文件、创建备份以及每次 `os.replace` 前复核父目录、现有路径组件、重解析点和最终目标身份。
- `process_resource` 把源文件与字典身份传给 `atomic_write_many` 作为不可写目标；`Path.resolve()`、`Path.absolute()` 和 `lstat()` 的 `OSError`/`RuntimeError` 统一转换为 `TranslationError`。
- 回滚捕获 `BaseException` 并尽力恢复、清理；仅把 `OSError`/`UnicodeError` 包装为 `TranslationError`，`KeyboardInterrupt` 等保持原类型重新抛出。
- 扫描队列保存目录身份，`scandir` 前后验证仍是同一普通目录且路径组件没有符号链接或 Windows reparse point。
- JSON 使用 `object_pairs_hook` 拒绝重复键、`parse_constant` 拒绝非有限常量、`Decimal` 验证浮点转换等价性，并以 `allow_nan=False` 输出。
- RPG Maker package 证据记录实际命中的相对路径。
- 聚焦 63 项回归已通过；最终完整 `unittest` 共 93 项通过，`compileall` 与 `git diff --check` 也通过。

## 残余限制

纯标准库、基于路径名的检查无法从根本上消除“最后一次身份检查”和紧随其后的文件系统操作之间极短的 TOCTOU 窗口。若输出目录被移走且原临时文件不再能通过原路径定位，为避免误删替换路径中的文件，清理会保守停止，可能在被移走的原目录中留下临时文件。事务仅对可捕获的错误或中断尽力回滚，不保证进程强制终止、操作系统崩溃或断电安全。

## 最终发布审查补充

### RED

新增 6 个测试方法覆盖字典重复键，以及资源 JSON 5000 位整数在库、CLI、GUI 的错误边界和不落盘行为。修改生产代码前的聚焦运行结果为 3 个失败、3 个未包装异常：字典重复键被静默合并；超长整数的 `ValueError` 从库和 GUI 泄漏，CLI 输出 traceback。

### GREEN

- 字典和资源 JSON 复用同一个严格 `object_pairs_hook`，重复键统一抛出包含键名的 `TranslationError`。
- 只在两个 `json.loads` 调用边界捕获解析产生的 `ValueError`；后续顶层对象及字符串键值验证保持原行为。
- 7 项聚焦回归（含原资源重复键用例）通过；完整 `unittest` 共 99 项通过，`compileall` 与 `git diff --check` 也通过。
