# 钉钉邮箱批量发信（DingMail Bulk Sender）

当前版本已切换到“任务包 + 任务表 + Zen GUI”桌面工作台。

## 核心约束

- 首次使用需维护：发件邮箱 + SMTP 授权码（仅发件邮箱会写入本地 `conn_profile.json`）
- SMTP 服务固定为：`smtp.qiye.aliyun.com:465`（`SSL`）
- **本项目所有文件**仅允许位于：
  `D:\OneDrive - PowerBI学谦\工作\AI分析\工具软件\钉钉邮件发送\`

## 当前目录

- `src\`：源码
- `campaigns\`：旧版活动目录/示例
- `packages\`：新版任务包目录
- `runs\`：运行产物
- `release\`：EXE 打包产物

## 当前状态

- 新版 GUI 已接入：
  - 顶部 SMTP 连接卡片
  - 任务包模板下载 / 导入
  - 一行一封的任务表
  - 软件内轻量编辑
  - 单行预览弹窗
  - 保存到草稿箱（IMAP）
  - 托盘定时发送
- 设计说明：`产品设计草案.md`
- 操作手册：`操作说明_GUI版.md`

## 本地运行

- GUI 启动：`.\run_gui.ps1`
- EXE 打包：`.\build_exe.ps1`
- EXE 产物：`.\release\DingMailSender.exe`
