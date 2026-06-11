# DingMailSender 审计问题记录（精简版）

**Project:** DingMailSender
**Audit mode:** full（精简输出：仅问题清单 + 评分，应用户要求省略完整模板章节）
**Date:** 2026-06-10
**Reviewer:** Claude (Fable 5, claude-fable-5)
**验证基线:** 45 tests OK (2 skipped) · compileall OK · H1/H2 已用复现脚本实锤

---

## 评分

```
Security        ████████░░  7.5  A   DPAPI/路径越界/HTML禁用/header校验扎实；迁移后明文残留+凭据位置文档误导
Stability       ██████░░░░  5.8  B   2个已复现数据/启动缺陷 + 状态卡死 + 退出abort + 非原子写
Performance     █████████░  8.5  A   桌面规模无实际瓶颈；全表重建+逐键刷新是增长点
Testing         ████████░░  7.5  A   45测试真实有效+env门控烟测；恰好缺额外列/回退/busy绕过3个出事路径
Maintainability ███████░░░  7.0  A   模块边界清晰；死campaign层+动态属性代理+正则三处重复
Design          ███████░░░  7.0  A   运行态/持久态分离、StrEnum、worker统一是大改善；静默修正仍存
Release         ██████░░░░  6.3  B   CI+constraints+SHA256良好；48MB EXE进Git(仓库94MB)+机器路径spec+文档失真
─────────────────────────────────────
Overall         ███████░░░  7.1  A
```

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 2 | 2 | 0 |
| Medium | 6 | 6 | 0 |
| Low | 6 | 5 | 1 |
| Info | 3 | 3 | 0 |
| **Total** | **17** | **16** | **1** |

对比 2026-06-05 上一轮审计：12 项旧发现中 9 项已修复或显著改善（真实数据出库、CI/constraints/SHA256、assert→显式校验、worker 生命周期统一、MailTask 运行态拆分、状态 Enum、迁移提示、烟测、design README）。本轮为新挖掘问题。

---

## High

### H1 · tasks.xlsx 额外列数据丢失/串值（任务ID缺失或重复时）— Confirmed，已复现
- 证据：`src/dingmail/task_package.py:265`（缺失ID静默生成UUID不写回）、`task_package.py:177-189`（快照按task_id键控，空ID行跳过、重复ID后行覆盖前行）
- 复现结果：①整列空ID + 用户自加"部门"列 → 任意一次保存后整列清空，且无任何修复提示；②Excel复制行（ID重复）→ 导入修复写回后，首行额外列值被串成末行值（市场部→研发部），副本行清空
- 失败场景：用户在 tasks.xlsx 加"人工复核备注"列并日常复制行/手工建表，正常操作即丢列
- 修复：`_mail_task_from_row` 不再捏造UUID（保留空串交给 `ensure_unique_task_ids` 报告+写回）；快照改"首现task_id键 + 行位置兜底"双映射；写回时按ID匹配不到的行用位置兜底
- 回归测试：空ID/重复ID两场景 round-trip 断言额外列逐行保值；effort: 2-3h

