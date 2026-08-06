# Fuck My Shit Mountain Audit Report

**Project:** DingMailSender
**Audit mode:** full
**Date:** 2026-06-05
**Reviewer:** Codex GPT-5

---

## 1. Executive Summary

DingMailSender 不是典型“屎山代码”。源码规模可控，核心路径有测试，`src` 下 27 个文件全部通过质量扫描，35 个单元测试通过，`compileall` 也通过。代码里已经能看到明确的工程边界：邮件构建、Markdown 渲染、任务包 Excel、运行输出、SMTP/IMAP 会话、GUI worker 都被拆到了独立模块。

但它有几个会在后续迭代中快速放大的结构风险。最明显的是 GUI 主窗口通过多个 mixin 拆文件，但这些 mixin 共享同一个 `MainWindow` 私有状态池，本质上还是“分布式大对象”。其次，`MailTask` 同时承载持久任务字段和运行态字段，当前没有造成数据损坏，但后续保存、筛选、队列、历史状态扩展会越来越难推理。发布侧最大问题是仓库跟踪了真实任务包数据，里面包含业务预算正文、部门信息和收件邮箱；如果仓库或分发包被共享，这不是代码味道，而是实际数据边界风险。

总体判断：当前项目是“可维护但已有结构债”的状态，不是不可救的屎山。优先处理数据边界、GUI 状态归属和发布流程后，项目健康度会明显提升。

### Score Dashboard

```
Security        ███████░░░  7.0  A   DPAPI、路径越界和 HTML 注入防护做得不错，但 Git 跟踪了真实任务包业务数据和邮箱。
Stability       ███████░░░  7.3  A   外部网络调用有 timeout，任务级错误能落到 outcome，但 GUI worker 生命周期和运行态混合仍有脆弱点。
Performance     ████████░░  8.0  A   桌面批量邮件场景规模不大，当前 I/O 和渲染路径可接受；主要风险来自大任务表全量刷新和 Excel 全量读写。
Testing         ███████░░░  7.0  A   35 个测试覆盖核心纯逻辑和部分 GUI 状态，但保存草稿/发信/打包 EXE 缺少真实端到端烟测。
Maintainability ██████░░░░  6.5  B   源码不大，但 MainWindow mixin、MailTask 运行态和 task_package 多职责是后续屎山化主因。
Design          ██████░░░░  6.6  B   SRP、DRY、类型边界有局部违反；路径与安全边界设计较清晰。
Release         ██████░░░░  6.0  B   有 PyInstaller 脚本和固定依赖版本，但无 CI、无锁文件、无产物校验，且真实任务包被纳入版本库。
─────────────────────────────────────
Overall         ██████░░░░  6.9  B
```

Each dimension scored 0.0–10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based. See `rubrics/scoring.md` for anchor descriptions.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 1 | 1 | 0 |
| Medium | 5 | 5 | 0 |
| Low | 3 | 3 | 0 |
| Info | 3 | 3 | 0 |
| **Total** | **12** | **12** | **0** |

## 2. Project Map

Runtime entry points:

- `dingmail_gui.py` 是桌面入口，优先导入 `dingmail.gui.main.run`，开发模式下再把 `src` 加到 `sys.path`。
- `src/dingmail/gui/main.py` 创建 `MainWindow`，加载连接配置，构建 UI、托盘和定时器。
- `src/dingmail/gui/workers.py` 用 `QThread` 执行 SMTP 测试、发送、保存 IMAP 草稿。

Main components:

- `src/dingmail/task_models.py` 定义 `MailTask` 和 `PackageLayout`。
- `src/dingmail/task_package.py` 负责 `tasks.xlsx` schema、读写、任务 ID 修复、模板任务包生成、任务克隆。
- `src/dingmail/task_service.py` 负责任务校验、预览、邮件渲染入口。
- `src/dingmail/rendering.py` 负责 Jinja2/Markdown/HTML/图片 CID 处理。
- `src/dingmail/email_builder.py` 负责 EmailMessage 构建、header 控制字符拒绝、附件加载。
- `src/dingmail/smtp_sender.py` 和 `src/dingmail/imap_drafts.py` 是外部邮箱网络边界。
- `src/dingmail/run_store.py` 创建运行目录、manifest、日志与快照。
- `src/dingmail/connection_profile.py` 保存发件邮箱与 SMTP 授权码，Windows 下使用 DPAPI。

Data flow:

1. 用户导入任务包目录。
2. `task_package.load_tasks_from_package()` 从 `tasks.xlsx` 读取 `MailTask`。
3. GUI 将任务交给 `TaskRuntimeController` 校验、标记状态、筛选和队列。
4. 保存草稿路径：`MainDeliveryMixin._start_save_drafts()` -> `SaveDraftsWorker` -> `save_tasks_to_imap_drafts()` -> `ImapDraftsSession.append_draft()`。
5. 立即发送路径：`MainDeliveryMixin._start_send()` -> `SendTasksWorker` -> `send_tasks()` -> `SmtpSession.send()`。
6. 每次运行写入 `runs/<timestamp>_<package>/manifest.csv`，默认只保存 manifest、日志和任务包快照；完整 `.eml`/preview 受 `DINGMAIL_SAVE_DEBUG_ARTIFACTS` 控制。

State ownership:

- `MainWindow` 拥有 `_tasks`、`_package_dir`、SMTP 配置、worker 引用、状态标签、按钮、表格、托盘、定时器。
- `TaskRuntimeController` 拥有队列 ID、发送中 ID、草稿中 ID、校验缓存，但同时直接修改 `MailTask.status/error_message/last_send_result`。
- UI mixin、任务 mixin、视图 mixin、发送 mixin 都读写同一个 `MainWindow` 私有状态集合。

Persistence layer:

- 任务包持久化为 Excel：`packages/<name>/tasks.xlsx`。
- 运行记录持久化为本地 `runs/`。
- 连接配置持久化为用户配置目录下 `conn_profile.json`；`.gitignore` 忽略该文件。
- 没有显式 schema version 或迁移机制。

External interfaces:

