# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v3.0.0)

### Release Readiness

- [ ] 用真实账号完成一次“终端扫码登录 → 单曲下载 → 歌单批量多选下载”冒烟（登录 803 成功路径需要真人扫码，暂未自动化）。
- [ ] 在 Windows Terminal / cmd 与常见 Linux 终端上验证 ASCII 二维码渲染与键盘交互。

### Type Safety and Tests

- [ ] 用更明确的结构类型替换 `batch_results.BatchResultRow` Protocol。
- [ ] 重新测量覆盖率并逐步提升到 95% 以上，避免仅依赖测试数量判断质量。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 为 TUI 单文件产物评估 UPX 与裁剪（当前约 13MB，可继续观察）。
