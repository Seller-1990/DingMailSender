# Fuck My Shit Mountain Audit Report

**Project:** DingMailSender  
**Audit mode:** full  
**Date:** 2026-06-11  
**Reviewer:** Codex / GPT-5

---

## 1. Executive Summary

本轮审计结论：项目已经从上一轮“可用但风险较多”的状态，进入“可以继续小步发布，但还不算完全成熟”的状态。核心风险不再是数据损坏、真实收件人入库、EXE 产物入 Git、worker 生命周期崩溃这类硬伤；这些在当前代码中已经有明确修复证据。当前主要债务集中在 GUI 状态耦合、协议层测试真实性、局部静默兜底、附件/图片资源上限和发布治理细节。

当前大致评分为 **7.8 / 10，A 档**。如果只看正式跟踪文件和 CI 发布链路，质量已经比较扎实；如果把本地忽略目录 `.claude/worktrees/` 中的残留任务包也纳入日常工作区风险，安全/仓库卫生仍有清理必要。这个评分比 2026-06-10 的 7.1 有明显提升，尤其是 Release、Stability 和 Testing。

### Score Dashboard

```
Security        ████████░░  8.2  A   DPAPI、路径越界校验、HTML禁用和日志脱敏到位；剩余风险主要是旧明文删除失败被静默吞掉和本地忽略工作区残留数据。
Stability       ████████░░  8.0  A   原子写、会话级熔断、启动错误提示和 EXE smoke 已补齐；退出清理和部分兜底仍缺可观测性。
Performance     ████████░░  7.8  A   桌面批处理规模下足够；主要缺口是附件/内联图片没有大小上限，PySide6 打包体积需持续监控。
Testing         ████████░░  8.0  A   60 个测试通过且覆盖真实回归；SMTP/IMAP 协议细节仍主要靠 mock，真实邮箱 smoke 默认跳过。
Maintainability ███████░░░  7.1  A   单体主窗体已拆分；但 mixin + 动态 state proxy 仍让 GUI 共享状态边界不够清晰。
Design          ███████░░░  7.2  A   路径边界、fail-fast、原子写等设计较好；字符串状态、动态属性和局部 silent fallback 仍削弱约束。
Release         █████████░  8.5  A   Windows CI、constraints、SHA256、release audit、EXE smoke 和历史清理都已就位；缺正式版本/发布说明/回滚策略。
─────────────────────────────────────
Overall         ████████░░  7.8  A
```

Each dimension scored 0.0-10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based. See `rubrics/scoring.md` for anchor descriptions.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 5 | 5 | 0 |
| Low | 4 | 4 | 0 |
| Info | 1 | 1 | 0 |
| **Total** | **10** | **10** | **0** |

## 2. Project Map

`dingmail_gui.py` 是运行入口，负责在源码模式下把 `src/` 放进 `sys.path`，然后进入 `dingmail.gui.main.run()`。`MainWindow` 由 `MainUiMixin`、`MainViewMixin`、`MainTaskMixin`、`MainDeliveryMixin` 组合而成，状态集中在 `MainWindowState` 和 `TaskRuntimeController`。

领域层位于 `src/dingmail/`：`task_package.py` 负责 `tasks.xlsx` 读写、路径归一化和任务 ID 修复；`task_service.py` 负责任务校验、Markdown 组合和预览/邮件 HTML 渲染；`task_delivery.py` 负责发送/草稿批次、运行目录、manifest、日志和会话级错误处理；`smtp_sender.py` 和 `imap_drafts.py` 是 SMTP/IMAP 协议边界；`connection_profile.py` 负责 DPAPI 凭据保存与旧配置迁移；`paths.py` 负责工作目录探测。

持久化层是本地文件系统：任务包在 `packages/`，运行输出在 `runs/`，连接配置在 `%LOCALAPPDATA%\DingMailSender\conn_profile.json`。`tasks.xlsx` 保存采用临时文件加 `os.replace`，运行输出默认只写 `manifest.csv` 和日志，`DINGMAIL_SAVE_DEBUG_ARTIFACTS=1` 才写 `.eml` 和 HTML 预览。

外部接口包括 SMTP SSL/STARTTLS、IMAP SSL、Windows DPAPI、PySide6 GUI、Excel 文件和本地文件打开。安全边界主要在路径越界校验、Markdown HTML 禁用、邮件 header 控制字符拒绝、DPAPI 加密、manifest 脱敏和 debug artifact 默认关闭。

测试结构使用 `unittest`，CI 在 `windows-latest` 上执行依赖安装、仓库卫生、单元测试、compileall、PyInstaller 打包、SHA256 审计、EXE offscreen smoke 和 artifact 上传。真实邮箱 smoke 测试存在，但默认由环境变量门控跳过。

