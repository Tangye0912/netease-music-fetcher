# music-fetch v3.4.0 规划

**版本主题：音质完整化 + 批量体验闭环 + 债务清偿。**
基于对 HEAD（255edc3 = v3.3.0 + `\r` 修复）的全量审查。已确认 v3.2/v3.3 已交付信息卡片、音质标签、搜索分页、试听、打开目录、更新缓存等，本计划不重复。

## 范围总览

| 分组 | 内容 | 优先级 |
| --- | --- | --- |
| A 新功能 | 无损/Hi-Res 档位；专辑下载；双语歌词 | P0/P1 |
| B UI 优化 | 批量汇总面板；明暗主题切换；我的歌单分页 | P0/P1 |
| C Bug | API 空值崩溃；标签写入炸掉下载；Windows 保留名；批量识别兜底；CLI 中文化；断点续传一致性 | P0 |
| D 技术债 | 死代码删除；CI 覆盖率；ROADMAP 重写 | P1 |
| E 发布 | 版本号/CHANGELOG/README/打标 | P0 |

新功能取舍（已定）：无损/Hi-Res（UI 标签已存在但 API 从不请求，性价比最高）、专辑下载（当前 `/album` 链接会被误当歌曲解析而失败，属资源类型缺口）、双语歌词（tlyric 已在返回中被丢弃，改动最小）。**增量下载（跳过已下载）与 eapi 接口加密化推迟到 3.5.0**，eapi.py 模块本身保留不动。

---

## A. 新功能

### A1. 无损/Hi-Res 音质档位（P0）
- `music_fetch/api.py:54`：`PLAYABLE_REQUEST_PROFILES` 追加 `("lossless", "flac")`、`("hires", "flac")`（放在 exhigh 之后，低档不可用时自然降级；`_LEVEL_RANK`/`_QUALITY_LABELS` 已有这两档，改动后标签真正可达）。
- 确认 `prioritize_candidates_by_format`（audio.py:185）对 `flac` 的推断与排序无需改动（URL `.flac` 后缀已支持）。
- VIP 无损不可用时该档返回空 url，现有 `saw_song_unavailable`/候选链逻辑自动兜底，不新增处理。
- 测试：profiles 常量、`_pick_highest_level` 含 lossless/hires、flac 优先排序、TUI 音质标签。

### A2. 专辑下载（P1）
- `api.py`：`_detect_resource_type`（:181）增加 `/album` 路径/fragment 识别 → 返回 `"album"`；`_extract_resource_id` 增加 `r"/album/(\d+)"` 模式；`parse_song_id` 对 album 报错（文案对齐 playlist 处理）。
- `api.py` 新增 `fetch_album_song_ids(album_id, cookie, timeout)`：GET `https://music.163.com/api/v1/album/{id}`，解析 `body["songs"][].id`，防御性解析（`isinstance` 检查，避免 C1 同类问题）。
- `batch_inspect.py`：`run_batch_detect` 展开分支增加 album → 逐曲进入批量流程，`source_label` 用 `专辑-《专辑名》`（接口返回 name）。
- `batch_inputs.py`：新增 `ALBUM_SHARE_WITH_URL_PATTERN`（"分享…的专辑《…》 URL"），纳入 hint 映射。
- `tui.py` `_screen_single`：输入解析为 album 时提示并路由到 `_batch_flow`（镜像歌单入口 tui.py:470 的做法）。
- 测试：URL 解析（`music.163.com/album?id=x`、`/album/x/`、带分享文案）、album 展开与去重、单曲入口路由。

