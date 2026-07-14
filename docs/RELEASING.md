# DingMailSender 发布与回滚手册

## 1. 版本规则

- 唯一版本来源：`src/dingmail/__init__.py` 中的 `__version__`。
- 版本格式：语义化版本 `MAJOR.MINOR.PATCH`，预发布版本可使用 `-rc.1` 等后缀。
- Git Tag 必须为 `v<version>`，例如版本 `0.2.0` 对应 Tag `v0.2.0`。
- 已推送的 Tag 不移动、不覆盖；发布修复使用新的补丁版本。

## 2. 发布资产

正式 Release 固定包含：

```text
DingMailSender-v0.2.0-windows-x64.exe
DingMailSender-v0.2.0-windows-x64.exe.sha256
```

校验和文件格式为 `<sha256>  <filename>`。GitHub Actions 会验证文件存在、非空、文件名一致且哈希匹配，并执行离屏启动 smoke。

## 3. 发布流程

1. 在 `src/dingmail/__init__.py` 更新 `__version__`。
2. 把本版用户可见变化写入 `CHANGELOG.md`，将 `Unreleased` 内容归档到对应版本和日期。
3. 执行本地发布前检查：

```powershell
py -3.12 -m unittest discover -s tests -v
uvx ruff check .
py -3.12 -m compileall -q src dingmail_gui.py tests
.\scripts\check_repo_hygiene.ps1
.\scripts\verify_release_version.ps1
git diff --check
```

4. 可选地在本地生成正式命名的候选包：

```powershell
.\scripts\build_release.ps1 -Tag v0.2.0
```

5. 将版本提交合并到 `main` 后创建并推送带注释 Tag：

```powershell
git tag -a v0.2.0 -m "DingMailSender v0.2.0"
git push origin v0.2.0
```

6. `.github/workflows/release.yml` 会检出该 Tag，重新执行静态检查、单元测试、编译、构建、产物审计和启动 smoke，然后创建 GitHub Release。
7. 下载 Release 中的 EXE 和 SHA256 文件，在目标 Windows 机器上复核哈希后再替换现用版本。

## 4. 手动重跑

Release 工作流支持 `workflow_dispatch`，但输入必须是已存在的 Tag。手动重跑不会绕过 Tag 与 `__version__` 一致性检查。

## 5. 回滚规则

### 尚未推送 Tag

修正代码和版本提交后重新创建 Tag；未推送的本地错误 Tag 可以删除后重建。

### 已推送 Tag 或已生成 Release

- 不移动旧 Tag，不用新代码覆盖旧版本资产。
- 若版本不可用，在 GitHub 将该 Release 标记为预发布或删除 Release 资产，保留 Tag 作为审计记录。
- 从最后一个可用版本分支修复，递增 `PATCH`，重新走完整发布流程。
- 客户端回滚时恢复上一版 EXE，并用对应 `.sha256` 复核文件完整性。

### 数据兼容

发布前确认任务包格式、连接配置格式和运行目录格式是否变化。若未来引入不可逆迁移，必须在变更版本中提供独立迁移与备份说明，不能只依赖替换 EXE 回滚。
