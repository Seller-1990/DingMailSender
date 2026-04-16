# 任务包操作说明

## 目录说明

- `tasks.xlsx`：一行一封邮件任务
- `content/`：Markdown 正文文件
- `assets/`：正文图片素材
- `attachments/`：附件文件

## 推荐填写方式

- `收件人` / `抄送人`：多个邮箱用分号分隔
- `Markdown路径`：优先填写相对任务包目录的路径，例如 `content/示例正文.md`
- `附件路径`：多个附件路径用分号分隔，例如 `attachments/a.pdf; attachments/b.pdf`
- `开头/补充内容`：支持换行，会拼接到 Markdown 正文前面
- `定时发送时间`：格式建议为 `2026-03-18 20:30:00`

## 正文图片

- 正文图片请在 Markdown 中按相对路径引用
- 程序发送时会自动转为 CID 内联图片