- 文件系统：任务包、Markdown、图片、附件、运行记录、连接配置。
- 网络：SMTP、IMAP SSL。
- 桌面系统：Qt GUI、系统托盘、`QDesktopServices.openUrl()` 打开目录/文件。

Security boundaries:

- Markdown HTML 被禁用：`MarkdownIt("default", {"html": False})`。
- 邮件 header 控制字符被拒绝。
- 附件和本地图片路径限制在任务包目录内。
- 授权码在 Windows 上用 DPAPI 保护。
- 风险边界主要是 Git 跟踪真实业务任务包和历史 plaintext 连接配置兼容读取。

Testing structure:

- `tests/test_task_package.py` 覆盖任务表读写、额外列保留、任务 ID 修复、路径越界拒绝。
- `tests/test_task_delivery.py` 用 fake SMTP/IMAP 覆盖发送/草稿结果、节流、debug artifacts。
- `tests/test_task_service_and_imap.py` 覆盖预览、HTML 转义、换行、图片缺失、IMAP UTF-7。
- `tests/test_gui_main.py` 用 offscreen Qt 覆盖部分主窗口状态、布局、运行历史和托盘退出。
- `tests/test_connection_profile.py` 覆盖 DPAPI、legacy password、fallback path。

Release process:

- `build_exe.ps1` 创建/复用 `.venv`，安装 `requirements.txt`，运行 PyInstaller 输出 `release/DingMailSender.exe`。
- `pyproject.toml` 与 `requirements.txt` 固定直接依赖版本。
- 未发现 `.github/workflows`、锁文件、checksum/signature/SBOM 或自动打包验证。

## 3. Top Risks

1. **High: 真实业务任务包被 Git 跟踪** — `packages/预算执行通知` 下 78 个文件包含业务预算正文、图片、收件邮箱和 Excel，已经进入版本库。
2. **Medium: GUI mixin 拆文件但共享同一私有状态池** — `MainWindow` 通过 4 个 mixin 组合，实际仍是分布式大对象。
3. **Medium: `MailTask` 同时承载持久任务和运行状态** — 运行态字段直接写入任务模型，状态来源不清晰。
4. **Medium: 任务包模块职责过多** — schema、Excel I/O、模板生成、ID 修复、路径解析、clone 都在 `task_package.py`。
5. **Medium: 发布流程缺少 CI、锁文件和产物校验** — 当前 release 依赖本机脚本与在线 pip 解析，难以稳定复现。
6. **Medium: 核心外部链路缺少真实端到端烟测** — 单测通过，但 IMAP 草稿、SMTP 发送、EXE 启动没有自动化验证。
7. **Low: Qt Signal 用 `object` 加 `assert isinstance` 做运行时类型校验** — optimized Python 下 assert 会消失，类型错误会延后爆炸。
8. **Low: 发送和保存草稿 worker 生命周期重复** — 后续加取消、进度、恢复、通知时容易漏改。
9. **Low: 配置读取存在静默默认和 legacy plaintext 兼容** — 合理但需要可见提示和迁移计划。
10. **Info: 本地工作区存在忽略的 `.claude/worktrees` 残留** — 不进 Git，但会干扰全仓扫描和磁盘体积。
11. **Info: 设计 demo HTML 被跟踪** — 可作为设计档，但应明确不是运行时代码。

## 4. Detailed Findings

### Finding: 真实业务任务包被纳入版本库

- Severity: High
- Confidence: High
- Category: Security / Release
- Status: Confirmed
- Affected area: Repository data boundary
- Evidence:
  - File: `packages/预算执行通知/tasks.xlsx`
  - File: `packages/预算执行通知/部门收件人映射模板.xlsx`
  - File: `packages/预算执行通知/content/*/预算执行情况传达书.md`
  - Relevant behavior: `git ls-files packages` 返回 78 个被跟踪文件；Excel 中包含真实收件邮箱，Markdown 中包含部门预算、成本、费用执行数据。
- Problem: 仓库中不只是示例模板，还包含真实部门、收件人邮箱和预算执行文本。如果仓库是公开的、被外包协作方拉取、或 release 打包时误带入这些文件，会产生业务数据泄露。
- Why it matters: 这是数据边界问题，不是代码风格问题。邮件系统项目的任务包天然包含收件人、业务内容、附件和图片，这些不应默认跟源码生命周期绑定。
- Realistic failure scenario: 维护者把 GitHub 仓库授权给外部协作者，或者把项目压缩包发给他人排查 UI 问题，对方同时拿到预算通知正文、部门邮件地址和图片材料。
- Minimal fix: 从 Git 跟踪中移除 `packages/预算执行通知`，保留脱敏的最小示例包，例如 `examples/sample_package`，并在 `.gitignore` 增加 `packages/*` 或至少忽略真实任务包目录。
- Better long-term fix: 建立“源码仓库只放代码和脱敏示例，真实任务包放用户数据目录”的规则；增加一个脚本扫描 `packages/` 下邮箱、公司域名和业务关键词，作为提交前检查。
- Regression test suggestion: 添加仓库卫生检查脚本，断言 `git ls-files packages` 不包含 `.xlsx`、`.png` 或含公司邮箱域名的 `.md`。
- Estimated effort: 1-2 hours；如果要清理 Git 历史，需要额外 0.5-1 day 并谨慎处理远端影响。

### Finding: MainWindow mixin 形成分布式大对象

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: GUI architecture
- Evidence:
  - File: `src/dingmail/gui/main.py:22`
  - Function / Module: `MainWindow(MainUiMixin, MainViewMixin, MainTaskMixin, MainDeliveryMixin, QMainWindow)`
  - Relevant behavior: `MainWindow` 初始化 `_home_dir`、`_smtp_cfg`、`_smtp_password`、`_package_dir`、`_tasks`、`_runtime`、worker、按钮字典等共享字段。
  - File: `src/dingmail/gui/main_ui.py:60-87`, `src/dingmail/gui/main_tasks.py:314-393`, `src/dingmail/gui/main_delivery.py:14-99`
