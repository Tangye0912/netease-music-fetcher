# 代码审查报告 — music-fetch v3.6.1

- **被审代码**：`HEAD 0a15f8b`（v3.6.1，工作区干净）
- **审查方式**：全量精读 + 4 个模块级对抗式审查（api/network、TUI、下载流水线、存储与批处理）+ 静态工具（`mypy --strict` 干净、`ruff` 干净）+ 每条结论都写了复现脚本（脚本位于 `/tmp/rev/`、`/tmp/mfrev/`，未修改仓库任何文件）
- **审查基线**：`.venv/bin/python -m pytest -q` → **584 passed, 14 subtests passed**
- **修复状态（2026-09-26 第二轮）**：下表 27 条**全部已修复**（含 §27 的改进型缓解）。修复后：**755 passed + 32 subtests**、覆盖率 **85.63%**、`mypy --strict` / `ruff` 干净。逐条修复说明见文末[修复记录](#修复记录)，修复后的行为断言已并入测试套件。
- **说明**：报告中 **✅ 已复现** = 我在本机独立复现过；**🔍 代码可证** = 逐行确认，未跑脚本（原因注明）。

| # | 严重度 | 问题 | 位置 | 证据 | 状态 |
|---|---|---|---|---|---|
| 1 | 高 | 粘贴网易云分享文案（短链）导致整个 TUI 崩溃 | `api.py:214-219`, `batch_inputs.py:109-115` | ✅ 已复现 | ✅ 已修复 |
| 2 | 高 | 响应体被截断却记为“下载成功”（无 Content-Length 校验） | `audio.py:443-461` | ✅ 已复现（真实 HTTP 服务） | ✅ 已修复 |
| 3 | 高 | 非 403 的 HTTP 状态中断候选与 outer-url 回退 | `audio.py:245-250` | ✅ 已复现 | ✅ 已修复 |
| 4 | 高 | 恢复队列时把任何非空文件当作下载完成（假成功） | `download_queue.py:475-483` | ✅ 已复现 | ✅ 已修复 |
| 5 | 高 | SOCKS5 传输不解压 gzip → 所有 API 调用失败 | `network.py:144-147` | ✅ 已复现（机制） | ✅ 已修复 |
| 6 | 高 | 批量识别“扩展阶段”异常逃逸 → 整程序崩溃 | `batch_inspect.py:56-86` | ✅ 已复现 | ✅ 已修复 |
| 7 | 高 | `downloads.json` 非原子写且不隔离 → 历史全丢 | `app_stores.py:253, 205-216` | ✅ 已复现 | ✅ 已修复 |
| 8 | 中 | 「覆盖」策略实际退化为“自动重命名” | `download_queue.py:206-211` | ✅ 已复现 | ✅ 已修复 |
| 9 | 中 | 取消可能删除用户已存在的文件（净数据丢失） | `pipeline.py:145-163` | ✅ 已复现 | ✅ 已修复 |
| 10 | 中 | API 读响应体异常逃逸：不重试/报“未知错误”/崩溃/卡死 | `api.py:311-324` | ✅ 已复现 | ✅ 已修复 |
| 11 | 中 | 并发数设成 4–8 会被静默改回 3 | `app_stores.py:174-175` | ✅ 已复现 | ✅ 已修复 |
| 12 | 中 | `format_panel` 截断算在一份、打印另一份 → 面板溢出 | `tui_utils.py:362-369` | ✅ 已复现 | ✅ 已修复 |
| 13 | 中 | `_truncate_to_width` 对 VS16/emoji 计宽错误 → 表格溢出 | `tui_utils.py:466-485` | ✅ 已复现 | ✅ 已修复 |
| 14 | 中 | 歌单接口把鉴权失败当网络错误/空列表 | `api.py:719-721, 736-740` | 🔍 代码可证 | ✅ 已修复 |
| 15 | 中 | 会话文件为非对象 JSON 时启动即崩 | `app_stores.py:103-123` | ✅ 已复现 | ✅ 已修复 |
| 16 | 中 | 多选按 label 反查索引 → 同名歌曲误选/无法区分 | `tui_utils.py:447-463` | ✅ 已复现 | ✅ 已修复 |
| 17 | 低 | `raw.isdigit()` + `int()` → 输入 `²` 或超长数字崩溃 | `tui_utils.py:340-343` 等 | ✅ 已复现 | ✅ 已修复 |
| 18 | 低 | 多选提示“回车确定”是错的（Enter 为切换） | `tui.py:763` | ✅ 已复现 | ✅ 已修复 |
| 19 | 低 | 登录 CDP socket 断开后忙转（满核 CPU） | `browser_login.py:254-260` | 🔍 代码可证 | ✅ 已修复 |
| 20 | 低 | 前台历史/会话写入未做异常保护 → OSError 崩溃 | `tui.py:1185-1189` 等 | 🔍 代码可证 | ✅ 已修复 |
| 21 | 低 | JSON `1e999` → `OverflowError` | `app_stores.py:178-182` | ✅ 已复现 | ✅ 已修复 |
| 22 | 低 | 来源格式未知 + 无 ffmpeg → 已下载内容被丢弃 | `audio.py:151, 184` | 🔍 代码可证 | ✅ 已修复 |
| 23 | 低 | 封面下载无大小上限；未知图片格式兜底标为 JPEG | `pipeline.py:235-252` | 🔍 代码可证 | ✅ 已修复 |
| 24 | 低 | `.part` 覆盖前无 `fsync`（掉电可能得到空洞文件） | `audio.py:443-460` | 🔍 代码可证 | ✅ 已修复 |
| 25 | 低 | 已“取消中”的任务再点取消无任何反馈 | `tui.py:1029`, `download_queue.py:248` | 🔍 代码可证 | ✅ 已修复 |
| 26 | 低 | 大小探测在 spinner 之外阻塞 UI（最长 2×timeout） | `tui.py:492` | 🔍 代码可证 | ✅ 已修复 |
| 27 | 低 | 多实例同时运行会互相覆盖下载历史 | `app_stores.py:201-268` | 🔍 代码可证 | ✅ 已缓解 |

---

## 高危（建议优先修）

### 1. 粘贴网易云官方分享文案（含短链 163cn.tv）直接崩溃

**位置**：`music_fetch/app_settings.py:56`（`URL_IN_TEXT_PATTERN = https?://[^\s]+`）、`music_fetch/api.py:214-219`（`extract_url_from_input`）、`music_fetch/batch_inputs.py:109-115`、`music_fetch/api.py:227-246`（`resolve_short_url`）

**原因**：正则 `[^\s]+` 不会在中文/全角字符处停下。网易云分享文案固定以 `（@网易云音乐）` 结尾，提取出的 URL 变成 `https://163cn.tv/3S7kCzr（@网易云音乐`（末尾全角右括号被 `TRAILING_URL_PUNCTUATION` 去掉，中间的 CJK 留在 URL 里）。短链分支会把它交给 urllib，`http.client.putrequest` 用 ASCII 编码请求行 → `UnicodeEncodeError`。该异常发生在**建立连接之前**，所以离线也会崩。

**复现**（`/tmp/rev`）：
```
$ .venv/bin/python -c "...A.SHORT_LINK_HOSTS={'127.0.0.1:1'}; A.parse_input_resource('分享单曲《夜曲》http://127.0.0.1:1/3S7kCzr（@网易云音乐）')"
parse_input_resource -> ESCAPED: UnicodeEncodeError | 'ascii' codec can't encode character '\uff08'
```
`_screen_single`（`tui.py:470-472`）与 `_batch_flow`（`tui.py:706`）都只捕获 `MusicFetchError`；`_run_menu` 只捕获 `KeyboardInterrupt`（`tui.py:340`），`main()` 只捕获 `KeyboardInterrupt/EOFError`（`tui.py:1590-1597`）→ 解释器级 traceback，直接退出。

**影响**：这是**最常见的一种输入**（手机端分享来的一律是短链）。粘贴即崩，且丢失已粘贴/已识别的批次内容。

**建议**：URL 正则限制为 ASCII URL 字符集，或在第一个 `ord(ch) > 127` 处截断；`extract_url_from_input` 返回前做 `url.isascii()` 断言；`resolve_short_url` 前先校验。上层同时把 `except MusicFetchError` 放宽为 `except (MusicFetchError, ValueError, UnicodeError)` 兜底。

### 2. 响应体被截断，却记为“下载成功”

**位置**：`music_fetch/audio.py:443-461`

**原因**：读循环 `chunk = resp.read(64*1024)`；`if not chunk: break`。TCP 连接中途 FIN 时 `read()` 返回 `b""` 而不是抛异常；`total_bytes`（来自 `Content-Length`，`audio.py:430-432`）只用于进度回调，**从不与 `downloaded` 比较**，于是 `.part` 被 `replace` 成最终文件、sidecar 被删除、上层记为 success。

**复现**（真实本地 HTTP 服务，声明 `Content-Length: 847` 只发 512 字节后关闭）：
```
exception raised   : None
final file size    : 512 (server claimed 847)
mutagen can parse  : NO -> MP4StreamInfoError not a MP4 file
```
`http.client` 对 Content-Length 不足**不会**抛 `IncompleteRead`（只在 chunked 时抛），所以这不是理论问题。

**影响**：网络抖动/被代理中断 → 用户拿到坏文件、历史记录“已完成”、sidecar 已删所以永远不会重下/续传。这是本次审查中最严重的数据完整性问题。

**建议**：EOF 后校验 `total_bytes is not None and downloaded < total_bytes` → 抛 `MusicFetchError(NETWORK_ERROR, ...)`（现有重试循环即可接管）；并且**保留** `.part` + sidecar 以便真正续传（见 §9 的删除策略）。

### 3. 非 403 的 HTTP 状态会中断整首下载（候选回退 + outer 回退全部跳过）

**位置**：`music_fetch/audio.py:245-250`（配合 `audio.py:483`、`251-268`）

**原因**：只有 “HTTP 403” 走 `continue`，其余状态（404/410/500/503/416…）直接 `raise`，于是后续候选与 outer-url 回退都不会执行。

**复现**：两个候选，第一个返回 404、第二个正常：
```
result: FAILED -> DOWNLOAD_FAILED Media request failed: HTTP 404.
candidates actually tried: ['https://m801.music.126.net/a.mp3']
outer-url fallback called: False
```
各候选是不同音质、不同的 CDN 对象，一个 404 不代表整首歌不可下载；`pipeline.py:119-127` 只对 `DOWNLOAD_FAILED/NETWORK_ERROR` 重试，但循环根本没机会继续。

**建议**：把“单个候选失败”统一视为可继续（`continue` 并记录最后一次错误），只在不可恢复错误（`CONVERT_TOOL_MISSING`、`PATH_TOO_LONG`…）时 `raise`。这与 v3.1.1 修 403 的思路一致。

### 4. 恢复队列时把“非空文件”一律当下载完成（假成功）

**位置**：`music_fetch/download_queue.py:475-483`

**原因**：`if target.exists() and target.stat().st_size > 0:` → 直接 `state="success"` + 写历史 + 从队列丢弃。既不比对大小，也不看持久化下来的 `state`。真实触发路径：退出时 `close()` 把运行中任务标为 `canceling` 并持久化（`download_queue.py:294-299`），而流水线在打标签/封面/歌词**之前**就已把 `.source` 改名成最终文件（`pipeline.py:146/160`），ffmpeg 也直接写最终路径（`audio.py:216`）——被强杀后留下的通常是非空残file。

**复现**：
```
case A restore_saved -> (0, 1)                      # 0 恢复, 1 "已完成"
case A history rows -> [('song', 180, 'success')]    # 180 字节的残file被记为成功
```
（现有测试只覆盖 0 字节的情况：`tests/test_download_queue.py:460`。）

**建议**：不要用“文件存在”推断成功。只有当持久化状态本身就是 `success`（或能以 Content-Length/解码校验确认完整）才记完成；否则按原路径重新入队（覆盖残file），或至少记为 `failed` 并提示“可能是未完成的文件”。

### 5. SOCKS5 传输返回未解压的 gzip，所有 JSON 接口失败

**位置**：`music_fetch/network.py:144-147`（根因），经 `network.py:178-186`（`stream=True`）与 `network.py:210-211`

**原因**：`_RequestsResponseAdapter.read()` 用 `self._response.raw.read(...)`。requests 在 `stream=True` 时以 `decode_content=False` 取流，`raw.read()` 返回**压缩字节**；而 `_open_with_socks` 用的请求头带默认 `Accept-Encoding: gzip, deflate`（urllib 直连发的是 `identity`，所以只有 SOCKS5 中招）。同函数 4xx 分支用的是已解码的 `response.content`（`network.py:192`），属遗漏。

**复现**（本地 gzip 服务 + 真实 adapter）：
```
requests default Accept-Encoding : gzip, deflate
adapter.read() first bytes : b'\x1f\x8b\x08\x00' (gzip magic 1f 8b 08)
_decode_json(...)          : MusicFetchError NETWORK_ERROR -> Unexpected API response (invalid JSON).
```
子审查还用真实 SOCKS5 代理验证了端到端失败，并实测 `music.163.com` 对 requests 默认头返回 `Content-Encoding: gzip`。

**影响**：配置 SOCKS5 的用户，登录校验、歌曲识别、搜索、歌单、下载全部报“网络请求失败（响应不是 JSON）”；`version_check.fetch_latest_project_version`（`version_check.py:58`）还会抛未捕获的 `UnicodeDecodeError`。

**建议**：`raw.read(size, decode_content=True)`（或改用 `response.content` / `iter_content`）；补一个“服务端 gzip → adapter 能解出 JSON”的单测（现有 socks 测试 mock 了 `raw.read`，测不出来）。

### 6. 批量识别的“扩展阶段”异常逃逸，整个 TUI 崩溃

**位置**：`music_fetch/batch_inspect.py:56-86`（第 77 行只 `except MusicFetchError`）对比 `_detect_one` 的 `except Exception`（`batch_inspect.py:159`）

**原因**：歌单/专辑/短链扩展走 `parse_input_resource`、`fetch_playlist_song_ids`、`fetch_album_songs`，它们内部可能抛出 `api.py:311-324` 未转换的 `ConnectionResetError`/`TimeoutError`/`IncompleteRead`/`UnicodeEncodeError`（含 §1 的短链 CJK）。同一函数里逐曲阶段有兜底，扩展阶段没有。

**复现**：
```
expansion error -> ESCAPED: ConnectionResetError connection reset by peer
detect-phase error -> survived, row status: failed
```
`_batch_flow` 只捕获 `MusicFetchError`（`tui.py:706`）→ `_run_menu`（`tui.py:340`）→ `main()`（`tui.py:1590-1597`）全都不接 → 整程序退出。

**建议**：扩展阶段同样 `except Exception`，落一条 `status="failed"` 行并记录日志（与逐曲阶段保持一致）。

### 7. `downloads.json` 非原子写 + 加载不隔离 → 下载历史整体丢失

**位置**：`music_fetch/app_stores.py:253`（`self.path.write_text(...)`），加载 `app_stores.py:205-216`；对比同文件已实现的原子私有写 `_write_private_json`（`app_stores.py:41-61`，用于 session/queue）

**原因**：每次完成一条记录都整file重写，无临时文件、无 `os.replace`、无 `fsync`；`load()` 解析失败只记 warning 就返回 `[]`，且不像 `QueueStore._quarantine`（`app_stores.py:321-332`）那样把坏文件挪走，于是下一次 `add()` 会用空列表重建文件。

**复现**：
```
rows on disk before crash: 3
load() after truncation -> []
rows on disk after one new add: 1 | contents: ['new']
quarantine backup created? ['downloads.json']     # 没有 .corrupt 备份
```
**建议**：改用 `_write_private_json`；`load()` 解析失败时按 `QueueStore` 的做法 `_quarantine()` 保留原始字节。

---

## 中危

### 8. 「覆盖」策略实际不生效（退化为自动重命名）

**位置**：`music_fetch/download_queue.py:206-211`，调用侧 `tui.py:1174-1195`（单曲）/ `tui.py:783-802`（批量）

**原因**：`resolve_output_path(policy="overwrite")` 故意返回规范目标（`audio.py:169-173` 的注释），但 `DownloadQueue.enqueue` 与策略无关地对**任何已存在**的目标名做 `_1` 改名，且 `DownloadRequest` 里根本没有 policy 字段。

**复现**：
```
requested path : /tmp/rev/overwrite/song-1.mp3
queued path    : /private/tmp/rev/overwrite/song-1_1.mp3
old file kept? : True 9
```
与 `CHANGELOG.md:8`「`覆盖`（重新下载并替换原文件）。单曲与批量流程都生效」直接矛盾；`tests/test_download_queue.py:108 test_existing_file_is_preserved` 把“存在就不覆盖”钉成了行为，两处需要一起改。副作用是**安全**的（旧文件不会被毁），但功能是坏的。

**建议**：把 policy 放进 `DownloadRequest`，仅在 `rename` 时分配新名；`overwrite` 保留规范路径（顺带注意 §9 的取消删除窗口）。

### 9. 取消可能删除用户已存在的文件

**位置**：`music_fetch/pipeline.py:145-149`（同格式分支）、`151-163`（无 ffmpeg 回退分支）

**原因**：先 `replace()` 覆盖目标，**之后**才检查取消；取消分支 `_cleanup_paths(output_path)` 删掉的正是刚覆盖上去的路径。唯一在改名之前做的检查是 `pipeline.py:139`。现有测试 `tests/test_pipeline.py:590` 用 `cancel_checker=lambda: True`，第一次调用（139 行）就命中，永远覆盖不到这个窗口。

**复现**：
```
cancel raised after 2 checks
pre-existing file exists now: False | bytes: None
directory: []            # 用户原有的 song.mp3 既没保留也没被替换
```
**建议**：记录“本次任务创建/覆盖了哪些路径”，取消时只删自己新建的；或把取消检查前移到 `replace()` 之前，改名用原子 `os.replace` 且保留原文件备份。

### 10. API 读响应体的异常逃逸：不重试 / 报“未知错误” / 崩溃 / 卡在“校验中…”

**位置**：`music_fetch/api.py:311-324`（`return status, resp.read()` 只被 `HTTPError/URLError` 包围）

**原因**：连接阶段超时被 urllib 包成 `URLError`，**读响应体**中途超时/重置抛的是裸 `TimeoutError`/`ConnectionResetError`（`OSError` 子类，不是 `URLError`）。`audio.py:501-511` 已经为媒体下载专门处理了这一点，API 层没有。

**复现**（三条链路都实测）：
1) 下载路径 —— `retry_count=2` 却只请求 1 次，错误码被兜底成未知：
```
state: failed | error_code: UNKNOWN_ERROR | message: timed out reading body
API requests made (retry_count=2 means 3 attempts expected if retried): 1
```
（`pipeline.py:119-127` 只接 `MusicFetchError`；异常一路到 `download_runner.py:224-234` 的 `except OSError` → `UNKNOWN_ERROR`，重试循环被绕过。）
2) 登录前台校验 —— `_accept_cookie`（`tui.py:420-424`）只捕获 `MusicFetchError` → 逃出 `main()` → traceback（子审查沿真实菜单链路复现）。
3) 后台登录校验 —— worker 线程异常死亡且不重置标志：
```
worker died, _login_checking = True | menu label = 校验中…
after drain, notices = [] -> stuck forever: True
```
（`tui.py:206-217` 没有 `finally`，`_login_checking` 永远为 True，`_drain_login_check` 永远早退。）

