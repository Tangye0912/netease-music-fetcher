# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v3.7.0)

> v3.4 起移除脚本模式（CLI），所有后续工作聚焦 TUI 体验。
> v3.5 交付后台任务队列，v3.6 交付队列持久化与任务页实时化，v3.6.1 为修复版本。
> v3.7.0 交付增量下载策略与 M4A/FLAC 封面嵌入，并修复 v3.6.1 代码审查发现的 27 项问题（详见 CHANGELOG 与 `CODE_REVIEW.md`）。

### 有意保留（审查结论，暂不修改）

> 完整理由见 `CODE_REVIEW.md` 的「明确未改」一节；这里只保留需要跟踪的结论。

- [ ] `cancel()`/`cancel_all()` 仍在队列锁内写历史：`poll()` 这条热路径已不持锁写盘，彻底移出需要重构 `cancel_all`/`close` 的锁边界，收益小、风险高。
- [ ] 同一 stem 的不同格式共用 `.lrc`：会话内由队列的 stem 预留规避，跨会话冲突概率极低；改名（如 `song.mp3.lrc`）会影响用户可见文件名，故保留。

### TUI Experience

- [ ] 分组视图的批次信息跨重启保留（当前 `_batches` 仅存在于本次运行）。
- [ ] Windows（含 GBK 控制台）与 SSH 真机冒烟：任务页 live_ask 渲染、bottom_toolbar、明暗主题、登录恢复与下载任务控制（v3.5/v3.6 遗留验收项）。冻结包启动与主菜单渲染已在 v3.6.1 的 Windows 构建上本地验证（无缺失导入、版本号正确），其余交互项仍待人工验证。
- [ ] 「我喜欢的音乐」直达需真机确认：代码假设网易云把该歌单挂在账号自己的 ID 下（`playlist?id=<uid>`），离线无法验证；若接口不是这样，改一行 URL 即可。同一轮真机确认还应覆盖：超过 1000 首时不会被 `trackIds` 分页静默截断（`fetch_playlist_song_ids` 在"下一页返回同一批 ID"时会停止）；以及鉴权下播放地址接口确实返回非 0 的 `size`（它决定批量识别能否省掉每首歌那次 CDN HEAD 探测——匿名请求实测为 0，拿不到时已回退探测，不会变慢）。

### v4.0 — Fullscreen Experiment（待定）

> 2026-09 评估结论：`tui-fullscreen-rewrite`（`4dbb214`，基点 `41ec0df`）整体复活约需 5-10
> 人天——8 个测试文件需重写/合并、3 项功能缺失、两套 `download_queue` API 不兼容、
> 且分支自带 `.part` 清理回归。已摘取其 `stage_callback` 思路与 `tests/test_pipeline.py`
> 的关键用例（阶段顺序、stage_callback 异常吞掉、取消保留既有目标文件）进入主线（v3.6.0）。分支继续存档；仅当菜单版 TUI 的形态确实无法满足需求时，
> 才按"分支修绿 → 功能对齐 → 三平台真机冒烟"的流程重启，否则维持存档。

- [ ] （重启前必做）重新评估：菜单版任务中心是否已覆盖全屏版的核心价值。

### Quality and Architecture

- [ ] 将 `batch_results.BatchResultRow` Protocol 收敛为明确的数据类，减少跨模块隐式约定。
- [ ] 检测前批量预取歌曲元数据：`/api/song/detail` 支持一次传多个 id（实测 30 个 id 一次请求 0.16s，逐首则 83ms/次，约 6 倍），千首歌单还能再少一个数量级的请求。
- [ ] 合并重复的搜索实现：`search_songs` 与 `search_playlists` 仅 `type` 与行解析不同，约 25 行需要同步维护。
- [ ] 合并两处分页逻辑：`_paginated_pick`（0 返回、非法输入重问）与 `_show_batch_rows`（除 n/p 外一律继续）语义不同，各自需要单独维护。
- [ ] 维持 95%+ 覆盖率（当前 95.2%，CI 门槛已提到 94%）；剩余缺口集中在 `audio.py` 的转码/ffmpeg 错误路径（89%）、`tui.py` 的 `main()` 启动装配（95%）与 `browser_login.py` 的 CDP 异常分支（79%）——都需要真实终端/浏览器或外部工具的错误注入。
- [ ] 在 Windows Terminal、macOS Terminal 和常见 Linux 终端验证明暗主题、中文对齐与键盘交互。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 UPX 与依赖裁剪对三平台单文件体积和启动速度的影响。