- Problem: 文件被拆小了，但状态所有权没有拆开。每个 mixin 都假设其他 mixin 已经创建了某些私有字段，例如按钮、表格、runtime、SMTP 状态、任务列表。这种结构缺少显式接口，重命名或移动字段时静态检查很难提前发现。
- Why it matters: 当前 UI 仍在快速调整，主路径也刚从“发送”转向“保存草稿复核”。后续继续加账号、多任务包、运行历史、草稿复核状态时，跨 mixin 私有字段会让变更影响范围变得不可预测。
- Realistic failure scenario: 修改 `main_ui.py` 中按钮命名或初始化顺序，`main_tasks.py` 的 `_refresh_task_action_buttons()` 运行时访问不存在字段，只有打开 GUI 并进入特定状态才暴露。
- Minimal fix: 引入 `MainWindowState` dataclass 和少量明确的 UI refs 容器，把共享状态集中声明；mixin 方法只通过 state/ref 对象访问。
- Better long-term fix: 将主窗口拆成组合式组件：`ConnectionController`、`PackageController`、`TaskTableController`、`DeliveryController`、`RunHistoryController`。`MainWindow` 只负责装配和事件转发。
- Regression test suggestion: 增加一个 smoke 测试实例化 `MainWindow` 后遍历主路径按钮：连接设置、导入、筛选、选中任务、保存草稿、运行历史，确认没有 AttributeError。
- Estimated effort: 1-2 days 做低风险 state/ref 容器；3-5 days 做完整 controller 拆分。

### Finding: MailTask 同时表示持久数据和运行态

- Severity: Medium
- Confidence: High
- Category: Maintainability / Stability
- Status: Confirmed
- Affected area: Task state model
- Evidence:
  - File: `src/dingmail/task_models.py:7-24`
  - Function / Module: `MailTask`
  - Relevant behavior: `MailTask` 同时包含持久字段 `to_recipients/subject/markdown_path/scheduled_at` 和运行字段 `status/error_message/last_previewed_at/last_send_result`。
  - File: `src/dingmail/gui/task_runtime.py:53-56`, `src/dingmail/gui/task_runtime.py:95-121`, `src/dingmail/gui/task_runtime.py:148-185`
- Problem: `TaskRuntimeController` 直接修改 `MailTask.status` 等字段；同一个对象又被 GUI 表格、筛选、Excel 保存逻辑、worker deep copy 共享。虽然 `save_tasks_to_package()` 当前没有写出运行态字段，但模型层边界已经混在一起。
- Why it matters: 状态来源不清晰会让 UI 表示和业务事实混淆。保存草稿成功、发送失败、定时队列、校验失败这些都是运行状态，不应和 Excel 任务定义有同等地位。
- Realistic failure scenario: 后续有人为了“保存运行结果到 tasks.xlsx”把 `status` 加进 `TASK_COLUMNS`，导致临时失败状态被持久化；下次打开任务包时，旧错误状态被误认为当前校验结果。
- Minimal fix: 新增 `TaskRuntimeState`，用 `task_id -> runtime_state` 存储 `status/error/last_result/queued/sending/drafting`；`MailTask` 只保留任务定义字段。
- Better long-term fix: 表格行状态由 `derive_task_view_model(task, runtime_state, validation_result)` 计算，不直接改任务对象。
- Regression test suggestion: 测试保存任务包后重新加载，运行态字段不会影响 Excel 内容；测试 runtime state 切换不改变 `MailTask` 的持久字段快照。
- Estimated effort: 1-2 days。

### Finding: task_package.py 负责过多任务包职责

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Task package persistence
- Evidence:
  - File: `src/dingmail/task_package.py:20-33`
  - Function / Module: `TASK_COLUMNS`
  - Relevant behavior: 定义 Excel schema。
  - File: `src/dingmail/task_package.py:49-118`
  - Relevant behavior: 解析邮箱/路径/布尔/时间和路径越界检查。
  - File: `src/dingmail/task_package.py:178-306`
  - Relevant behavior: Excel 读写、额外列快照、行扩缩、任务加载保存。
  - File: `src/dingmail/task_package.py:309-382`
  - Relevant behavior: 模板任务包、README 文本、clone。
- Problem: 该模块不到 500 行，但职责已经超过 3 个清晰原因：schema 演进、Excel I/O、模板文档、路径策略、任务克隆。当前还能读，但下一次任务字段变更会同时触碰解析、写入、模板、测试和 GUI。
- Why it matters: 任务包是核心数据格式，后续最容易变化。模块职责过多会增加 schema migration 和兼容处理的风险。
- Realistic failure scenario: 增加“人工复核状态”列时，开发者只更新 `TASK_COLUMNS` 和 `_mail_task_from_row()`，忘记模板、额外列保留、测试和 README，导致用户下载模板后字段不一致。
- Minimal fix: 拆出 `task_schema.py`、`task_excel_io.py`、`package_template.py`；或者先把模板生成与 clone 移出当前文件。
- Better long-term fix: 给任务包 schema 增加 version，并把读写迁移集中在一个 `TaskPackageRepository`。
- Regression test suggestion: 增加 schema 快照测试，断言模板 README、`TASK_COLUMNS`、Excel header、读写 round-trip 一致。
- Estimated effort: 0.5-1 day 做轻拆；2-3 days 做 schema version。

### Finding: 发布流程缺少可复现构建与发布门禁

- Severity: Medium
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Build and release
- Evidence:
  - File: `build_exe.ps1:31-50`
  - Function / Module: PyInstaller build script
  - Relevant behavior: 本地创建 `.venv`，执行 `pip install -U pip` 和 `pip install -r requirements.txt` 后打包。
  - File: `pyproject.toml:6-18`, `requirements.txt:1-9`
  - Relevant behavior: 直接依赖固定版本，但没有锁文件。
  - File: `.github/workflows`
  - Relevant behavior: 未发现 CI workflow。