### H2 · 打包版工作目录回退到 EXE 父目录 — Confirmed，已复现
- 证据：`src/dingmail/paths.py:58`（frozen 无标记时 `return start_dir.parent`）；复现：exe 在 `...\Tools\DingMail\` → home=`...\Tools`
- 失败场景：①用户把 EXE 放 `D:\DingMail\` → packages/runs 建到 `D:\` 根；②放 `C:\Program Files\DingMail\` → `MainWindow.__init__` 里 `ensure_layout` PermissionError → noconsole 下启动即死且无可读提示；③与 README"EXE 所在目录"承诺矛盾
- 修复：最终回退改为 `start_dir`（EXE 所在目录）；`gui/main.run()` 包启动异常弹 critical 对话框并提示 `DINGMAIL_HOME`
- 回归测试：fresh-install frozen 场景断言 home==exe目录；effort: 1h

## Medium

### M1 · 连接配置迁移后旧明文文件残留 — Confirmed
- 证据：`src/dingmail/connection_profile.py:141-153`（migrate 只写新文件，不删 `result.source_path`）；`docs/security.md:8` 声称"迁移为DPAPI密文"但明文仍留盘
- 失败场景：旧版明文 `conn_profile.json` 留在程序/工作目录，用户打包目录分享 → 授权码泄露
- 修复：迁移成功且 source≠target 时 best-effort 删除旧文件；effort: 30min

### M2 · 死代码 campaign 流 + jinja2/PyYAML 死依赖打进 EXE — Confirmed
- 证据：`config_io.py`(120行)、`recipients_excel.py`(90行)、`model.py` CampaignConfig/RecipientsConfig、`rendering.py:24-48` jinja 函数、`email_builder.py:70-95` load_attachments、`constants.py:2` STARTTLS常量、`task_package.py:308-330` 死再导出——零调用方、零测试；`import yaml` 与 `jinja2` 仅存在于死路径
- 失败场景：维护者误以为 campaign.yml 生效；EXE 体积/攻击面白白增加两个库
- 修复：整组删除 + requirements/pyproject/constraints 去 jinja2、PyYAML、MarkupSafe；effort: 1-2h

### M3 · 48MB EXE 被 Git 强制跟踪 — Confirmed
- 证据：`git ls-files` 含 `release/DingMailSender.exe`(48MB×2版本→仓库94.38MiB)；与 `.gitignore`(release/) 和 README:165 自相矛盾。（勘误：`DingMailSender.spec` 经核实未被跟踪，仅为含本机绝对路径的本地构建产物，不构成仓库问题）
- 修复：`git rm --cached` 两个 release 产物；hygiene 脚本加 release/与*.spec 跟踪检查；历史清理(94MB)另行决策；effort: 30min(+历史清理0.5d)

### M4 · 双击表格行绕过 busy 守卫 → 投递结果丢失、状态永久卡死 — Confirmed
- 证据：`main_ui.py:184`（itemDoubleClicked 无条件连 `_edit_selected_task`）、`main_tasks.py:196-210`（无 busy 检查，`_persist_tasks` 重建 `self._tasks` 对象）、`main_delivery.py:162-166`（按 `id()` 身份匹配 → 失配后结果不回写，sending/drafting_task_ids 永不清理）
- 失败场景：保存草稿进行中用户双击行→保存→批次完成后所有任务永远显示"草稿保存中"，需重新导入才能恢复
- 修复：增删改克隆四入口加 `_delivery_is_busy` 守卫；effort: 1h

### M5 · worker 运行中退出 → QThread destroyed → 进程 abort — Confirmed
- 证据：`main_view.py:177-187`（`_exit_from_tray` 只查 queued_task_ids）、`main_view.py:189-199`（无托盘时 closeEvent 直接 accept）；QThread 运行中被销毁 = Qt fatal
- 失败场景：200条草稿保存中用户从托盘退出 → 进程 abort、批次中断、重试产生重复草稿
- 修复：投递 worker 运行中拒绝退出/关闭并提示等待；effort: 1h

### M6 · tasks.xlsx 保存非原子，中断即损坏主数据文件 — Confirmed
- 证据：`task_package.py:303`（openpyxl 直接 `save(tasks_path)`，zip 写入先截断）；无备份机制
- 失败场景：保存瞬间断电/进程被杀/磁盘满 → tasks.xlsx 损坏且无副本（运行快照仅在发送/草稿时产生）
- 修复：写同目录临时文件 + `os.replace`，失败清理并保留原文件；effort: 1h

## Low

### L1 · 发送/草稿循环无会话级熔断 — Confirmed
- 证据：`task_delivery.py:236-238,293-295`（逐任务吞所有异常含 SMTPServerDisconnected，断连后剩余任务逐条失败+逐条 sleep）
- 修复建议：识别会话级异常提前中止并标记"已中止"；本轮不改（影响结果语义），列入后续

### L2 · 定时队列任务被改为非定时后误标"发送失败" — Confirmed
- 证据：`task_runtime.py:263-273`（collect_due_tasks 对 `not schedule_enabled` 的队列成员置 SEND_FAILED）；编辑路径不清队列成员
- 修复：该分支改为静默出队；`sync_task_ids` 顺带剔除已取消定时的队列ID；effort: 30min

### L3 · EMAIL_RE 三处重复 + 预览校验口径不一致 — Confirmed
- 证据：`main_support.py:9`、`task_runtime.py:14` 同一正则两份；`dialogs.py:296` PreviewDialog 直调 `validate_task` 缺邮箱格式检查，与表格状态口径不一致
- 修复：正则收敛到 `task_service`，邮箱格式检查并入 `validate_task`，runtime 删补充逻辑；effort: 1h

### L4 · 文档与实现不符（含凭据位置） — Confirmed
- 证据：`README.md:28,114`、`操作说明_GUI版.md:21`（称 conn_profile 在程序目录，实际已改 `%LOCALAPPDATA%\DingMailSender\`）；`README.md:33,101-106`、`操作说明_GUI版.md:151-160`（称每次输出 eml/previews，实际默认关闭、受 `DINGMAIL_SAVE_DEBUG_ARTIFACTS` 门控）；`README.md:116`（EXE 工作目录描述与 H2 行为矛盾）
- 修复：三处文档同步实现；effort: 1h

### L5 · 卫生脚本与 CI 盲区 — Confirmed
- 证据：`check_repo_hygiene.ps1:20`（内容扫描排除 .xlsx，敏感邮箱进 xlsx 不会被拦）；脚本不查 release/、*.spec 被跟踪（M3 因此漏网）；CI 无 EXE 启动烟测
- 修复：本轮加 release/spec 跟踪检查；xlsx 内容扫描与 EXE 烟测列入后续；effort: 30min

### L6 · IMAP mailbox 名含空格未加引号 — Suspected
- 证据：`imap_drafts.py:98,145`（LIST 提取的名字去引号后原样传给 append/select；imaplib 不自动加引号，含空格名会协议出错）；另 `:75` 改写 `imaplib._MAXLINE` 私有变量
- 修复：append/select 前按 IMAP 规则为含空格/特殊字符的名字加引号；effort: 30min

## Info

- I1 · `gui/main.py:166-199` 动态 property 代理：静态分析不可见，mixin 隐式契约仍在（较上版改善但未根治）
- I2 · `.claude/worktrees` 9.5MB 本地残留（不入 Git，影响打包/扫描）
- I3 · 无 ruff/mypy 配置；`main_state.py` 状态对象持有 UI 控件引用（state/UI 混合）

---

## 修复顺序

**立即修（本次会话执行）**：H1、H2、M1、M3、M4、M5、M6、M2、L2、L3、L4、L5(部分)、L6
**列入后续**：L1（会话级熔断，涉及结果语义）、M3 历史清理（94MB，需协调远端）、L5 的 xlsx 内容扫描与 CI EXE 烟测、I1/I3 结构性改进
**忽略**：I2（本地工作区杂物，不入库）

## 本次会话修复记录（2026-06-11 完成）

验证基线：**58 tests OK (2 skipped) · compileall OK · H1/H2/L2 复现脚本全部转绿 · hygiene 脚本通过**（修复前 45 tests，新增 13 个回归用例）。

| 项 | 修复内容 | 主要变更 |
|----|---------|---------|
| H1 | 额外列按"首现task_id键 + 行位置兜底"双映射保值；缺失ID不再静默捏造UUID，改由 `ensure_unique_task_ids` 报告并写回 | `task_package.py`；测试 ×3 |
| H2 | frozen 无标记时工作目录=EXE所在目录（兼容 release\ 与同级 packages 布局）；`run()` 包启动异常并弹错误框提示 `DINGMAIL_HOME` | `paths.py`、`gui/main.py`；测试 ×1 |
| M1 | 迁移成功且源≠目标时 best-effort 删除旧明文配置文件 | `connection_profile.py`；测试断言补强 |
| M2 | 删除 `config_io.py`、`recipients_excel.py`、CampaignConfig/RecipientsConfig、jinja 渲染函数、`load_attachments`、STARTTLS 常量、task_package 死再导出；依赖去 jinja2/PyYAML/MarkupSafe | 12 个文件；EXE 不再捆绑两个死库 |
| M3 | `git rm --cached` 两个 release 产物（本地文件保留）；hygiene 脚本新增 release/与*.spec 跟踪检查 | git 索引、`check_repo_hygiene.ps1` |
| M4 | 新增/编辑/复制/删除四入口加 busy 守卫（封死双击绕过） | `main_tasks.py`；GUI 测试 ×1 |
| M5 | 投递 worker 运行中拒绝托盘退出与无托盘关闭，避免 QThread 运行中销毁导致进程 abort | `main_view.py`、`main_delivery.py`；GUI 测试 ×2 |
| M6 | tasks.xlsx 改"临时文件 + os.replace"原子写，失败保留原文件并清理临时文件 | `task_package.py`；测试 ×1 |
| L2 | 入队后被改为非定时的任务静默出队，不再误标"发送失败"；`sync_task_ids` 同步剔除 | `task_runtime.py`；新建 `test_task_runtime.py` ×3 |
| L3 | EMAIL_RE 收敛到 `task_service` 并并入 `validate_task`（预览/表格校验口径统一），删除两处重复定义 | `task_service.py`、`task_runtime.py`、`main_support.py`、`main_view.py`；测试 ×1 |
| L4 | README/操作说明/security.md 同步：凭据实际位置（LOCALAPPDATA）、eml/previews 受 `DINGMAIL_SAVE_DEBUG_ARTIFACTS` 门控、EXE 工作目录规则、迁移删除旧明文文件 | 3 份文档 |
| L5(部分) | hygiene 增加产物跟踪检查（随 M3） | `check_repo_hygiene.ps1` |
| L6 | IMAP append/select 对含空格/引号的邮箱名按协议加引号 | `imap_drafts.py`；测试 ×1 |

### 第二轮（遗留待办处理，2026-06-11）

验证基线：**60 tests OK (2 skipped) · compileall OK · hygiene 通过 · EXE 启动烟测通过**。

| 项 | 修复内容 | 主要变更 |
|----|---------|---------|
| L1 | 发送/草稿循环增加会话级熔断：SMTP 断连/连接超时/SSL 错误（IMAP 同理 abort）时中止剩余任务并标记 `send_skipped`/`draft_skipped`（不再逐条失败+逐条 sleep）；结果对话框与运行历史显示跳过数；跳过任务在表格中标为失败可重试 | `task_delivery.py`、`main_delivery.py`、`dialogs.py`；测试 ×2 |
| L5(余项) | 新增 `scripts/smoke_exe.ps1`（offscreen 启动打包 EXE，验证 15s 存活 + 工作目录初始化）并接入 CI；新增 `scripts/scan_xlsx_sensitive.py`，hygiene 脚本对跟踪的 xlsx 做敏感内容扫描（模式从正则派生，避免脚本自含可命中字面量） | `ci.yml`、`check_repo_hygiene.ps1`、2 个脚本 |
| M3(历史) | `git filter-repo` 清除历史中的 `release/`（48MB EXE ×2）与 `packages/`（含真实收件邮箱与预算正文的 78 个文件，上轮审计 High 项的历史残留）；删除 3 个残留 agent 分支；gc 后 force push | git 历史重写 |

仍未处理（有意保留）：I1 动态属性代理与 I3 lint/typecheck 配置（结构性改造，建议单独立项）、I2 `.claude/worktrees` 本地残留（不入 Git）。