**建议**：`_perform_request` 增补 `except (OSError, http.client.HTTPException) as err: raise MusicFetchError(NETWORK_ERROR, ...)`；`_start_login_check` 的 worker 用 `try/finally` 复位 `_login_checking`。这一处能同时消掉三条症状。

### 11. 并发数超过 3 会被静默改回 3

**位置**：`music_fetch/app_stores.py:174-175`（`MAX_DOWNLOAD_CONCURRENCY=3`） vs `tui.py:1458`（设置界面提供 1..`MAX_UI_CONCURRENCY`=8）与 `download_queue.py:114`（队列吃 8）

**复现**：
```
saved concurrency 8 -> on disk: 3 | reloaded: 3
```
用户设 8 → 本次运行按 8 跑，重启后悄悄回到 3。

**建议**：会话存储改用 `MAX_UI_CONCURRENCY` 作为上限（或让设置界面只提供到 3）。

### 12. `format_panel` 的截断只用于算 padding，打印的是未截断原文

**位置**：`music_fetch/tui_utils.py:362-369`

**复现**（终端宽 40，ANSICode 剥离后测量）：
```
format_panel widths (ANSI stripped): [40, 61, 40]     # 中间一行 61 列，边框 40
```
任务详情面板每 0.5s 重绘（`U.live_ask`），长路径/长错误信息必然溢出；`…` 提示是死代码。