- Problem: 目前 release 成功依赖本机环境和实时 pip 解析；没有自动运行单测、编译检查、打包检查、产物 checksum 或签名。`DingMailSender.spec` 存在但 `.gitignore` 又忽略 `*.spec`，当前是否长期维护 spec 也不清晰。
- Why it matters: 桌面工具最终交付给非开发用户，打包缺陷和依赖漂移会直接变成“打开不了/被杀软拦截/行为不一致”。
- Realistic failure scenario: 未来某个依赖发布破坏性 wheel 或 PyInstaller hook 行为变化，本地开发机缓存正常，另一台机器重新打包失败或 EXE 启动失败。
- Minimal fix: 增加 GitHub Actions 或本地 release checklist：`python -m unittest discover -s tests`、`python -m compileall src dingmail_gui.py tests`、PyInstaller build、EXE 启动 smoke、生成 SHA256。
- Better long-term fix: 使用锁文件或 constraints 文件管理完整解析结果；发布产物带版本号、checksum、变更说明和可回滚的上一版。
- Regression test suggestion: CI 在 Windows runner 上跑单测、compileall、build，并保存 artifact。
- Estimated effort: 0.5-1 day。

### Finding: 核心邮箱链路缺少真实端到端烟测

- Severity: Medium
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: SMTP/IMAP delivery confidence
- Evidence:
  - File: `tests/test_task_delivery.py:83-85`
  - Function / Module: `test_send_tasks_only_sleeps_between_tasks`
  - Relevant behavior: Patch `SmtpSession`、`render_task_email` 和 `rate_limit_sleep`。
  - File: `tests/test_task_delivery.py:159-161`
  - Relevant behavior: Patch `ImapDraftsSession`、`render_task_email` 和 `rate_limit_sleep`。
  - File: `tests/test_gui_main.py:64-73`
  - Relevant behavior: GUI 测试 patch home、connection profile、system tray，用 offscreen Qt。
- Problem: 这些测试对单元逻辑很有价值，但没有覆盖真实邮箱服务器、真实 IMAP 草稿箱选择、打包 EXE 启动、Windows DPAPI 与 GUI 主流程的组合行为。
- Why it matters: 用户主路径是“保存草稿 -> 人工复核”，最关键风险恰好在 IMAP 草稿写入和邮箱端可见性。fake session 无法捕获服务器草稿箱命名、编码、权限、授权码过期、邮件客户端显示差异。
- Realistic failure scenario: 单测全部通过，但某企业邮箱的草稿箱名称不是 `Drafts/草稿箱` 任何候选，或 IMAP append flags 不被接受，用户批量保存草稿失败。
- Minimal fix: 增加手动可运行的 smoke 脚本或测试标记，例如 `DINGMAIL_SMOKE_IMAP=1` 时读取临时测试账号，把一封邮件保存到草稿并校验返回 mailbox。
- Better long-term fix: 建立 release 前 checklist：真实账号连接、保存 1 封草稿、打开 EXE、导入脱敏任务包、预览、运行历史。
- Regression test suggestion: 添加跳过默认执行的 `tests/test_mailbox_smoke.py`，只有提供环境变量时运行；CI 可保留为 manual workflow。
- Estimated effort: 0.5 day 建脚本；1 day 集成 manual CI。

### Finding: Qt signal payload 依赖 assert 做运行时类型校验

- Severity: Low
- Confidence: High
- Category: Stability / Design
- Status: Confirmed
- Affected area: GUI worker result handling
- Evidence:
  - File: `src/dingmail/gui/main_delivery.py:37-40`
  - Function / Module: `_start_send._ok`
  - Relevant behavior: `finished_ok` 是 `Signal(object)`，handler 用 `assert isinstance(result, SendTasksResult)` 后调用 `_apply_send_result()`。
  - File: `src/dingmail/gui/main_delivery.py:84-87`
  - Function / Module: `_start_save_drafts._ok`
- Problem: `assert` 在 `python -O` 下会被移除；即使当前 PyInstaller `optimize=0`，这仍不是可靠的运行时边界。错误 payload 会在后续属性访问处报更模糊的异常。
- Why it matters: Qt signal 已经把类型擦成 `object`，这里是跨线程边界，应该 fail-fast 且错误信息明确。
- Realistic failure scenario: 后续 worker 改动误发字符串或异常对象，开发模式能触发 assert，优化构建或不同启动方式下 assert 被跳过，错误变成 `_apply_*` 内部 AttributeError。
- Minimal fix: 改为显式检查：`if not isinstance(result, SendTasksResult): self._show_error_dialog(...); return`。
- Better long-term fix: 给发送和草稿 worker 分别使用更明确的 result signal 包装类型，或统一 `WorkerResult[T]`。
- Regression test suggestion: 直接调用 `_ok("bad")` 或通过 fake signal 传入错误类型，断言 GUI 显示明确错误且不会崩溃。
- Estimated effort: 30 minutes。

### Finding: 发送和保存草稿 worker 生命周期重复

- Severity: Low
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: GUI delivery orchestration
- Evidence:
  - File: `src/dingmail/gui/main_delivery.py:14-59`
  - Function / Module: `_start_send`
  - Relevant behavior: busy 检查、空任务检查、mark state、刷新 UI、创建 worker、connect ok/error、清理 worker、启动。
  - File: `src/dingmail/gui/main_delivery.py:61-99`
  - Function / Module: `_start_save_drafts`
  - Relevant behavior: 相同生命周期逻辑重复一遍。
- Problem: 当前重复不大，但这是主路径。后续加入取消、进度条、重试策略、通知、运行历史跳转时，需要在两条路径同步维护。
- Why it matters: 重复生命周期代码容易出现“发送路径修了，草稿路径没修”的不一致，特别是草稿现在才是主路径。
- Realistic failure scenario: 新增“运行中禁用关闭窗口”只加在 `_start_send`，保存草稿时用户仍可关闭主窗口造成 worker 状态难以解释。
- Minimal fix: 抽一个 `_start_delivery_worker(kind, tasks, build_worker, mark_running, apply_result, mark_error)` 小 helper。
- Better long-term fix: 引入 `WorkerRunner`，统一 busy state、result validation、error dialog、tray notification、UI refresh。
- Regression test suggestion: 对发送和保存草稿分别模拟 worker ok/error，断言 worker 引用清理、按钮状态恢复、runtime 状态一致。
- Estimated effort: 1-2 hours。

### Finding: 连接配置存在 legacy plaintext 兼容和静默候选路径