## 3. Top Risks

1. **旧明文配置删除失败被静默吞掉** - Medium：迁移成功后如果旧文件无法删除，GUI 仍显示已迁移，可能残留授权码。
2. **附件和内联图片无大小上限** - Medium：大文件会被一次性读入内存，可能导致 GUI 批次卡死或 OOM。
3. **GUI mixin 共享动态状态边界仍不清晰** - Medium：多个 mixin 通过动态 property 操作同一个 `_state`，后续改动容易产生隐式耦合。
4. **SMTP/IMAP 协议测试真实性不足** - Medium：默认 CI 覆盖业务分支，但真实邮箱兼容性主要依赖 opt-in smoke。
5. **GUI/测试文件仍偏大** - Medium：已拆分主窗体，但多个 GUI 类和 `test_gui_main.py` 仍是维护热点。
6. **SMTP/IMAP teardown 错误无日志** - Low：退出清理失败不影响主流程，但会降低故障排查能力。
7. **投递状态仍是字符串协议** - Low：跨层状态枚举没有收敛，未来新增状态容易漏计数或漏 UI 映射。
8. **缺正式发布治理** - Low：CI 能产 artifact，但没有 tag、changelog、rollback 或签名策略。
9. **本地忽略工作区有大量历史任务包副本** - Low：不进入 Git，但会增加本机泄露和误扫描风险。
10. **依赖体积合理但需监控** - Info：PySide6/PyInstaller 对桌面 GUI 是合理依赖，当前 EXE 约 48 MB。

## 4. Detailed Findings

### Finding: 旧明文配置迁移后删除失败被静默吞掉

- Severity: Medium
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Connection profile migration
- Evidence:
  - File: `src/dingmail/connection_profile.py:157`
  - Function / Module: `migrate_connection_profile_if_needed`
  - Relevant behavior: 迁移成功后尝试 `source_path.unlink(missing_ok=True)`，但 `except OSError` 只注释说明并 `pass`。
  - Trigger condition: 旧明文 `conn_profile.json` 被占用、权限不足、同步盘锁定或杀毒软件暂时拦截删除。
- Problem: 迁移写入新 DPAPI 配置成功后，旧明文配置删除失败不会被返回给 GUI，也不会写日志或保留告警状态；这违反 Fail-Fast / Don't Swallow Errors 原则。
- Why it matters: 用户界面可能显示“已自动迁移”，但旧明文授权码仍留在程序目录或工作目录，之后打包/分享目录时仍可能泄露。
- Realistic failure scenario: 用户从旧版升级，旧配置在 OneDrive 同步目录中；同步客户端短暂锁文件导致删除失败；程序继续显示迁移成功；用户把旧目录发给同事排查问题，明文授权码一并泄露。
- Minimal fix: `migrate_connection_profile_if_needed` 返回迁移结果对象，包含 `saved_path` 和 `cleanup_warning`；GUI 在删除失败时显示“已迁移但旧文件未删除”并保留来源路径。
- Better long-term fix: 给配置迁移建立显式状态模型：`NoMigrationNeeded`、`MigratedAndCleaned`、`MigratedCleanupFailed`、`MigrationFailed`。
- Regression test suggestion: mock `Path.unlink` 抛 `OSError`，断言 GUI warning 不为空且提示旧明文文件仍需手动删除。
- Estimated effort: 1-2 hours

### Finding: 附件和内联图片一次性读入内存且没有大小上限

- Severity: Medium
- Confidence: High
- Category: Performance
- Status: Confirmed
- Affected area: Email rendering and attachment loading
- Evidence:
  - File: `src/dingmail/email_builder.py:70`
  - Function / Module: `attachment_from_path`
  - Relevant behavior: 附件通过 `path.read_bytes()` 一次性读入。
  - File: `src/dingmail/rendering.py:94`
  - Function / Module: `embed_cid_images`
  - Relevant behavior: 内联图片通过 `resolved.read_bytes()` 一次性读入。
- Problem: 用户可在任务包内引用任意大小的附件或图片，代码只校验存在性和 MIME 类型，没有 per-file 或 per-task 大小上限；这违反 Unbounded Resources Must Not Grow Forever 原则。
- Why it matters: 桌面批量邮件工具的失败模式通常是用户拖入大 PDF、压缩包或高清图片；一次性读入会造成 GUI 卡顿、内存暴涨或 SMTP 阶段才失败。
- Realistic failure scenario: 20 个任务各带 200 MB 附件并含多张大图，发送前渲染就占用数 GB 内存，用户只看到程序无响应。
- Minimal fix: 在 `validate_task` 增加附件和内联图片大小检查，例如默认单附件 25 MB、单图片 5 MB、单任务总附件 50 MB，可通过常量或配置覆盖。
- Better long-term fix: 在 GUI 任务详情中展示附件总大小，并在发送前做批次级资源预算。
- Regression test suggestion: 构造超过阈值的临时附件和图片，断言 `validate_task` 返回明确错误且 `render_task_email` 不进入读全量内容路径。
- Estimated effort: 2-4 hours