### A3. 双语歌词（P1）
- `audio.py` 新增纯函数 `merge_bilingual_lyric(original, translation) -> str`：按时间戳配对，翻译行缀在对应原文行下方（标准双语 LRC），无翻译的时间轴保持原文，空翻译返回原文。
- `pipeline.py:178-184`：歌词下载增加模式参数 `lyric_mode: "off"|"original"|"translation"|"bilingual"`（默认 original，向后兼容）；bilingual 时用合并结果写 `.lrc` 与嵌入标签。
- `tui.py` 单曲下载处把"同时下载歌词？"升级为四选一菜单；批量保留是/否确认（=原文，若存在翻译自动合并双语）。
- `cli.py` 增加 `--lyric-mode`（默认随 `--lyric`）。
- 顺带修复：`embed_lyric_tag`（audio.py:433-441）的 `.wav` 分支移除（mutagen 对 wav 用 `FLAC()` 必抛 `FLACNoHeaderError`），仅保留 `.flac`。
- 测试：合并函数（时间戳对齐/错位/空翻译）、模式接线、wav 跳过。

---

## B. UI 表现优化

### B1. 批量下载汇总面板（P0）
- 现状：批量结束只打一行 `summary_text()`（tui.py `_run_batch_session` 末尾）。
- 改为复用 v3.2 的 `U.print_panel`（tui_utils.py:241）：标题"批量下载完成"，键值行 = 成功/失败/取消/输出目录 + 失败原因 top3（数据来自 `summarize_batch_rows().failure_reasons`，已在 batch_download.py:333 聚合），失败时提示"可在下载历史中重试"。

### B2. 明暗主题切换（P1）
- `tui_utils.py`：把现有散落的 `COLOR_*` 常量收拢为 `DARK_THEME`/`LIGHT_THEME` 两个语义角色映射字典（标题/正文/辅助/成功/失败/警告/状态条背景），模块级 `set_theme(name)` 切换活跃调色板；`print_header/print_status/print_table/menu/panel` 等全部改从活跃调色板取色。
- `TuiApp.__init__` 启动即应用 `session.ui_theme`（字段与校验已存在，app_stores.py:76/170，零迁移成本）；`_screen_settings` 增加"界面主题"项（choice 7 前插入，保存流程不变）。
- Light 主题原则：正文深灰、辅助中灰、状态条保留青色底、成功/失败用深绿/深红保证浅底可读。
- 测试：切换后取色变化、非法主题回退 dark、设置项往返持久化。

### B3. 我的歌单分页（P1）
- `api.py fetch_user_playlists`（:686）：offset 循环翻页（每页 100，上限 500 防失控），沿用 `fetch_playlist_song_ids` 的循环写法。
- `tui.py _screen_playlists`：镜像搜索分页交互（`n`/`p` 翻页、`0` 返回、"第 x/y 页"，模式见 tui.py:371-437）。
- 测试：API 多页聚合、TUI 分页冒烟。

---

## C. Bug 修复（全部已在当前 HEAD 核实）

1. **API 空值崩溃**：`api.py:661` `body.get("result", {})` 在 `{"result": null}` 时 AttributeError（搜索界面直接炸）；`api.py:765-766` `fetch_lyric` 同类。改为 `body.get("result") or {}` 风格 + `isinstance` 检查（对齐 api.py:441 既有写法）。全文件排查其余 `get(x, {}).get(y)` 链。
2. **标签写入炸掉已完成的下载**：`write_audio_tags` 调用点 `pipeline.py:168` 无兜底，mutagen `MutagenError`（不在 `(OSError, ValueError, KeyError, TypeError)` 捕获集，pipeline.py:271）会传出 → CLI 直接 traceback、TUI 把已成功落盘的文件标成下载失败。修复：调用点包 `try/except Exception`（仅 warning），内部捕获放宽为 `Exception`；歌词嵌入（audio.py:423/432/441）同步放宽。**原则：元数据失败永不影响下载结果。**
3. **Windows 保留文件名**：`sanitize_filename`（audio.py:54）增加控制字符过滤与保留名映射（`CON/PRN/AUX/NUL/COM1-9/LPT1-9` 大小写不敏感 → 前缀 `_`），跨平台统一应用。
4. **批量识别兜底**：`_detect_one`（batch_inspect.py:117）增加 `except Exception` → 该行置 failed（UNKNOWN_ERROR 文案），单行异常不再炸掉整个批量识别（UI 回调 tui.py:513 是现实触发源）。
5. **CLI 中英混杂**：`cli.py` 引入 `error_texts.user_error_message`（:197 现在直接打印英文 err.message，而 TUI/批量都走了中文映射）；ffmpeg 回退警告（:118/:183）、进度与结果文案中文化。**脚本可解析的键（`SUCCESS path=`、错误码前缀）保持英文不变**，只翻人类可读部分。
6. **断点续传一致性**：`.part` 续传只在崩溃路径可达（audio.py:277-281），但换媒体 URL 续传会拼接错位字节。新增 `.part.src` 旁车文件记录来源 URL：续传前校验，URL 不一致则从头重来；所有 .part 清理路径（audio.py 各异常分支、download_runner.py:222-226 finally）同步清理旁车。补 resume 测试（当前零覆盖）。

