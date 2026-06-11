# DingMailSender

DingMailSender 是一款面向 Windows 桌面的本地企业邮箱批量发送工具，适合行政通知、周报汇报、活动邀约、客户跟进等“按任务包批量发信”场景。它以 `tasks.xlsx` 管理收件人与发送状态，以 Markdown 维护邮件正文，支持附件、正文图片 CID 转换、IMAP 草稿箱留存、托盘定时发送，并在 Windows 下使用 DPAPI 加密保存 SMTP 授权码。

项目定位：**本地运行、任务包驱动、可预览可追溯、适合企业邮箱批量草稿/发送流程的轻量桌面工具**。

当前版本提供：

- 任务包目录管理
- `tasks.xlsx` 一行一封邮件任务
- `Markdown` 正文 + 正文图片自动转 `CID`
- 附件发送
- IMAP 保存草稿箱
- 托盘常驻定时发送
- GUI 内轻量编辑与预览

## 适用场景

- 批量发送通知、汇报、周报、活动邮件
- 邮件正文希望以 `Markdown` 维护
- 需要“先存草稿再人工复核”流程
- 需要在本机托盘里等待定时发送

## 核心特性

- SMTP 连接成功后，会自动保存发件邮箱与授权码信息
- Windows 下 SMTP 授权码使用 DPAPI 加密保存
- 登录信息保存在用户配置目录 `%LOCALAPPDATA%\DingMailSender\conn_profile.json`；程序目录/工作目录中的旧版配置会在启动时自动迁移，迁移成功后旧明文文件会被删除
- `Markdown路径`、`附件路径` 仅允许引用当前任务包目录内的文件，避免误取包外文件
- `tasks.xlsx` 中缺失或重复的 `任务ID` 会在重新加载或保存时自动修复
- 软件内编辑 `tasks.xlsx` 时，只更新 `Tasks` 工作表，保留其他工作表；写入采用“临时文件 + 原子替换”，保存中断不会损坏原文件
- 每次发送 / 保存草稿都会生成唯一运行目录，避免同秒重复执行冲突
- 发送和草稿流程会输出运行日志与 `manifest.csv` 状态清单（收件人与错误信息已脱敏）；设置环境变量 `DINGMAIL_SAVE_DEBUG_ARTIFACTS=1` 时才会额外输出 `eml` 原文与 HTML 预览

## 快速开始

### 1. 运行 GUI

源码运行：

```powershell
.\run_gui.ps1
```

或直接运行打包后的：

```text
release\DingMailSender.exe
```

### 2. 连接 SMTP

当前默认发信配置为：

- SMTP 服务器：`smtp.qiye.aliyun.com`
- 端口：`465`
- 安全方式：`SSL`

首次使用时填写：

- 发件邮箱
- SMTP 授权码

连接成功后，下次启动会自动带出已保存的登录信息。

### 3. 下载或导入任务包

标准任务包目录结构：

```text
任务包目录/
  tasks.xlsx
  README_操作说明.md
  content/
    示例正文.md
  assets/
  attachments/
```

说明：

- `tasks.xlsx`：核心任务表
- `content/`：邮件正文 Markdown
- `assets/`：正文中引用的图片
- `attachments/`：邮件附件

### 4. 编辑并发送

典型流程：

1. 下载任务包模板
2. 在 `tasks.xlsx` 中维护任务
3. 重新加载任务包
4. 预览单封邮件
5. 选择“保存草稿”“立即发送”或“加入定时队列”

详细 GUI 说明见 [操作说明_GUI版.md](./操作说明_GUI版.md)。

## 输出目录

每次发送或保存草稿后，会在 `runs/` 下生成一份输出：

- `logs/`：运行日志
- `manifest.csv`：每封邮件的状态清单（收件人与错误信息已脱敏）
- `previews/`、`eml/`：默认为空；设置 `DINGMAIL_SAVE_DEBUG_ARTIFACTS=1` 后才写入 HTML 预览与邮件原文（含完整收件人与正文，注意保管）

## 本地目录

程序会在工作目录下维护这些内容：

- `packages/`：任务包
- `runs/`：运行输出

连接信息（发件邮箱与 DPAPI 加密的授权码）保存在用户配置目录 `%LOCALAPPDATA%\DingMailSender\conn_profile.json`，不随项目目录走。

打包版默认以 EXE 所在目录作为工作目录；若 EXE 所在目录或其上一级已存在 `packages/`，则沿用该目录。源码运行时默认以项目目录作为工作目录。也可以通过环境变量 `DINGMAIL_HOME` 指定。

## 开发与测试

安装依赖后可运行：

```powershell
python -m unittest discover -s tests
python -m compileall src dingmail_gui.py tests
```

当前已覆盖的重点回归：

- 任务包路径越界校验
- `tasks.xlsx` 多工作表保留
- 重复 / 缺失 `任务ID` 自动修复
- 预览不读取附件
- IMAP Drafts UTF-7 兼容
- 发送与存草稿节流/日志行为
- GUI 基础交互与托盘行为

## 打包

执行：

```powershell
.\build_exe.ps1
```

输出文件：

```text
release\DingMailSender.exe
```

## 仓库说明

- `src/`：源码
- `tests/`：自动化测试
- `build_exe.ps1`：PyInstaller 打包脚本
- `run_gui.ps1`：本地 GUI 启动脚本



## 安全与授权码存储

- Windows 下保存连接配置时，授权码优先使用 DPAPI 绑定当前 Windows 用户加密；配置文件迁移后不再保存明文授权码。
- GUI 启动加载旧版明文配置时会尝试自动迁移为当前用户 DPAPI 加密格式；若迁移失败，可在“连接设置”中测试成功后重新保存，并在界面查看配置来源与迁移提示。
- 非 Windows 或 DPAPI 不可用环境不会静默降级为明文保存；如需迁移，请在目标 Windows 用户下重新保存连接配置。
- 请勿将个人配置目录、运行日志、`runs/`、`release/` 产物中的敏感样例提交到仓库。

## 发布链路审计

CI 在 Windows 上执行单元测试、PyInstaller 打包、生成 SHA256，并通过 `scripts/audit_release.ps1` 校验发布产物存在、非空、校验和格式与实际哈希一致。
本地发布前可执行：

```powershell
.\build_exe.ps1
.\scripts\audit_release.ps1
```