### Finding: MainWindow 通过 mixin 和动态 property 共享同一批可变状态

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: GUI state ownership
- Evidence:
  - File: `src/dingmail/gui/main.py:25`
  - Function / Module: `MainWindow`
  - Relevant behavior: `MainWindow` 继承 `MainUiMixin`、`MainViewMixin`、`MainTaskMixin`、`MainDeliveryMixin` 和 `QMainWindow`。
  - File: `src/dingmail/gui/main.py:186`
  - Function / Module: `_state_property` loop
  - Relevant behavior: `_smtp_cfg`、`_tasks`、`_runtime`、`_send_worker` 等属性通过运行时 `setattr` 映射到 `self._state`。
- Problem: 拆分主窗体后，代码量下降明显，但多个 mixin 仍隐式读写同一批动态属性；这违反 Explicit Dependencies Over Implicit/Global 和 SRP 原则。
- Why it matters: 后续改 UI、投递或任务状态时，很难只看一个模块确认状态来源、生命周期和并发边界。
- Realistic failure scenario: 新增“多任务包标签页”时，某个 mixin 仍通过 `_package_dir` 读写全局当前包，另一个 mixin 认为状态已隔离，导致异步结果写到错误包。
- Minimal fix: 把 `_state_property` 的动态 loop 替换为显式 property 或直接通过 `self._state.xxx` 访问，至少让 IDE/类型检查能发现字段。
- Better long-term fix: 把 GUI 分成 `PackageController`、`DeliveryController`、`ViewModel` 三个显式对象，mixin 只处理 Qt widget 组装。
- Regression test suggestion: 增加一个“切换任务包 + 异步 worker 回调 + 状态不污染”的测试矩阵，覆盖发送、草稿、队列三种状态。
- Estimated effort: 0.5-1 day

### Finding: GUI 和 GUI 测试文件仍偏大，SRP 压力仍在

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: GUI modules and tests
- Evidence:
  - File: `src/dingmail/gui/dialogs.py:34`
  - Function / Module: `TaskEditorDialog`, `PreviewDialog`, `MarkdownPreviewDialog`, `RunHistoryDialog`
  - Relevant behavior: 单文件 485 行，包含 4 个对话框类。
  - File: `src/dingmail/gui/main_tasks.py:27`
  - Function / Module: `MainTaskMixin`
  - Relevant behavior: 单类 391 行，处理包导入、任务编辑、表格刷新、按钮状态和状态栏。
  - File: `tests/test_gui_main.py:76`
  - Function / Module: `MainWindowGuiTests`
  - Relevant behavior: 一个测试类约 451 行，覆盖布局、队列、托盘、worker、迁移等多个主题。
- Problem: 单体主窗体已被拆开，但拆分仍偏“按文件分区”，而不是按稳定职责边界；这违反 File Size Limit、Function/Class Size 和 High Cohesion 原则。
- Why it matters: 现在新增一个 GUI 行为容易同时改 UI、任务状态和测试大类，review 成本较高，也容易让测试夹杂过多不相关 setup。
- Realistic failure scenario: 修改运行历史弹窗时误触 `dialogs.py` 的任务编辑依赖；测试失败定位到 `test_gui_main.py` 中一个 50 行以上的场景，很难判断破坏的是布局、状态还是 worker 回调。
- Minimal fix: 先把 `RunHistoryDialog`、`TaskEditorDialog` 拆成独立文件；把 `test_gui_main.py` 按 `test_gui_package.py`、`test_gui_delivery.py`、`test_gui_tray.py` 分组。
- Better long-term fix: 形成 GUI controller/view-model 测试边界，减少直接断言 Qt widget 内部状态的比例。
- Regression test suggestion: 文件拆分后保留现有 60 个测试，再增加 import smoke，确认新模块没有循环导入。
- Estimated effort: 0.5-1 day

### Finding: SMTP/IMAP 协议层默认测试仍以 mock 为主