---

## D. 技术债 / 历史债

1. **死代码删除**（逐项先 grep 确认零生产引用再删）：`audio.download_audio`、`audio.invalidate_ffmpeg_cache`（no-op）、`download_tasks.next_task_snapshot` + 对应测试、`app_settings` 的 `DETECT_TIMEOUT_OPTIONS/DOWNLOAD_TIMEOUT_OPTIONS`；`__init__.py` 导出面收敛（`check_login_status`、`fetch_playable_url`、`parse_playlist_id`、`download_audio` 等零生产调用符号从 `__all__` 移除，函数体一并删除并清理其测试；`fetch_playable_url` 被 `detect_song` 内部使用的可能性需以 grep 为准，若在用则只收敛导出）。**eapi.py 按 CHANGELOG 承诺保留**，仅在 ROADMAP 标注去向。
2. **CI 增强**：dev 依赖 + `pytest-cov`、`ruff`；`build.yml` pytest 步骤加 `--cov=music_fetch --cov-fail-under=<当前值+3>`（先实测基线再定阈值，防回退）；ruff 用最小默认规则集（E/F/W，line-length 120）。
3. **ROADMAP.md 重写**：移除已失效的二维码冒烟项；更新 Backlog 为 3.5.0 方向——eapi 接口加密化（CHANGELOG v3.3.0 承诺）、增量下载/跳过已下载、m4a/flac 封面嵌入、macOS 签名公证、UPX 体积评估、BatchResultRow Protocol → dataclass、覆盖率 95% 目标。

## E. 发布工程

- 版本号：`pyproject.toml` 3.3.0→3.4.0、`app_settings.APP_VERSION` 同步。
- CHANGELOG.md 顶部新增 v3.4.0 节（沿用现有"功能/优化/修复"格式）。
- README.md 更新：音质档位说明（无损需 VIP）、专辑链接支持、歌词模式、主题设置、快捷键表补充。
- 打 tag `v3.4.0` → CI 三平台构建 + draft release（现有 build.yml 流程）。

---

## 执行顺序与验收

**M1 修复与清债**（C1-C6、D1、D2）→ **M2 新功能**（A1→A3→A2）→ **M3 UI**（B1→B2→B3）→ **M4 发布**（E、D3）。每项带单元测试随做随提。

验收标准：
- `pytest tests/ -q` 全绿（新增约 40-60 个用例）、`mypy --strict` 零错误、ruff 通过、覆盖率不低于设定阈值；
- 手动冒烟清单：官网扫码登录 → 单曲检测显示"无损/Hi-Res"标签并成功下载 flac → 专辑链接进批量流程 → 双语歌词合并输出 → 主题切换生效且重启保持 → 批量下载结束出现汇总面板 → 下载历史重试可用；
- 全程不推送，最终提交序列由你确认后推送。

**明确不做（推迟 3.5.0+）**：增量下载/跳过已下载、eapi 接口加密化、m4a/flac 封面嵌入、macOS 签名、UPX、歌单内大表分页、试听入口扩展到批量/歌单。