- Severity: Low
- Confidence: High
- Category: Security / Configuration / Fallback
- Status: Confirmed
- Affected area: Connection profile compatibility
- Evidence:
  - File: `src/dingmail/connection_profile.py:100-107`
  - Function / Module: `load_connection_profile`
  - Relevant behavior: 如果没有 `smtp_password_protected`，读取 `smtp_password` 或旧字段 `password`，并以 `"plain"` 模式返回。
  - File: `src/dingmail/connection_profile.py:119-142`
  - Relevant behavior: 保存时遍历候选 path，写入失败后尝试下一个 path。
- Problem: legacy plaintext 读取是兼容需要，但没有显式迁移提示；候选路径 fallback 对库调用者来说也不够可见。GUI 当前保存只传一个路径，风险有限。
- Why it matters: 凭据处理应该尽量可见。旧明文配置如果长期留存，用户可能误以为已经全部 DPAPI 加密。
- Realistic failure scenario: 用户目录里有旧 `conn_profile.json` 明文授权码，程序能正常读取，用户长期不知道需要重新保存来迁移。
- Minimal fix: 当读取 legacy/plain password 时返回一个 `needs_migration` 标志或 warning，连接成功后自动重写为 DPAPI 格式。
- Better long-term fix: 用 versioned profile schema，例如 `schema_version: 2`，明确迁移路径。
- Regression test suggestion: 加载旧 `password` 字段后，触发保存迁移，断言文件不再包含原授权码。
- Estimated effort: 1-2 hours。

### Finding: 配置缺失时使用默认 SMTP/IMAP 假设但缺少来源可见性

- Severity: Info
- Confidence: High
- Category: Configuration
- Status: Confirmed
- Affected area: Campaign config and connection defaults
- Evidence:
  - File: `src/dingmail/config_io.py:69-72`
  - Function / Module: `load_campaign_config`
  - Relevant behavior: 没有 `campaign.yml` 时返回 `CampaignConfig()`。
  - File: `src/dingmail/config_io.py:36-44`
  - Relevant behavior: SMTP host/port/security 缺失时使用 `SmtpConfig()` 默认值。
  - File: `src/dingmail/constants.py:1-5`
  - Relevant behavior: 默认 IMAP 为阿里企业邮箱。
- Problem: 这是本地工具的合理默认，不应升级成高危。但用户排查连接问题时，UI/日志最好显示“当前使用默认值还是任务包配置值”。
- Why it matters: 默认值隐藏来源会增加排障时间，尤其是企业邮箱服务器或账号体系变化时。
- Realistic failure scenario: 用户切换到非阿里企业邮箱，任务包没有配置文件，界面仍使用默认服务器，连接失败但用户不知道配置来源。
- Minimal fix: 在连接设置或状态栏显示“来源：默认 / campaign.yml / 用户保存配置”。
- Better long-term fix: 统一配置来源模型，支持 `effective_config` 展示和导出。
- Regression test suggestion: 没有 `campaign.yml`、有 `campaign.yml` 两种路径分别断言 UI 状态展示配置来源。
- Estimated effort: 1 hour。

### Finding: 本地工作区有忽略的代理 worktree 残留

- Severity: Info
- Confidence: High
- Category: Maintainability / Release
- Status: Confirmed
- Affected area: Workspace hygiene
- Evidence:
  - File: `.gitignore:20-23`
  - Function / Module: ignore rules
  - Relevant behavior: `.claude/` 被忽略。
  - Workspace observation: `.claude/worktrees` 下存在多个 `agent-*` worktree；本次扫描统计约 312 个文件、约 9 MB。
- Problem: 这些文件不在 Git 中，不会污染仓库；但它们会干扰全仓 `Get-ChildItem`、手工压缩、磁盘体积和非 Git-aware 的审计脚本。
- Why it matters: 工作区杂物会让“项目到底有哪些文件”变得不清楚，尤其是用户手动打包或发 zip 给别人时。
- Realistic failure scenario: 用户直接压缩项目目录发给别人，`.claude/worktrees` 里的旧代码、旧任务包和图片一起被发出。
- Minimal fix: 定期清理 `.claude/worktrees`，并在 release/zip 脚本里只包含 `git ls-files` 或显式 allowlist。
- Better long-term fix: 增加 `scripts/package_source.ps1`，只打包源码、docs、脱敏 examples，不包含 ignored workspace。
- Regression test suggestion: release 脚本 dry-run 输出文件清单，断言不包含 `.claude/`、`.venv/`、`build/`、`release/`、真实 `packages/`。
- Estimated effort: 30 minutes。

### Finding: 设计 demo HTML 被跟踪但没有运行边界说明

- Severity: Info
- Confidence: High
- Category: Documentation / Release
- Status: Confirmed
- Affected area: Design artifacts
- Evidence:
  - File: `design/dingmail-workbench-demo.html`
  - File: `design/dingmail-workbench-no-sidebar-demo.html`
  - File: `design/dingmail-ui-redesign-plan.md`
  - Relevant behavior: 这些文件由 `git ls-files` 跟踪，属于前期 UI 设计参考。
- Problem: 设计 demo 可以保留，但应明确“非运行时代码、非测试基准、仅设计参考”。否则后续 UI 与 demo 分叉时，维护者可能误以为 HTML demo 是需要同步维护的产品代码。
- Why it matters: 设计资产和运行代码边界不清，会增加维护噪声。
- Realistic failure scenario: 新开发者修改 PySide6 UI 后又手工同步 HTML demo，浪费时间且引入无意义 diff。
- Minimal fix: 在 `design/README.md` 或报告中注明 demo 生命周期：保留为历史参考，不作为发布或测试输入。
- Better long-term fix: 如果继续做设计演示，把 demo 生成方式脚本化或只保留最终方案截图/说明。
- Regression test suggestion: 无需代码测试；release 文件清单断言不包含 `design/*.html`，除非明确打包源码设计资料。
- Estimated effort: 15-30 minutes。

## 5. Security Concerns

Confirmed concerns:

- 真实业务任务包被 Git 跟踪，包含收件邮箱和预算执行正文。这是本次唯一 High severity 问题。
- Legacy plaintext password 读取路径仍存在，但 `.gitignore` 已忽略 `conn_profile.json`，保存路径在 Windows 上使用 DPAPI。

Positive security evidence:

- `src/dingmail/connection_profile.py:28-83` 使用 Windows DPAPI 保护授权码。
- `src/dingmail/email_builder.py:32-35` 拒绝邮件 header 控制字符。
- `src/dingmail/email_builder.py:70-83` 附件路径限制在任务包目录内。
- `src/dingmail/rendering.py:51-53` 禁用 Markdown 原始 HTML。
- `src/dingmail/rendering.py:60-70` 本地图片路径限制在任务包目录内。
- `src/dingmail/task_package.py:104-118` 用户路径限制在任务包目录内。

No confirmed issues found:

- 未发现 `eval`、`exec`、`subprocess shell=True`、SQL 拼接或网络请求代理类攻击面。
- 未发现硬编码授权码/API key。

## 6. Stability Concerns

Confirmed concerns:

- `MainDeliveryMixin` 的跨线程 result 类型边界靠 `assert`，应改成显式运行时检查。
- 保存草稿和发送 worker 生命周期重复，未来加取消/进度/恢复时容易产生不一致。
- `MailTask` 运行态与持久态混合，状态推导不够清晰。

Positive stability evidence:

- `src/dingmail/smtp_sender.py:18-39` 和 `src/dingmail/imap_drafts.py:65-77` 都设置了 30 秒 timeout。
- `src/dingmail/task_delivery.py:221-240` 和 `src/dingmail/task_delivery.py:273-297` 按单任务捕获异常，失败会进入 outcome 和 manifest，而不是整批直接中断。
- `src/dingmail/run_store.py:50-64` 对同秒运行目录冲突做了递增 suffix。

## 7. Performance Concerns

Confirmed concerns:

- 没有发现当前规模下的严重性能问题。
- 潜在增长点是 `src/dingmail/gui/main_tasks.py:314-324` 每次刷新全量重建表格行，`src/dingmail/task_package.py:238-241` 全量读取 Excel rows。几十到几百封邮件可接受，上千封任务会变慢。

Positive performance evidence:

- Debug `.eml` 和 preview artifacts 默认不写，`src/dingmail/task_delivery.py:182-189` 受 `DINGMAIL_SAVE_DEBUG_ARTIFACTS` 控制。
- 发送/草稿链路按任务顺序执行并有 rate limit，适合企业邮箱限制。

## 8. Testing Gaps

Confirmed gaps:

- 缺少真实 IMAP 草稿箱保存 smoke。
- 缺少真实 SMTP 连接/发送 smoke。
- 缺少 PyInstaller EXE 启动 smoke。
- GUI 测试主要断言私有字段状态，能覆盖回归但重构脆弱。

Valuable tests:

- `tests/test_task_package.py` 对 Excel 额外列保留和重复 ID 修复很有价值。
- `tests/test_task_service_and_imap.py` 覆盖了 HTML 转义、换行、图片缺失和 IMAP UTF-7。
- `tests/test_task_delivery.py` 覆盖了 manifest 脱敏和 debug artifact 开关。
- `tests/test_connection_profile.py` 覆盖 DPAPI 和 legacy 配置。

Verification run:

- `node C:\Users\Seller\.agents\skills\ccg\tools\verify-quality\scripts\quality_checker.js src --json`: passed，0 error，0 warning。
- `python -m unittest discover -s tests`: 35 tests OK。
- `python -m compileall src dingmail_gui.py tests`: OK。

## 9. Maintainability Concerns

Confirmed concerns:

- GUI mixin 是最大维护风险。
- `MailTask` 状态边界不清。
- `task_package.py` 职责偏多。
- `dialogs.py` 当前 414 行，包含 `TaskEditorDialog`、`PreviewDialog`、`MarkdownPreviewDialog`、`RunHistoryDialog`，还没超 500 行，但会是下一个膨胀点。

Positive maintainability evidence:

- 单个源码文件均未超过质量检查器 500 行阈值。
- 核心功能已有相对清晰的模块名。
- 多数函数长度合理，只有少数 UI 构造函数接近 50 行。

## 10. Design / Principles Concerns

Principle violations:

- SRP 1.1: `MainWindow` mixin 共享状态和 `task_package.py` 多职责。
- DRY 4.1: `_start_send` 与 `_start_save_drafts` 生命周期重复。
- Fail-Fast 4.4: Qt signal result 依赖 `assert`，错误类型边界不够明确。
- State & Side Effects 5.1/5.3: `TaskRuntimeController` 直接修改 `MailTask`。
- Configuration 9.2: 默认配置合理但来源提示不足。

Principles respected:

- 路径边界 fail-fast 明确。
- 网络 timeout 明确。
- SMTP/IMAP 会话被封装在边界类中。
- 运行输出默认脱敏邮箱和错误文本。

## 11. Release Concerns

Confirmed concerns:

- 无 CI workflow。
- 无完整锁文件，仅固定直接依赖版本。
- 无 EXE checksum/signature/SBOM。
- 真实任务包被版本库跟踪。
- 本地 `DingMailSender.spec` 存在，但 `.gitignore` 忽略 `*.spec`，应明确是否维护。

Positive release evidence:

- `build_exe.ps1` 设置 `$ErrorActionPreference = "Stop"`。
- build 脚本把 pip cache、tmp、PyInstaller workpath 放入 `build/`。
- `.gitignore` 已忽略 `.venv/`、`build/`、`release/`、`runs/`、`conn_profile.json`。

## 12. Documentation Accuracy

Confirmed concerns:

- README/操作说明描述了 SMTP 授权码保存和 Windows DPAPI，和代码基本一致。
- 设计 demo 缺少生命周期说明。
- 没有 architecture overview 文档；对于当前规模不是 blocker，但 GUI 架构重构前建议补一页。

Positive evidence:

- `README.md` 和 `操作说明_GUI版.md` 对用户主路径、SMTP/IMAP 需求和故障排查有基础说明。

## 13. Configuration Safety