- Severity: Medium
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: Mailbox integration confidence
- Evidence:
  - File: `tests/test_task_delivery.py:103`
  - Function / Module: `TaskDeliveryTests`
  - Relevant behavior: 发送流程测试 patch `dingmail.task_delivery.SmtpSession` 和 `render_task_email`。
  - File: `tests/test_task_delivery.py:179`
  - Function / Module: `TaskDeliveryTests`
  - Relevant behavior: 草稿流程测试 patch `ImapDraftsSession`。
  - File: `tests/test_mailbox_smoke.py:43`
  - Function / Module: `MailboxSmokeTests`
  - Relevant behavior: 真实 IMAP/SMTP 测试由 `DINGMAIL_SMOKE_IMAP` / `DINGMAIL_SMOKE_SMTP` 门控，默认跳过。
- Problem: 默认 CI 能证明业务编排、断连熔断、manifest 和 GUI 行为，但不能证明当前 IMAP mailbox quoting、UTF-7、SMTP TLS/login 与真实邮箱服务长期兼容；这属于 Testing Authenticity 风险。
- Why it matters: 邮箱服务差异常出现在真实协议响应上，mock 会把这类问题推迟到用户现场。
- Realistic failure scenario: 企业邮箱升级 IMAP 响应格式或草稿箱命名，mock 测试仍绿，真实保存草稿失败。
- Minimal fix: 在发布前提供一个手动但标准化的 smoke profile，要求 release candidate 至少跑一次真实 SMTP 和 IMAP smoke，并记录结果到 release notes。
- Better long-term fix: 用容器化测试邮箱或可控测试账号在夜间 CI 中跑协议 smoke，避免 PR 里直接发真实邮件。
- Regression test suggestion: 为 `_parse_mailbox_entries` 增加更多真实 IMAP LIST 样本；为 SMTP 增加 starttls/ssl 配置矩阵测试。
- Estimated effort: 0.5 day for manual gate, 1-2 days for automated test mailbox

### Finding: SMTP/IMAP teardown 错误被吞掉且无日志

- Severity: Low
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: SMTP and IMAP session cleanup
- Evidence:
  - File: `src/dingmail/smtp_sender.py:43`
  - Function / Module: `SmtpSession.__exit__`
  - Relevant behavior: `quit()` 失败后尝试 `close()`，`close()` 再失败则 `pass`。
  - File: `src/dingmail/imap_drafts.py:98`
  - Function / Module: `ImapDraftsSession.__exit__`
  - Relevant behavior: `logout()` 任意异常直接 `pass`。
- Problem: 清理失败通常不应覆盖主发送结果，但完全无日志会隐藏网络、服务器或 socket 清理异常；这违反 Don't Swallow Errors 原则。
- Why it matters: 如果用户报告“批次成功但邮箱端会话异常”或“关闭后服务端仍显示连接”，当前日志没有证据链。
- Realistic failure scenario: SMTP 服务器在 DATA 后断开，邮件已发送成功，但 `quit()` 抛异常；用户后来遇到限流，日志无法判断连接关闭是否异常。
- Minimal fix: 让 session 接收可选 logger，或在上层 `task_delivery.py` 的 logger 中记录 teardown warning。
- Better long-term fix: 把 session cleanup result 纳入运行日志，但不改变发送成功/失败状态。
- Regression test suggestion: fake SMTP/IMAP 在 `quit/logout` 抛异常，断言批次结果仍成功且日志包含 cleanup warning。
- Estimated effort: 1-2 hours

### Finding: 投递结果状态仍是字符串协议

- Severity: Low
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Delivery result contract
- Evidence:
  - File: `src/dingmail/task_delivery.py:41`
  - Function / Module: `TaskDeliveryOutcome`
  - Relevant behavior: `status: str`，实际值包括 `sent`、`send_error`、`send_skipped`、`draft_saved`、`draft_error`、`draft_skipped`。
  - File: `src/dingmail/gui/main_delivery.py:171`
  - Function / Module: `_send_result_counts`, `_draft_result_counts`, `_result_skipped_count`
  - Relevant behavior: UI 通过字符串字面量统计结果。
- Problem: 状态枚举已在 GUI runtime 中存在，但投递结果仍是字符串协议，跨层没有类型约束；这违反 Stringly Typed 和 Principle of Least Surprise。
- Why it matters: 新增状态时，业务层能运行但 UI 统计可能漏算，运行历史也可能归类错误。
- Realistic failure scenario: 将来新增 `send_cancelled`，`_send_result_counts` 把它算作失败但 `_result_skipped_count` 不显示原因，用户看到数量但不知道是取消还是发送失败。
- Minimal fix: 增加 `DeliveryStatus(StrEnum)`，`TaskDeliveryOutcome.status` 使用该枚举，GUI 统计使用 enum set。
- Better long-term fix: 把 `TaskStatus` 与 delivery outcome status 做显式映射函数，集中在一个模块里。
- Regression test suggestion: 添加一个未知/新增 delivery status 的统计测试，确保 UI 显示不会静默归错类。
- Estimated effort: 2-3 hours

