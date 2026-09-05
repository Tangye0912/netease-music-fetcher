# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v3.4.0)

### v3.5.0 — Download Efficiency and API Evolution

- [ ] 增量下载：下载前识别已有文件，并提供跳过、覆盖或重命名策略。
- [ ] 将可播放地址请求逐步迁移到 `eapi.py` 加密传输，并保留可回退的兼容路径。
- [ ] 为 M4A/FLAC 补齐封面嵌入，统一 MP3/M4A/FLAC 的元数据能力。
- [ ] 将试听入口扩展到批量识别结果与“我的歌单”流程。

### Quality and Architecture

- [ ] 将 `batch_results.BatchResultRow` Protocol 收敛为明确的数据类，减少跨模块隐式约定。
- [ ] 逐步把覆盖率从 75% 提升到 95%，优先覆盖 TUI 路由和错误恢复分支。
- [ ] 在 Windows Terminal、macOS Terminal 和常见 Linux 终端验证明暗主题、中文对齐与键盘交互。
- [ ] 为大歌单的曲目明细增加分页或虚拟化，避免一次渲染过长列表。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 UPX 与依赖裁剪对三平台单文件体积和启动速度的影响。
