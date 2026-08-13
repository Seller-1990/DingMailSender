# Changelog

本项目遵循语义化版本。所有面向用户或维护者的重要变化记录在此文件。

## [Unreleased]

## [0.4.0] - 2026-08-13

### Added

- 单实例互斥锁：防止多实例并行运行导致数据覆盖和重复发送。
- SMTP/IMAP 断线自动重连：session error 后尝试重建连接继续剩余任务，而非直接跳过全部。
- 发送状态持久化：`tasks.xlsx` 新增「最近结果」列，崩溃后重启可恢复已发送状态，防止重复发送。
- 可中断的 rate_limit_sleep：取消信号每 0.1 秒检查一次，取消延迟从秒级降至百毫秒级。
- 增量校验：首次加载大量任务时分批校验（每 100ms 处理 5 个），避免 UI 冻结。
- DPAPI 应用级熵值：加密凭据时传入固定 entropy，提高同用户恶意进程窃取密码的门槛。

### Fixed

- Excel 保存时文件被占用不再丢失数据：PermissionError 时保留 tmp 文件供用户恢复。
- 退出程序时安全等待 worker 结束（cancel + wait），避免 QThread 析构导致进程 abort。
- IMAP 连接显式传入 `ssl_context`，与 SMTP 保持一致，消除隐式安全依赖。
- `imaplib._MAXLINE` 在 `__enter__` 失败时正确恢复，不再泄漏全局修改。
- DPAPI 解密兼容旧版无熵加密格式（fallback 机制）。

### Changed

- CI 流水线精简：移除冗余的 `compileall` 步骤，合并 artifact 验证到构建步骤。

## [0.3.0] - 2026-08-06

### Added

- IMAP 主机/端口可通过连接配置自定义，不再硬编码为阿里企业邮。
- 发送/草稿进度实时显示在状态栏（"正在处理 3/10..."）。
- 发送/草稿完成弹框显示失败任务详情（主题 + 原因）。
- 取消发送机制：worker 支持 `request_cancel()`，投递循环每轮检查取消标志。
- `py.typed` marker 和 `pyproject.toml` pyright 配置启用静态类型检查。

### Changed

- `MarkdownIt` 渲染器提升为模块级单例，避免高频渲染时重复实例化。
- CID 内联图片按路径去重——同一图片多次引用只嵌入一份，减少邮件体积。
- SMTP 部分收件人被拒绝时标记为"已发送（部分拒绝）"而非全量失败。
- SMTP login 条件简化为仅检查 username（有用户名即认证）。
- `imaplib._MAXLINE` 修改改为 enter/exit 配对恢复，避免全局状态污染。
- 审计报告和优化计划文档移入 `docs/` 目录。

### Fixed

- `tasks.xlsx` 日期格式解析异常不再击穿整个任务包加载。
- 连接配置保存后设置文件权限为 owner-only（Windows）。

## [0.2.0] - 2026-07-14

### Changed

- GUI 大型模块按任务包操作、任务编辑、表格状态、对话框职责拆分，并保留原有兼容导入入口。
- 投递结果状态改为统一枚举，未知历史状态会明确显示。

### Fixed

- 空邮件正文提前校验。
- SMTP/IMAP 初始化失败时可靠释放连接。
- 限制附件、内联图片和单封邮件总文件载荷。
- `tasks.xlsx` 保存失败时保持当前任务与运行态不变。

### Release

- 建立单一版本来源、Tag/版本一致性检查、版本化 Windows 资产、SHA256 审计、启动 smoke 和 GitHub Release 工作流。