### Finding: 发布流程缺正式版本、发布说明和回滚策略

- Severity: Low
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Release governance
- Evidence:
  - File: `pyproject.toml:3`
  - Function / Module: project metadata
  - Relevant behavior: 版本固定为 `0.1.0`。
  - File: `.github/workflows/ci.yml:57`
  - Function / Module: CI artifact upload
  - Relevant behavior: CI 上传 `DingMailSender-windows` artifact，但没有 tag/release/changelog/rollback 步骤。
  - Repository state: `git tag --list` 为空。
- Problem: 构建链路已经能稳定产物，但发布治理仍停留在 artifact 层；这违反 Release Readiness 中的 versioning/rollback 要求。
- Why it matters: 用户拿到 EXE 后，无法从二进制对应到修复说明、风险提示或可回滚版本。
- Realistic failure scenario: 某次发布引入邮箱兼容性问题，用户手上只有 `DingMailSender.exe`，没有版本号和上一版 artifact 链接，回滚依赖手工找文件。
- Minimal fix: 每次稳定发布打 `vX.Y.Z` tag，生成 GitHub Release notes，artifact 名带版本号。
- Better long-term fix: 增加 `--version` 或 about dialog，EXE 内嵌版本和 commit hash，发布说明列出 smoke 结果。
- Regression test suggestion: CI 校验 artifact 名包含 tag/version，about dialog 或版本模块与 `pyproject.toml` 一致。
- Estimated effort: 2-4 hours

### Finding: 本地忽略工作区仍残留多份任务包和数据副本

- Severity: Low
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Local workspace hygiene
- Evidence:
  - File: `.gitignore:23`
  - Function / Module: ignore rules
  - Relevant behavior: `.claude/` 被 ignore，不会进入 Git。
  - Local state: `.claude/worktrees/agent-*` 共有 3 个目录，每个约 104 个文件，包含 `packages/预算执行通知/...` 和 `tasks.xlsx`。
- Problem: 这些文件不会污染正式仓库，但仍在同一工作区和 OneDrive 路径下，可能被备份、误打包、误搜索或被其他工具读取。
- Why it matters: 该项目处理邮件、收件人和业务正文，本地残留数据的风险不等于 Git 风险，但仍是实际安全面。
- Realistic failure scenario: 用户把整个项目目录压缩给同事或交给外部 AI 工具分析，`.claude/worktrees` 中的历史任务包一起被带走。
- Minimal fix: 手动清理不再需要的 `.claude/worktrees/agent-*`，或把 agent 工作区移到不含业务数据的临时目录。
- Better long-term fix: 增加本地维护脚本，列出 ignored 目录中可能含敏感任务包的文件，但默认只报告不删除。
- Regression test suggestion: hygiene 脚本增加 dry-run 模式，扫描 ignored `packages/`、`runs/`、`.claude/worktrees/` 并输出风险清单。
- Estimated effort: 30-60 minutes

### Finding: PySide6/PyInstaller 体积合理但应持续监控

- Severity: Info
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Dependency weight and binary size
- Evidence:
  - File: `pyproject.toml:7`
  - Function / Module: dependencies
  - Relevant behavior: 直接依赖 `PySide6==6.10.1`、`openpyxl==3.1.5`、`markdown-it-py==4.0.0`、`beautifulsoup4==4.13.4`。
  - File: `release/DingMailSender.exe`
  - Function / Module: built artifact
  - Relevant behavior: 当前 EXE 大小为 48,326,877 bytes，SHA256 审计通过。
- Problem: 这不是阻塞问题；对于 Windows GUI，PySide6 是合理依赖。但桌面一体化 EXE 的体积、启动时间和第三方升级风险需要持续可见。
- Why it matters: 如果后续只新增小功能却显著增大 EXE，说明依赖或打包配置可能引入了不必要模块。
- Realistic failure scenario: 为一个小工具函数引入新重依赖，EXE 体积和启动时间明显上升，但 CI 没有记录变化趋势。
- Minimal fix: 在 release audit 输出中保留 EXE size，并在 release notes 中记录。
- Better long-term fix: CI 对 EXE size 设置软阈值，例如超过上一版 20% 时提示人工确认。
- Regression test suggestion: `scripts/audit_release.ps1` 输出 size 已有，可加阈值参数但默认只 warning。
- Estimated effort: 1 hour

## 5. Security Concerns

已验证的安全正面证据：