**建议**：截断后的 `text` 直接用于打印（现在只用于算宽度）。

### 13. `_truncate_to_width` 按单字符累计宽度，VS16/emoji 计宽错误

**位置**：`music_fetch/tui_utils.py:466-485`（调用点 `202/309/321/365/519`）

**复现**：
```
_truncate_to_width('❤️'*10, 10) -> display width: 20 (budget 10)
```
`wcswidth("❤️")==2`，但逐字符 `wcswidth("❤")+wcswidth("\ufe0f")==1`，于是预算被突破一倍（ZWJ 序列反向偏早）。表格/菜单/居中标题的边框随之错位。

**建议**：用“候选串整体 `wcswidth`”来判定，或按 grapheme cluster（`regex`/`grapheme` 库，或手写 VS16/ZWJ 合并）迭代。

### 14. 歌单接口把鉴权失败当“网络错误”甚至“空列表”

**位置**：`music_fetch/api.py:719-721`（账号信息非 200 → `NETWORK_ERROR`）、`736-740`（第一页非 200 → `return []`）

**🔍 代码可证**：与 `fetch_account_profile:348`、`fetch_playlist_song_ids:495-499`、`fetch_album_songs:559-563` 的 `AUTH_EXPIRED` 处理不一致；`tui.py:664` 会把 `[]` 显示成“暂无歌单。”。

