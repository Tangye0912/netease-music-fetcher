# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v3.8.0)

> v3.4 起移除脚本模式（CLI），所有后续工作聚焦 TUI 体验。
> v3.5 交付后台任务队列，v3.6 交付队列持久化与任务页实时化，v3.6.1 为修复版本。
> v3.7.0 交付增量下载策略与 M4A/FLAC 封面嵌入，并修复 v3.6.1 代码审查发现的 27 项问题（详见 CHANGELOG 与 `CODE_REVIEW.md`）。
> v3.8.0 交付「我喜欢的音乐」直达、歌单搜索、大歌单明细分页、批次结果跨重启保留与识别阶段取消，完成一轮独立审查并把覆盖率从 85.7% 提到 95.1%。

### 有意保留（审查结论，暂不修改）

> 完整理由见 `CODE_REVIEW.md` 的「明确未改」一节；这里只保留需要跟踪的结论。

- [ ] `cancel()`/`cancel_all()` 仍在队列锁内写历史：`poll()` 这条热路径已不持锁写盘，彻底移出需要重构 `cancel_all`/`close` 的锁边界，收益小、风险高。
- [ ] 同一 stem 的不同格式共用 `.lrc`：会话内由队列的 stem 预留规避，跨会话冲突概率极低；改名（如 `song.mp3.lrc`）会影响用户可见文件名，故保留。

### 真机验证（需要有账号的环境）

> 离线无法确认的假设已写成可执行检查，一条命令跑完：
> `MUSIC_FETCH_LIVE_COOKIE="MUSIC_U=…" python -m pytest tests/test_live_api.py -v`
> 不带该环境变量时这四条自动跳过，普通测试仍然禁止真实联网（守卫只对这**一个**模块放开，且必须同时设置该变量）。

- [ ] `test_liked_songs_are_reachable_under_the_account_id`：「我喜欢的音乐」是否真的挂在账号自己的 ID 下 → 失败则改 `_screen_liked` 的入口 URL（一行）。
- [ ] `test_paging_advances_when_the_playlist_exceeds_one_request`：喜欢列表超过 1000 首时 `trackIds` 的分页偏移是否推进 → 失败则 `fetch_playlist_song_ids` 需要换分页方式，否则会静默截断。
- [ ] `test_playable_candidates_and_reported_size`：鉴权下播放地址接口是否返回非 0 `size`（**只报告不判定**）→ 为 0 时批量识别回退 HEAD 探测，不会变慢，但省不掉那次请求。
- [ ] `test_quality_profile_ladder`：七个音质档案实际各返回什么 level → 决定能否"拿到最高音质就跳出循环"或改为并发发出（当前每首歌 9 次请求里有 7 次是它）。
- [ ] Windows（含 GBK 控制台）与 SSH 真机冒烟：任务页 live_ask 渲染、bottom_toolbar、明暗主题、登录恢复与下载任务控制（v3.5/v3.6 遗留验收项，仍需人工过一遍；冻结包启动与主菜单渲染已在 Windows 构建上验证）。
- [ ] 在 Windows Terminal、macOS Terminal 和常见 Linux 终端验证明暗主题、中文对齐与键盘交互。

### v4.0 — Fullscreen Experiment（待定）

> 2026-09 评估结论：`tui-fullscreen-rewrite`（`4dbb214`，基点 `41ec0df`）整体复活约需 5-10
> 人天——8 个测试文件需重写/合并、3 项功能缺失、两套 `download_queue` API 不兼容、
> 且分支自带 `.part` 清理回归。已摘取其 `stage_callback` 思路与 `tests/test_pipeline.py`
> 的关键用例（阶段顺序、stage_callback 异常吞掉、取消保留既有目标文件）进入主线（v3.6.0）。分支继续存档；仅当菜单版 TUI 的形态确实无法满足需求时，
> 才按"分支修绿 → 功能对齐 → 三平台真机冒烟"的流程重启，否则维持存档。

- [ ] （重启前必做）重新评估：菜单版任务中心是否已覆盖全屏版的核心价值。

### Quality and Architecture

- [ ] **单曲识别里最大的开销是音质档案循环**：`fetch_playable_candidates` 会为 7 个 `PLAYABLE_REQUEST_PROFILES` 各发一次请求且不提前退出（实测 300 首 → 2100 次请求），占每首歌 9 次请求中的 7 次。可考虑两条路：拿到 `hires` 候选即跳出（对能播放最高音质的账号安全等价），或把 7 次请求并发发出（请求总数不变、单曲延迟约降 4 倍）。**两条都需要先跑上面的 `test_quality_profile_ladder` 看真实回包**，故未动。
- [ ] 维持 95%+ 覆盖率（当前 95.1%，CI 门槛 94%）；剩余缺口集中在 `audio.py` 的转码/ffmpeg 错误路径（89%）、`tui.py` 的 `main()` 启动装配（95%）与 `browser_login.py` 的 CDP 异常分支（79%）——需要注入 ffmpeg 失败或假 CDP 连接。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 UPX 与依赖裁剪对三平台单文件体积和启动速度的影响。