- `connection_profile.py` 在 Windows 下使用 DPAPI 保存授权码，非 Windows 不静默降级保存明文。
- `task_package.py` 的 `resolve_user_path` 和 `package_relpath` 阻止任务包路径越界。
- `rendering.py` 使用 `MarkdownIt("default", {"html": False})`，测试覆盖 `<script>` 转义。
- `email_builder.py` 拒绝 header 控制字符，测试覆盖收件人注入。
- `run_store.py` 默认脱敏 manifest 中的邮箱、主题和错误，debug artifact 默认关闭。

剩余安全问题集中在两个地方：旧明文配置删除失败不可见，以及本地 ignored 工作区残留历史任务包。没有发现硬编码真实凭据、SQL/命令注入、网络服务未授权端点或生产 API 暴露。

## 6. Stability Concerns

已验证的稳定性提升：

- `tasks.xlsx` 保存采用临时文件加 `os.replace`，测试覆盖保存失败不损坏原文件。
- SMTP/IMAP 批次遇到会话级错误会跳过剩余任务，避免逐条失败和逐条 sleep。
- GUI 阻止 worker 运行时退出或编辑任务，避免 QThread abort 和状态污染。
- `scripts/smoke_exe.ps1` 已在本地通过，EXE 启动 15 秒后仍存活且初始化工作目录。

剩余稳定性问题主要是 cleanup 阶段无日志、定时队列仍是内存态且退出后不会恢复。后者已在操作说明中明确，不算隐藏 bug。

## 7. Performance Concerns

项目当前规模下性能足够：任务读取、渲染和发送都是本地桌面批处理，不是服务端高并发路径。主要现实瓶颈是资源大小而不是算法复杂度：附件和内联图片没有大小上限，Excel rows 会一次性读入内存。对企业邮件批量工具而言，应优先给用户输入设上限，而不是做复杂优化。

## 8. Testing Gaps

验证结果：

```text
python -m unittest discover -s tests
Ran 60 tests in 0.935s
OK (skipped=2)

python -m compileall -q src dingmail_gui.py tests
OK

.\scripts\check_repo_hygiene.ps1
Repository hygiene check passed.

.\scripts\audit_release.ps1
Release audit OK

.\scripts\smoke_exe.ps1
Launch smoke OK: process alive after 15s and workspace initialized.
```

测试质量总体比上一轮明显好，覆盖了路径越界、额外列保留、ID 修复、HTML 转义、header 注入、断连熔断、busy guard、托盘退出和异步包切换。主要缺口是：真实 SMTP/IMAP smoke 默认跳过、没有 coverage/lint/type-check gate、GUI 测试集中在一个大类中。

## 9. Maintainability Concerns

维护性已从“一个巨大主窗体”改善为“领域模块 + GUI mixin + runtime controller”。不过 GUI 仍是最高风险区：mixin 之间共享动态 `_state` 属性，`main_tasks.py`、`main_ui.py`、`main_view.py` 和 `dialogs.py` 的职责边界还偏 UI 结构而非业务边界。短期不用重写，下一步应先消除动态 property 和拆分对话框/测试。

## 10. Design / Principles Concerns

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Don't Swallow Errors | 2 | Medium/Low | connection migration cleanup, SMTP/IMAP teardown |
| Explicit Dependencies Over Implicit/Global | 1 | Medium | MainWindow dynamic state proxy |
| File/Class Size Discipline | 3 | Medium | dialogs.py, main_tasks.py, test_gui_main.py |
| Unbounded Resources | 1 | Medium | attachment and inline image reads |
| Stringly Typed | 1 | Low | delivery outcome status |
| Release Versioning | 1 | Low | artifact release process |

### Principles Respected

- Fail-fast on invalid paths and malformed connection config.
- Atomic write for user-owned `tasks.xlsx`.
- Debug artifact opt-in instead of always writing full `.eml`.
- SMTP/IMAP external calls use timeouts.
- GUI blocks risky operations while worker is active.
- CI validates build artifact checksum and EXE launch.

---

## 11. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 1 | 0 | 1 | 0 |
| EmptyCatch | 2 | 2 | 0 | 0 |
| CompatibilityBranch | 2 | 2 | 0 | 0 |
| SilentCorrection | 1 | 1 | 0 | 0 |
| DefensiveGuess | 1 | 1 | 0 | 0 |

Details:

- `connection_profile.py:157-162`：旧明文删除失败应 KeepWithAlert，而不是完全 `pass`。
- `smtp_sender.py:43-51`、`imap_drafts.py:98-104`：cleanup 错误可以不覆盖主结果，但应写 warning。
- `paths.py:46-62`：工作目录探测包含兼容分支，目前有注释和测试，保留合理。
- `task_package.py:138-158`：缺失/重复任务 ID 自动修复是正确用户体验，GUI 已弹 warning；保留。
- `imap_drafts.py:154-169`：草稿箱 fallback candidate 合理，但真实邮箱覆盖仍不足。