Confirmed concerns:

- 默认 SMTP/IMAP 假设缺少来源展示。
- 连接配置 legacy plaintext 兼容需要迁移提示。

Positive evidence:

- `conn_profile.json` 被 `.gitignore` 忽略。
- 非 Windows 保存授权码会抛错，不会静默写明文。

## 14. Observability

Confirmed concerns:

- 运行日志是本地文件，足够桌面工具使用，但没有结构化事件或可导出的诊断包。
- GUI 错误对话框能显示 details，但没有统一“复制诊断信息”能力。

Positive evidence:

- 每次发送/草稿运行都有 `manifest.csv`。
- 邮箱和错误文本会被脱敏写入 manifest。
- 运行历史对 manifest 做了摘要展示。

## 15. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 3 | 3 | 0 | 0 |
| EmptyCatch | 2 | 2 | 0 | 0 |
| CompatibilityBranch | 1 | 1 | 0 | 0 |
| SilentCorrection | 1 | 1 | 0 | 0 |
| DefensiveGuess | 1 | 1 | 0 | 0 |

Details:

- `connection_profile.py:100-107` legacy plaintext password fallback: keep with migration alert。
- `config_io.py:69-72` missing campaign config -> defaults: keep with source visibility。
- `imap_drafts.py:121-124` IMAP UTF-7 decode failure -> raw mailbox name: keep, because mailbox listing is external input。
- `smtp_sender.py:47-51` / `imap_drafts.py:85-88` logout/close exceptions swallowed: acceptable cleanup fallback，但可记录 debug log。
- `task_package.py:138-158` missing/duplicate task IDs auto-repaired: acceptable silent correction because UI warns and tests cover。

## 16. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|---------------|------|--------|
| Task package Excel read/write | High | Schema migration still manual | Keep and augment schema snapshot |
| Rendering and email builder | High | Mail client display differences escape | Keep and add golden `.eml` smoke if needed |
| Delivery unit tests | Medium | Real SMTP/IMAP server behavior escapes | Keep but add manual integration smoke |
| GUI tests | Medium | Private-field assertions brittle | Keep but add user-flow smoke |
| Release build | Low | EXE startup/build regressions escape | Add CI/manual release smoke |

### Valuable Tests

- Excel 额外列保留。
- 任务 ID 自动修复。
- Markdown 预览 HTML escape。
- intro 单换行保留。
- header 控制字符拒绝。
- manifest 邮箱脱敏。
- 运行目录冲突处理。
- DPAPI 保存/读取。

### Suspicious Tests

- `tests/test_gui_main.py` 多处直接访问 `_tasks`、`_runtime`、`_task_table`、按钮私有字段。它们对当前回归有用，但重构 GUI 内部结构时会变脆。

### Missing Tests

- IMAP 真实草稿保存。
- SMTP 真实连接/发送或 dry-run。
- PyInstaller EXE 启动。
- GUI 主路径“导入任务包 -> 选择任务 -> 保存草稿 -> 打开运行历史”的端到端自动化。

---

## 17. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 1 | 0 | 0 | 0 | 1 |
| InputBoundary | 1 | 0 | 0 | 0 | 1 |
| OutputLeak | 0 | 0 | 0 | 0 | 0 |
| BooleanTrap | 0 | 0 | 0 | 0 | 0 |
| StringlyTyped | 1 | 0 | 0 | 1 | 0 |
| ErrorType | 1 | 0 | 0 | 0 | 1 |

Details:

- `main_delivery.py:38` 和 `main_delivery.py:85` 是 TypeAssertion 风险。
- `MailTask.status` 使用中文字符串状态，是 StringlyTyped；短期可接受，长期应改为 Enum。
- `connection_profile.py` 用 `ConnectionProfileLoadError`，但其他模块多用 generic `Exception` 作为 UI 边界捕获；桌面 GUI 可接受。

## 18. Frontend State Analysis

### Summary

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 3 | `MainTaskMixin`, `MainUiMixin`, `MainViewMixin` |
| StateDuplication | 1 | `MailTask` runtime fields + `TaskRuntimeController` ID sets |
| PropDrilling | 0 | 不适用，PySide6 桌面 UI |
| EffectChain | 1 | Qt signal/timer refresh chain |
| UIBusinessCoupling | 2 | Task table refresh + delivery state transitions |
| DOMasState | 0 | 不适用 |
| RequestState | 1 | Worker busy state |
| RenderPerf | 1 | Full table refresh |

Details:

- 这是 PySide6 桌面应用，不是浏览器前端；frontend-state 维度按 GUI 状态管理审计。
- 主要问题是主窗口组件拥有过多状态，并且 UI 刷新和业务状态切换互相调用。

## 19. Backend API Analysis

### Summary

| Subtype | Count | Affected Endpoints |
|---------|-------|-------------------|
| ApiConsistency | 0 | 不适用 |
| Validation | 0 | 不适用 |
| Auth | 0 | 不适用 |
| NplusOne | 0 | 不适用 |
| Caching | 0 | 不适用 |
| ErrorResponse | 0 | 不适用 |
| BusinessLogic | 0 | 不适用 |
| DataFlow | 0 | 不适用 |

This project has no backend HTTP API. The equivalent external boundaries are local files, SMTP and IMAP, already covered under Security, Stability and Configuration.

## 20. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| PySide6==6.10.1 | Healthy but heavy | Large desktop UI stack | High | GUI | Keep |
| openpyxl==3.1.5 | Healthy | Moderate | Low | Excel task packages | Keep |
| jinja2==3.1.6 | Healthy | Moderate | Moderate | Template rendering | Keep |
| markdown-it-py==4.0.0 | Healthy | Moderate | Low | Markdown rendering | Keep |
| beautifulsoup4==4.13.4 | Healthy | Moderate | Low | HTML image rewrite | Keep |
| PyYAML==6.0.3 | Healthy | Moderate | Low | campaign config | Keep |
| pyinstaller==6.18.0 | Build dependency | Large | Moderate | EXE packaging | Keep in build extra |

No unused direct dependency was confirmed. Main dependency issue is release reproducibility, not dependency bloat.

