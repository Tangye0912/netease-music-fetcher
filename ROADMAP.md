# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v1.12.0)

### Type Safety and Tests

- [ ] 为 `MainWindow` 的检测、批量路由、设置切换和下载结果流程补行为级测试。
- [ ] 收紧 `music_fetch/__init__.py` 的公开 API，并用更明确的结构类型替换 `BatchResultRow` Protocol。
- [ ] 重新测量覆盖率并逐步提升到 95% 以上，避免仅依赖测试数量判断质量。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 PyInstaller WebEngine 资源裁剪，降低当前 onefile 产物体积，同时保持扫码登录可用。