## 12. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|-----------------|------|--------|
| task_package round-trip | High | Excel 结构回归 | Keep |
| connection_profile DPAPI/migration | High on Windows, Medium cross-platform | cleanup failure path未覆盖 | Keep but augment |
| task_delivery with fake SMTP/IMAP | Medium | 真实协议差异逃逸 | Keep but augment |
| GUI main behavior | Medium/High | 测试大类维护成本高 | Split later |
| real mailbox smoke | High when enabled, None in default CI | 发布前未强制跑真实邮箱 | Add release gate |

### Valuable Tests

- `tests/test_task_package.py:233` 覆盖保存失败时旧文件保持完整。
- `tests/test_gui_main.py:410` 覆盖异步结果不污染切换后的任务包。
- `tests/test_task_delivery.py:198` 覆盖 SMTP 断连后剩余任务跳过。
- `tests/test_task_service_and_imap.py:94` 覆盖 header 注入拒绝。
- `tests/test_connection_profile.py:126` 覆盖旧明文迁移成功后删除旧文件。

### Suspicious Tests

没有发现“为了绿色而造假”的测试。主要问题不是假测试，而是协议层 mock 覆盖不了真实邮箱兼容性。

### Missing Tests

- 旧明文迁移成功但旧文件删除失败时 GUI warning。
- 超大附件/图片校验。
- SMTP/IMAP cleanup warning。
- delivery status enum 化后的未知状态防护。
- release version 与 artifact 名称一致性。

---

## 13. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 1 | 0 | 0 | 0 | 1 |
| InputBoundary | 1 | 0 | 0 | 1 | 0 |
| OutputLeak | 0 | 0 | 0 | 0 | 0 |
| BooleanTrap | 0 | 0 | 0 | 0 | 0 |
| StringlyTyped | 1 | 0 | 0 | 0 | 1 |
| ErrorType | 1 | 0 | 0 | 0 | 1 |

Notes:

- `ctypes` DPAPI 边界有 `type: ignore[attr-defined]`，但该代码只在 Windows 执行且测试覆盖非 Windows fail-fast；风险低。
- `SendTasksConfig.smtp_security: str` 在 `_smtp_config_from_delivery` 中显式校验后 cast，当前可接受。
- `TaskDeliveryOutcome.status: str` 是主要类型约束缺口。
- 多处 `except Exception as exc` 会把错误转为用户可见文本，适合桌面工具，但应避免吞掉 cleanup/migration 这类运维信号。

## 14. Frontend State Analysis

该项目是 PySide6 桌面 GUI，不是 Web 前端。状态主要在 `MainWindowState`、`TaskRuntimeController` 和各 Qt widget 中。正面证据是运行态已从 `MailTask` 中分离，异步 worker 回调也校验当前任务包和对象身份。剩余风险是 mixin 隐式共享 `_state`，以及部分 UI 统计直接读 runtime set/list，缺少 view-model 层。

### Summary

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 3 | `dialogs.py`, `main_tasks.py`, `test_gui_main.py` |
| StateDuplication | 0 | None confirmed |
| PropDrilling | 0 | Not applicable |
| EffectChain | 1 | worker callbacks -> runtime -> table refresh -> metrics |
| UIBusinessCoupling | 1 | MainTaskMixin / MainDeliveryMixin |
| DOMasState | 0 | Not applicable |
| RequestState | 0 | Not applicable |
| RenderPerf | 1 | large table refresh may resize all rows |

## 15. Backend API Analysis

Not applicable as a network backend/API audit. There is no HTTP server, database API, auth middleware or public endpoint. The closest API boundary is local task package input, and it is covered under Security, Stability and Type Safety.

## 16. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| PySide6==6.10.1 | Healthy | Heavy by nature | Qt stack | Desktop GUI | Keep |
| openpyxl==3.1.5 | Healthy | Moderate | small | `tasks.xlsx` read/write | Keep |
| markdown-it-py==4.0.0 | Healthy | Light | mdurl | Markdown rendering with HTML disabled | Keep |
| beautifulsoup4==4.13.4 | Healthy | Light/Moderate | soupsieve | image rewrite/CID embedding | Keep |
| pyinstaller==6.18.0 | Healthy build dep | Moderate | hooks/contrib | Windows onefile EXE | Keep |

No unused direct dependency found in current tracked code. Current local Python environment has unrelated global `pip check` conflicts, but CI installs from `requirements.txt -c constraints.txt`, so those conflicts are not evidence against this project.

---