---

## 21. Code Consistency Analysis

Confirmed concerns:

- 状态字符串是中文 magic string，分布在 `task_runtime.py`、`main_view.py`、`main_tasks.py`、`main_delivery.py`。建议改为 Enum + label map。
- GUI 私有字段命名一致，但跨 mixin 隐式依赖太多。
- 错误处理模式总体一致：核心层抛异常或返回 outcome，GUI 边界弹窗；没有发现大量空 catch。

## 22. Comment Coverage Analysis

Confirmed concerns:

- Python 代码缺少模块级 docstring；对于私人工具不是 blocker。
- `task_package.py`、`task_runtime.py`、`imap_drafts.py` 有非显然业务规则，建议补少量“为什么这么做”的注释或模块说明。
- 没有发现大段过期 TODO/FIXME 或注释与代码明显冲突。

Positive evidence:

- 代码命名普遍清晰，注释不多但也没有大量噪音注释。

## 23. Principles Compliance

当前项目大体遵守 KISS、Fail-fast 边界和模块化，但在 GUI 状态所有权、任务模型职责和发布流程上存在明确原则债。它不是“不可维护屎山”，更像是“功能已经跑通，但如果继续堆 UI 和状态，会变成屎山”的阶段。

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP) | 2 | Medium | `MainWindow` mixins, `task_package.py` |
| DRY | 1 | Low | `main_delivery.py` worker lifecycle |
| Fail-Fast | 1 | Low | `assert isinstance` on signal payload |
| Immutability Preference | 1 | Medium | `MailTask` runtime mutation |
| Explicit Dependencies | 1 | Medium | mixins depend on shared private state |
| Configuration Visibility | 1 | Info | default SMTP/IMAP source |
| Release Reproducibility | 1 | Medium | build/release workflow |

### Principles Respected

- Path traversal prevention is explicit.
- Email header validation is explicit.
- External network clients have timeouts.
- Per-task delivery errors are captured as outcomes instead of crashing whole batch.
- Test suite covers several historical UI and rendering regressions.
- `.gitignore` already excludes most local build/runtime artifacts.

---

## 24. Fallback / Defensive Code Analysis

See section 15. Main conclusion: fallback code is mostly intentional and bounded. The only fallback that deserves near-term action is legacy plaintext connection profile migration visibility.

## 25. Testing Authenticity Analysis

See section 16. Main conclusion: unit tests are meaningful, not fake green checks. The gap is integration/release confidence, especially IMAP drafts and packaged EXE.

## 26. Type Safety Analysis

See section 17. Main conclusion: no unsafe blocks or widespread type escapes. Replace status strings with Enum and replace signal `assert` with explicit checks.

## 27. Frontend State Analysis

See section 18. Main conclusion: PySide6 GUI state is the primary future debt. The next refactor should reduce `MainWindow` shared private state before adding more workflow states.

## 28. Backend API Analysis

See section 19. Not applicable: no backend API.

## 29. Dependency Weight Analysis

See section 20. Dependencies are justified for a desktop email tool. Release reproducibility needs improvement more than dependency count.

---

## 30. Recommended Fix Order

### Fix Immediately

- Remove real `packages/预算执行通知` data from Git tracking and replace with a desensitized sample package.
- Add a repository hygiene check that blocks tracked `.xlsx`/`.png` task package data and company email domains.

### Fix Before Stable Release

- Add Windows CI or release workflow: test, compileall, build EXE, launch smoke, checksum.
- Add manual/flagged IMAP draft smoke test for the primary “保存草稿” path.
- Replace `assert isinstance` in worker result handlers with explicit runtime validation.
- Add release packaging allowlist so ignored local worktrees and real packages cannot enter source zips.

### Schedule Later

- Introduce `MainWindowState` and reduce mixin private-field coupling.
- Split `MailTask` persistent model from `TaskRuntimeState`.
- Split `task_package.py` by schema, Excel I/O and template generation.
- Convert task status strings to Enum.
- Add config source display and profile migration warning.

### Ignore for Now

- PySide6 dependency weight: justified by desktop GUI.
- Lack of backend API conventions: not applicable.
- Lack of full module docstrings: acceptable until architecture stabilizes.

## 31. Quick Wins

- Replace `assert isinstance(result, SendTasksResult)` with explicit check in `main_delivery.py`.
- Add `.gitignore` rule for real task packages and create `examples/sample_package` with fake emails.
- Add `scripts/check_repo_hygiene.ps1` to scan tracked packages and company email domains.
- Add `design/README.md` clarifying demo HTML is design reference only.
- Add `python -m unittest discover -s tests` and `python -m compileall src dingmail_gui.py tests` to a simple CI workflow.
- Add SHA256 generation to `build_exe.ps1`.
- Add UI label showing config source: default vs saved profile vs campaign config.

## 32. Long-term Refactor Plan

1. Data boundary first
   - Motivation: Prevent business data leakage through Git and release artifacts.
   - Approach: Move real packages out of repo, add desensitized examples, add hygiene check.
   - Risk: If history is cleaned, collaborators must coordinate pulls.
   - Testing strategy: `git ls-files packages` and hygiene script must pass.

2. GUI state ownership
   - Motivation: Stop `MainWindow` from becoming a distributed god object.
   - Approach: Add `MainWindowState`, then extract `DeliveryController` and `TaskTableController`.
   - Risk: GUI regressions from changed field access.
   - Testing strategy: Keep current offscreen GUI tests, add user-flow smoke around selection/save draft/history.

3. Task model split
   - Motivation: Separate persisted task definition from ephemeral runtime state.
   - Approach: Introduce `TaskRuntimeState` keyed by `task_id`; derive table status from task + runtime + validation.
   - Risk: Status display and filters may change.
   - Testing strategy: Add tests for every status transition and for Excel round-trip ignoring runtime state.

4. Release hardening
   - Motivation: Make EXE builds repeatable and releasable.
   - Approach: Add Windows CI, lock/constraints, smoke, checksum, release checklist.
   - Risk: CI setup friction and PyInstaller runtime quirks.
   - Testing strategy: CI artifact launch smoke and checksum verification.