**建议**：401/403 与 `code in (301,302,401,403)` 统一映射为 `AUTH_EXPIRED`，让 `_handle_auth_expired()` 生效。

### 15. 会话文件为非对象 JSON 时启动即崩

**位置**：`music_fetch/app_stores.py:103-123`（`raw.get(...)`，只捕获 `JSONDecodeError/OSError/UnicodeDecodeError`）

**复现**：
```
load('[]')    -> AttributeError: 'list' object has no attribute 'get'
load('null')  -> AttributeError: 'NoneType' ...
load('123')   -> AttributeError: 'int' ...
load('"x"')   -> AttributeError: 'str' ...
```
`TuiApp.__init__`（`tui.py:119`）在 `main()` 的 try **之前**执行（`tui.py:1589-1590`），所以是启动即死。同模块的 `DownloadHistoryStore.load:216` 和 `QueueStore.load:316-318` 都做了 shape 校验，这里是漏的。

### 16. 多选按 label 反查索引，同名歌曲无法区分

**位置**：`music_fetch/tui_utils.py:447-463`；label 构造 `tui.py:759-767`

**原因**：`values=[(label,label)]`、`[index for index,label in enumerate(labels) if label in selected]` — label 不是唯一键。prompt_toolkit 的 `CheckboxList` 本身就是按 value 记录勾选状态（`checked = value[0] in self.current_values`），重名行会被视作同一项。