## 17. Code Consistency / Comment Coverage

代码风格总体一致：领域模块使用 dataclass、显式路径边界、中文用户错误信息、`unittest` 结构统一。注释质量比上一轮好，关键处如 `paths.py` 的工作目录策略、`task_package.py` 的原子写、`main_tasks.py` 的 busy guard、`task_delivery.py` 的 session error 分类都有解释。

需要注意的是，报告文件 `audit-report-DingMailSender-2026-06-05.md` 和 `audit-report-DingMailSender-2026-06-10.md` 已经是历史记录，不应被当作当前状态说明；当前 README/security docs 与实现基本一致。

---

## 18. Principles Compliance

总体遵守情况较好。项目现在的关键设计已经围绕“本地文件安全、用户数据不损坏、发送失败可追踪、敏感输出默认关闭”展开，这比单纯追求代码短更重要。仍需改进的是 GUI 状态边界、资源上限、协议状态类型化和发布治理。

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP) | 3 | Medium | `MainTaskMixin`, `dialogs.py`, `test_gui_main.py` |
| File/Class Size Limit | 3 | Medium | GUI dialogs/tasks/tests |
| Fail-Fast / Don't Swallow Errors | 3 | Medium/Low | migration cleanup, SMTP/IMAP teardown |
| Explicit Dependencies Over Implicit State | 1 | Medium | `MainWindow` state proxy |
| Unbounded Resources | 1 | Medium | attachments/images |
| Stringly Typed | 1 | Low | delivery outcome statuses |

### Principles Respected

- Path traversal defense is explicit and tested.
- Required connection config errors are surfaced, not silently replaced with defaults.
- Task file writes avoid partial corruption.
- Worker lifecycle avoids QThread destruction during active delivery.
- Logs and manifests avoid full recipient leakage by default.
- CI validates both source and packaged binary startup.

---

## 19. Recommended Fix Order

### Fix Immediately

No Critical or High findings in current tracked project.

### Fix Before Stable Release

| Priority | Issue | Rationale |
|----------|-------|-----------|
| 1 | Add visible warning when old plaintext config cleanup fails | Prevents false “迁移完成” security signal |
| 2 | Add attachment/inline image size limits | Prevents realistic local OOM/freezing |
| 3 | Add release tag/version/release notes discipline | Makes artifacts traceable and rollback possible |
| 4 | Add manual real SMTP/IMAP smoke gate for release candidates | Covers protocol risks mocks cannot catch |

### Schedule Later

| Priority | Issue | Rationale |
|----------|-------|-----------|
| 5 | Replace dynamic `_state_property` with explicit state access | Improves GUI maintainability |
| 6 | Convert delivery statuses to enum | Reduces cross-layer string contract bugs |
| 7 | Split GUI dialogs and GUI tests | Lowers review/test maintenance cost |
| 8 | Log SMTP/IMAP teardown warnings | Improves incident diagnosis |

### Ignore for Now

| Issue | Reason |
|-------|--------|
| PySide6 binary size | Expected for desktop GUI; current release audit already records size |
| In-memory scheduled queue | Documented product behavior for V1, not hidden reliability bug |

## 20. Quick Wins

- Return cleanup warning from `migrate_connection_profile_if_needed` when `unlink` fails.
- Add `MAX_ATTACHMENT_BYTES`, `MAX_INLINE_IMAGE_BYTES`, `MAX_TASK_PAYLOAD_BYTES` constants and validation errors.
- Add `DeliveryStatus(StrEnum)` and replace string literals in `task_delivery.py` and `main_delivery.py`.
- Add `v0.1.1` tag/release checklist with smoke result and SHA256.
- Add `scripts/check_workspace_sensitive.ps1 -DryRun` to list ignored worktree/package residues.

## 21. Long-term Refactor Plan

1. Stabilize GUI state ownership.
   Motivation: mixins share dynamic state and make feature changes risky. Approach: introduce explicit controller/view-model objects and remove runtime property injection. Risk: medium, because many tests touch `_state` and widget fields. Testing strategy: keep current GUI regression tests, then split by package/delivery/tray.

2. Formalize release lifecycle.
   Motivation: CI builds artifacts but version traceability is weak. Approach: tag-based releases, artifact names with version, release notes with test matrix and SHA256. Risk: low. Testing strategy: CI checks version consistency and artifact naming.

3. Add real mailbox compatibility coverage.
   Motivation: SMTP/IMAP provider behavior is the highest external uncertainty. Approach: maintain a manual smoke SOP first, then move to a controlled test mailbox if stable. Risk: medium due to secrets and side effects. Testing strategy: environment-gated smoke stays opt-in, but release checklist records evidence.
