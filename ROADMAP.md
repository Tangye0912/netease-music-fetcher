# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v3.6.1)

> v3.4 起移除脚本模式（CLI），所有后续工作聚焦 TUI 体验。
> v3.5 交付后台任务队列，v3.6 交付队列持久化与任务页实时化，v3.6.1 为修复版本（均详见 CHANGELOG）。

### Known Issues（v3.6.1 代码审查遗留，尚未修复）

- [ ] `download_queue.poll()` 全程持锁做磁盘 I/O（写下载历史与 `queue.json`），历史接近 1000 条时会阻塞 UI 刷新。计划：把两次落盘移出锁。
- [ ] TUI 分页逻辑在搜索、歌单、历史、任务四个页面各写一遍，且已存在的 `_pick_from_rows` 无人使用。计划：抽公共 `_paginated_pick`，预计净删 100–130 行。
- [ ] 关键路径缺测试：`pipeline.py` 的取消检查与 ffmpeg 缺失回退、`audio.py` 的暂停等待循环与歌词写盘、`tui.py` 的代理配置失败与任务详情控制路径。
- [ ] 无控制台环境（stdin 被管道或重定向）启动冻结包时，菜单能正常以纯文本渲染，但读取输入会抛出 `prompt_toolkit...NoConsoleScreenBufferError` 的原始 traceback 并以 1 退出（v3.6.1 Windows 构建本地实测）。计划：捕获该异常并给出中文提示。

### TUI Experience

- [ ] 我喜欢的音乐：主菜单直达"喜欢列表"批量下载（新增 likelist API）。
- [ ] 歌单搜索：按关键词搜索歌单并整单下载。
- [ ] 大歌单曲目明细分页，避免一次渲染过长列表。
- [ ] 分组视图的批次信息跨重启保留（当前 `_batches` 仅存在于本次运行）。
- [ ] Windows（含 GBK 控制台）与 SSH 真机冒烟：任务页 live_ask 渲染、bottom_toolbar、明暗主题、登录恢复与下载任务控制（v3.5/v3.6 遗留验收项）。冻结包启动与主菜单渲染已在 v3.6.1 的 Windows 构建上本地验证（无缺失导入、版本号正确），其余交互项仍待人工验证。

### v3.7 — Download Efficiency and API Evolution

- [ ] 增量下载：下载前识别已有文件，并提供跳过、覆盖或重命名策略（v3.6 的队列恢复已落地"文件已存在即视为完成"判定，可复用）。
- [ ] 将可播放地址请求逐步迁移到 `eapi.py` 加密传输，并保留可回退的兼容路径（CHANGELOG v3.3.0 起的既定方向）。
- [ ] 为 M4A/FLAC 补齐封面嵌入，统一 MP3/M4A/FLAC 的元数据能力。

### v4.0 — Fullscreen Experiment（待定）

> 2026-09 评估结论：`tui-fullscreen-rewrite`（`4dbb214`，基点 `41ec0df`）整体复活约需 5-10
> 人天——8 个测试文件需重写/合并、3 项功能缺失、两套 `download_queue` API 不兼容、
> 且分支自带 `.part` 清理回归。已摘取其 `stage_callback` 思路与 `tests/test_pipeline.py`
> 的关键用例（阶段顺序、stage_callback 异常吞掉、取消保留既有目标文件）进入主线（v3.6.0）。分支继续存档；仅当菜单版 TUI 的形态确实无法满足需求时，
> 才按"分支修绿 → 功能对齐 → 三平台真机冒烟"的流程重启，否则维持存档。

- [ ] （重启前必做）重新评估：菜单版任务中心是否已覆盖全屏版的核心价值。

### Quality and Architecture

- [ ] 将 `batch_results.BatchResultRow` Protocol 收敛为明确的数据类，减少跨模块隐式约定。
- [ ] 逐步把覆盖率从 75% 门槛提升到 95%，优先覆盖 TUI 路由和错误恢复分支。
- [ ] 在 Windows Terminal、macOS Terminal 和常见 Linux 终端验证明暗主题、中文对齐与键盘交互。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 UPX 与依赖裁剪对三平台单文件体积和启动速度的影响。
