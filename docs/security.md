# DingMailSender 安全说明

## 授权码与 DPAPI

DingMailSender 的连接配置由 `src/dingmail/connection_profile.py` 统一读写。Windows 环境保存授权码时使用 DPAPI 绑定当前 Windows 用户加密，降低配置文件被复制后直接泄露的风险。

- 加密作用域：当前 Windows 用户。
- 迁移策略：旧版明文授权码在加载/保存连接配置流程中迁移为 DPAPI 密文；迁移成功后会删除旧位置的明文配置文件，避免明文授权码残留在磁盘上（删除失败不阻断启动，下次启动重试）。
- 失败策略：DPAPI 不可用或解密失败时向 GUI 返回明确错误/警告，不静默回退为明文。
- 运维建议：发布包、日志和示例配置中不得包含真实邮箱授权码。

## 发布审计

发布链路要求同时产出：

- `release/DingMailSender.exe`
- `release/DingMailSender.exe.sha256`

`build_exe.ps1` 负责生成 SHA256；`scripts/audit_release.ps1` 负责复算哈希并检查校验文件格式、文件名和产物非空。CI 会在上传 artifact 前执行该审计脚本。