**复现**（真实对话框语义）：
```
dialog values: ['夜曲（未知大小）', '夜曲（未知大小）', '晴天（未知大小）']
selected indices -> [0, 1]        # 只勾了第一行，却返回两行
```
触发条件现实存在：同批次里两首**同名**歌曲（翻唱/不同版本）且大小探测都失败（`probe_media_size_bytes` 失败即显示“未知大小”，走代理/弱网很常见）→ 勾一首下一首，或用户想只选一首却选不了。

**建议**：`values` 用 `(str(index), label)`，结果按下标返回。

---

## 低危 / 加固建议

17. **`raw.isdigit()` + `int(raw)` 未保护**（`tui_utils.py:340-343`，`tui.py:639-642/749/989-996/1289-1292`）：`'²'.isdigit()` 为 True、`int('²')` 抛 `ValueError`；超过 4300 位的数字串在 py≥3.11 同样抛错。已复现 `ValueError: invalid literal for int() with base 10: '²'`，逃出 `run()/main()` → traceback。改为 `try/except ValueError` 或 `raw.isascii() and raw.isdecimal()`。
18. **多选提示文案错误**（`tui.py:763`，`tui_utils.py:442-443` 的 docstring 同样错）：prompt_toolkit 把 `enter` 和 `space` **都**绑到切换（已核对 `_DialogList` 源码），只有 `Tab` 聚焦“确定”后再回车才提交。按提示操作会来回切换、最后 Esc 丢选择。
19. **登录 CDP socket 断开后忙转**（`browser_login.py:254-260`）：`except Exception: raw=""` 后直接 `continue`，无 `sleep`、无 `break`，坏 socket 期间满核空转（子审查实测 ~0.95s CPU / 1s）。加 `time.sleep(0.05)` + 连续失败即 `break`。
20. **前台历史/会话写入未保护**（`tui.py:1185-1189`、`1200`、`1409`、`1473`）：磁盘满/只读目录/`should_skip_existing` 与 `stat()` 之间的 TOCTOU 都会抛 `OSError` 直接崩；批量路径（`tui.py:803`）反而做了保护。建议统一包一层并复用 `queue.history_error` 那种“可恢复提示”。
21. **JSON 非有限数**（`app_stores.py:178-182/278-283`）：`1e999` 经 `json.loads` 成 `inf` → `int()` 抛 `OverflowError`（已复现）。`clamp`/`_safe_int` 增补 `OverflowError` 即可。
22. **来源格式未知 + 无 ffmpeg 时丢弃已下载内容**（`audio.py:151`、`184`）：`source_format="unknown"` 不在 `SUPPORTED_AUDIO_FORMATS`，跳过“直接另存”回退，转而调用 ffmpeg → `CONVERT_TOOL_MISSING`，`pipeline.py:182-184` 又把 `.source` 删了。建议未知格式时按候选给出的 `encode_type` 兜底后缀，或保留文件并只提示未转码。
23. **封面下载无大小上限、格式兜底为 JPEG**（`pipeline.py:235-252`）：`resp.read()` 全量入内存；`_detect_image_mime` 对 GIF/AVIF/BMP 返回 `image/jpeg`，M4A 会以 JPEG 格式写入非 JPEG 字节。建议限制字节数 + 未知格式跳过嵌入。
24. **`.part` → 最终名之前无 `fsync`**（`audio.py:443-460`，`.lrc` 亦然 `audio.py:582`）：与 `_write_private_json` 的做法（flush+fsync+replace）不一致，掉电可能留下长度不足的“成功”文件。
25. **“取消中”任务再取消无反馈**（`tui.py:1029-1032` + `download_queue.py:248`）：选项应隐藏或提示“正在取消中”。
26. **大小探测在 spinner 之外**（`tui.py:492`）：spinner 在 `484` 结束，`probe_media_size_bytes` 的 HEAD+Range GET 最多阻塞 2×timeout，界面无任何提示。
27. **多实例互相覆盖历史**（`app_stores.py:201-268`）：无单实例保护，A/B 交错写会丢记录（已在子审查脚本中复现）。

---

## 已检查并确认无问题的部分（避免重复投入）

- **分页数学**：`_paginated_pick`、`paginate_download_history` 的边界/空列表/单元素/越界钳制全部正确（3000 组随机宽度与边界用例）。
- **表格边框计算**：非 emoji 内容下 `format_table` 的行宽与边框一致（随机化测试）。
- **UI/队列线程安全**：跨线程读取都经锁保护的不可变快照，worker 不触碰任何界面对象，通知列表有互斥锁；mypy strict 干净。
- **CSV 公式注入**：`safe_csv_text` 覆盖 `= + - @` 前缀（导出历史/批次），`utf-8-sig` 落盘。
- **凭据泄漏**：日志不打印 cookie/token（`audio.py:420/476` 只打印 yes/no，`_url_for_log` 脱敏 token/authSecret）；诊断报告有 `redact_diagnostic_text`；session/queue 用 `_write_private_json`（0600 + 原子替换）。
- **TLS**：全仓库无 `verify=False`/`CERT_NONE`。
- **无头/异常终端**：`stdin=/dev/null`、空管道、`PYTHONIOENCODING=ascii`、`LC_ALL=C`、`TERM=dumb` 均 rc=0 无 traceback。
- **静态检查**：`mypy --strict` 干净；`ruff`（E/F/W）干净；584 个测试通过。

## 未确认 / 依赖时序的疑点（不作为结论）

- 退出时总打印“正在取消下载并清理临时文件，请稍候…”（`tui.py:251`）：子审查 5/5 触发，我单次实测 `queue.wait(0)` 返回 True（不打印）。属竞态，建议改成“有活跃任务才提示”。
- `tests/test_batch_inspect.py:150-165` 的专辑用例写在 `if __name__ == "__main__":` 且在 `unittest.main()` 之后，pytest 永远不收集（专辑分支零覆盖）——覆盖缺口，非 bug。
- `eapi.py` 无任何引用（死代码），其 docstring 声称的 QR 登录早已迁移到浏览器 CDP。
- `version_check.version_key` 对长度不等的版本元组比较会误判（`3.6` vs `3.6.0`）；当前 tag 都是三段，暂不触发。
- `format_duration` 收到非数值 `dt` 会抛 `TypeError`（`api.fetch_song_metadata` 未做类型兜底）；未能在真实响应中确认。
- 历史清空/删除与队列历史写入并发交错可能丢一行（按操作加锁，但顺序不定）。
- 设置里“界面主题”立即生效而取消项写“返回（不保存）”，语义待确认。
- 批量重试失败项后，旧任务在任务页显示为“单曲”而映射指向新任务（`tui.py:899-913/1064-1073`），标签与实际不一致。
- `safe_csv_text(0) == ""`（`csv_utils.py:18` 的 `value or ""`），当前调用方都传字符串，暂无实际影响。

---

## 建议的修复顺序

1. **§1 短链崩溃** + **§6 扩展阶段兜底** + **§10 API 异常收敛**：三处都属“异常逃逸到 main()”，一次性收敛后能同时消掉崩溃、卡死与不重试。
2. **§2 截断即成功**、**§4 恢复假成功**、**§7 历史非原子**：数据完整性问题，各配一个回归测试（本地截断服务、残file恢复、截断 JSON）。
3. **§3 候选回退**、**§8 覆盖策略**、**§9 取消删除**：逻辑/功能缺陷，注意 §8 与 §9 需一起改（修好覆盖后，取消删文件窗口会真正暴露给用户）。
4. **§5 SOCKS5 gzip**：一行修复 + 一个 gzip 单测。
5. **§11–§16**：设置回退、面板/表格宽度、歌单鉴权、会话 shape、多选索引。
6. 低危项按需清理，并补上 §2/§4/§6/§8/§9 的回归测试（当前测试套件在这些路径上全部是空白，这也是它们能进入 v3.6.1 的原因）。

---

## 修复记录

第二轮已按上表逐条修复。修复后：**755 passed + 32 subtests**（原 584）、覆盖率 **85.63%**（原 84.72%）、`mypy --strict` 与 `ruff` 干净。除下表说明外，每条修复都补了会失败的回归测试（先验证旧代码失败，再验证修复后通过）。

### 高危

| # | 修复内容 | 主要改动 | 回归测试 |
|---|---|---|---|
| 1 | URL 在首个非 ASCII 字符处截断；`resolve_short_url` 对非 ASCII 链接直接报 `INVALID_URL`；`main()` 增加兜底 | `app_settings.clean_extracted_url`、`api.extract_url_from_input`、`batch_inputs._extract_urls/_normalize_url`、`api.resolve_short_url`、`tui.main` | `test_app_settings.CleanExtractedUrlTests`、`test_api.ShareCopyCjkTests` |
| 2 | 读完响应体校验 `downloaded == Content-Length`，不足则保留 `.part`+sidecar 并在本次下载内用 `Range` 续传，最终按 `NETWORK_ERROR` 上报 | `audio._TruncatedBodyError`、`_download_audio_stream` | `test_audio.DownloadAudioStreamTests::test_truncated_body_resumes_*`、`test_all_truncated_attempts_*`、`TruncatedResponseIntegrationTests`（真实本地 HTTP 服务） |
| 3 | `DOWNLOAD_FAILED`/`NETWORK_ERROR` 视为单候选失败并继续；全部候选失败后仍走 outer-url 回退；只有不可恢复错误码立即抛出 | `audio.download_song_with_fallback` | `test_music_fetch_helpers.DownloadFallbackTests::test_dead_candidate_*`、`test_all_candidates_dead_*`、`test_network_error_on_candidate_*` |
| 4 | 只有能被 mutagen 解析的非空文件才算已完成；否则按原路径重新入队（`overwrite_existing=True` 替换残file，不再产生 `_1`） | `audio.is_plausible_complete_audio`、`download_queue.restore_saved` | `test_download_queue.test_restore_redownloads_a_truncated_leftover`、`test_restore_reenqueues_missing_and_records_existing`（改用真实音频 fixture）、`test_audio.PlausibleCompleteAudioTests` |
| 5 | adapter 读取改为 `decode_content=True`；4xx 分支的响应体读取用 `try/finally` 释放 session | `network._RequestsResponseAdapter.read`、`_open_with_socks` | `test_network.SocksResponseDecodingTests`（本地 gzip 服务 + 真实 adapter） |
| 6 | 扩展阶段（歌单/专辑/短链）增加 `except Exception`，落一条 `failed` 行并记日志 | `batch_inspect.run_batch_detect` | `test_batch_inspect.test_expansion_transport_error_becomes_failed_row`（顺带把从未被 pytest 收集的专辑用例移回类内） |
| 7 | 历史文件改用原子私有写（临时文件 + `fsync` + `replace`）；解析失败/非列表时移到 `downloads.json.corrupt` | `app_stores._quarantine_file`、`DownloadHistoryStore.load/save` | `test_app_stores.DownloadHistoryDurabilityTests` |

### 中危

| # | 修复内容 | 主要改动 | 回归测试 |
|---|---|---|---|
| 8 | 请求新增 `overwrite_existing`，覆盖策略下锁定原路径（仍避免与队列中其它请求撞名）；TUI 按策略传入 | `download_queue.DownloadRequest/enqueue`、`audio.should_replace_existing`、`tui` 三处入队点 | `test_download_queue.test_overwrite_request_targets_the_existing_path`、`test_overwrite_still_avoids_colliding_*`、`test_audio.ExistingTargetDecisionTests` |
| 9 | 只删除本次运行创建的文件；转码先写 `*.converting.<ext>` 再原子替换；改名前后各加一次取消检查 | `pipeline._cleanup_paths(keep=...)`、`run_download_pipeline` | `test_pipeline.PipelineFailurePathTests::test_cancel_after_the_move_keeps_a_preexisting_file`、`test_failed_conversion_leaves_a_preexisting_file_untouched`、`test_conversion_is_published_from_a_temporary_name` |
| 10 | `_perform_request` 把 `OSError`/`HTTPException`/`UnicodeError` 统一转成 `MusicFetchError(NETWORK_ERROR)`；登录校验线程用 `try/finally` 复位“校验中”；`main()` 兜底 | `api._perform_request`、`tui._start_login_check/main` | `test_api.PerformRequestBodyErrorTests`、`test_tui.test_unexpected_check_error_does_not_wedge_the_checking_state` |
| 11 | 会话存储的并发上限改用 `MAX_UI_CONCURRENCY` | `app_stores.SessionStore._safe_download_concurrency` | `test_app_stores.test_concurrency_above_the_ui_ceiling_*`、`test_download_settings_are_clamped_on_load`（断言同步更新） |
| 12 | padding 与实际打印的（截断后）文本一致 | `tui_utils.format_panel` | `test_tui_utils.PrintPanelTests::test_long_value_is_truncated_inside_the_border`、`test_short_values_are_not_truncated` |
| 13 | 按候选串整体宽度截断，正确处理 VS16/ZWJ 序列 | `tui_utils._truncate_to_width` | `test_tui_utils.TruncateWidthTests` |
| 14 | 账号信息与歌单分页的 401/403/301/302 映射为 `AUTH_EXPIRED`，第一页非 200 报 `NETWORK_ERROR` | `api.fetch_user_playlists` | `test_api.UserPlaylistFailureTests` |
| 15 | `load()` 增加 `isinstance(raw, dict)` 形状校验 | `app_stores.SessionStore.load` | `test_app_stores.SessionStoreRobustnessTests::test_wrong_json_shape_falls_back_to_defaults` |
| 16 | 对话框 value 改为行序号（而非文案），结果按序号解析并去重排序 | `tui_utils.multiselect` | `test_tui_utils.test_multiselect_uses_indexes_so_duplicate_labels_stay_separate`、`test_multiselect_ignores_unknown_and_duplicate_indexes` |

### 低危

| # | 修复内容 | 主要改动 | 回归测试 |
|---|---|---|---|
| 17 | 新增 `tui_utils.parse_index`（要求 ASCII 十进制，捕获 `ValueError`），替换 4 处 `isdigit()+int()` | `tui_utils.parse_index/menu`、`tui` 任务页/历史页/试听/分页 | `test_tui_utils.ParseIndexTests`、`test_non_decimal_digit_input_is_retried_not_raised` |
| 18 | 多选提示改为“空格勾选，Tab 切到「确定」后回车提交”；`input_multiline` 提示不再声称“直接回车返回” | `tui.py`、`tui_utils.input_multiline` | 与 #16 同一组用例（含 docstring 校正） |
| 19 | 关闭/异常 socket 立即 `break`，超时仍继续轮询；记录一条 warning | `browser_login._read_music_cookies` | `test_browser_login.CookieSocketLoopTests` |
| 20 | 新增 `TuiApp._save_session`，`_add_record`/清空历史/删除记录包 `OSError`；跳过分支的 `stat()` 加保护 | `tui.py` | `test_tui.GuardedWritesTests` |
| 21 | `clamp` 与两处 `_safe_int` 捕获 `OverflowError` | `app_settings.clamp`、`app_stores` | `test_app_stores.SessionStoreRobustnessTests`（`1e999`） |
| 22 | 新增 `audio.sniff_audio_format`（magic bytes），无 ffmpeg 时按 URL 后缀 → 文件头 → API `encode_type` 决定保留后缀 | `audio.sniff_audio_format`、`pipeline._source_format_to_keep` | `test_pipeline.test_missing_ffmpeg_without_url_extension_keeps_the_encode_type` |
| 23 | 封面下载限制 5MB；未知图片容器返回 `None`→跳过而不是标成 JPEG | `pipeline.MAX_COVER_BYTES/_detect_image_mime/_download_cover` | `test_pipeline.CoverArtTests::test_oversized_cover_is_rejected_and_skipped`、`test_unknown_cover_container_is_rejected`、`test_cover_error_never_fails_the_tag_write` |
| 24 | 发布前 `flush()` + `os.fsync()` | `audio._download_audio_stream` | `test_audio.test_fsync_runs_before_the_part_file_is_published` |
| 25 | `canceling` 状态不再提供“取消任务”选项 | `tui._task_action_options` | `test_tui.GuardedWritesTests::test_cancel_is_not_offered_while_already_canceling` |
| 26 | 大小探测包进独立 spinner | `tui._screen_single` | `test_tui.DownloadScreenProgressTests` |
| 27 | 缓解：`add()` 写入前清缓存并重新读盘，后写者不再用陈旧缓存覆盖其它实例的记录（仍非跨进程锁，属缓解） | `app_stores.DownloadHistoryStore.add` | `test_app_stores.test_appends_from_a_second_instance_are_not_dropped` |

### 顺带修复（原报告"未确认/低危"清单里可安全处理的项）

- `search_songs` 的 4xx/5xx/`code!=200` 不再伪装成"无结果"；`fetch_playable_candidates` 对非列表 `data`/非字典元素做类型防护；服务端 5xx 优先于"不可下载"结论；`detect_song` 的音质标签与探测 URL 现在指向同一个候选；`_safe_duration_ms` 兜底非数值时长。
- 歌单拉取加 200 页上限；`fetch_playable_candidates` 的 `_pick_highest_level` 复用新的 `_pick_best_candidate`。
- `version_check`：非 UTF-8 响应体不再抛 `UnicodeDecodeError`，新增 `is_newer_version` 解决 `3.6` vs `3.6.0` 误报。
- `csv_utils.safe_csv_text(0)` 不再返回空串；`menu([])` 立即报错而不是死循环，越界快捷键被忽略；预览文件扩展名过滤非法字符（防 API 返回值注入路径分隔符）；`.part` 失败清理策略与取消语义保持一致。
- 测试工程：`tests/test_batch_inspect.py` 里写在 `unittest.main()` 之后的专辑用例移回类内，现已执行。

### 明确未改（有意保留）

- **`cancel()`/`cancel_all()` 仍在队列锁内写历史**（原报告"未确认"项）：`poll()` 这条热路径已不持锁写盘，剩余的 `cancel` 调用点要彻底移出需要把 `cancel_all`/`close` 的锁边界一起重构；收益是极小的锁竞争，风险是改动队列这套已有充分测试的同步逻辑，故本轮不动。
- **`eapi.py` 死代码**：删除属于结构性清理（需同时删 `tests/test_eapi.py` 并评估对外部引用），不属于缺陷修复，保留现状并在报告里标注。
  - **2026-09-30 处置**：已按决策删除 `music_fetch/eapi.py`、`tests/test_eapi.py`、`pycryptodome` 依赖与 `music-fetch.spec` 的 `Crypto*` hiddenimports，并新增断言防止重新引入（见 CHANGELOG 的 Unreleased → Removed）。
- **同一 stem 不同格式共用 `.lrc`**：会话内由队列的 stem 预留避免，跨会话冲突概率极低，改变命名（如 `song.mp3.lrc`）会动到用户可见的文件名，保留现状。
