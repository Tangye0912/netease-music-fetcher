# music-fetch

网易云音乐单曲/歌单下载工具。v3.1 起登录采用**官网扫码（浏览器）**唯一方式，并加入登录门槛（未登录只显示登录/退出）。

## 1. 版本概览（v3.1.0）

### 1.1 v3.1.0 重大变更

- **官网扫码登录（浏览器，唯一方式）**：启动本机 Chrome/Edge 打开网易云官网登录页，扫码官网二维码后自动取回登录凭证；移除终端二维码登录与粘贴 Cookie。可绕开工具自身二维码被网易云风控标记的问题。
- **登录门槛**：未登录时主菜单只显示「登录 / 退出」，其余功能锁定；cookie 过期自动回到登录流程。
- **防风控优化**：登录接口轮询降频（2s→5s）；被 8821 拦截后强制 30 分钟冷却（跨重启生效）。
- **界面优化**：搜索结果/歌单改为 wcwidth 对齐的分列表格（中文全角正确对齐、表头高亮）；所有下载步骤提示"回车用默认 / 0 取消"；错误信息全中文（去掉英文错误码）；返回操作统一（输入框回车返回、列表 0 返回）。
- **新增依赖**：`websocket-client`（浏览器登录取 cookie 用）。

### 1.2 v3.0.0 重大变更

- **全面 TUI 化**：移除 PySide6 GUI（约 6000 行 Qt 代码与 WebEngine 依赖），所有交互都在终端完成。
- **终端扫码登录**：调用网易云 QR 登录接口，在终端渲染二维码（ASCII 方块），扫码后自动轮询登录状态并保存凭证。
- **键盘多选下载**：批量识别结果用勾选式列表选择（空格勾选、回车确认），下载中支持 `p` 暂停/继续、`r` 恢复、`c` 取消。
- **体积锐减**：单文件产物从约 185MB（含 WebEngine）降至约 13MB，跨平台打包与启动都更快。
- **保留脚本模式**：`music-fetch --url ...` 等参数化 CLI 原样保留（含 `--concurrency` 歌单并行下载）。

### 1.2 核心能力

- 登录：终端 ASCII 二维码扫码登录，自动保存凭证；不读取浏览器数据，也不需要提前登录网易云网页
- 单曲：链接/分享文案/歌曲 ID → 检测 → 目录/文件名/格式/歌词选项 → 进度条下载（p 暂停 c 取消）
- 搜索：按歌名/歌手名搜索并直接下载
- 我的歌单：登录后浏览歌单，选中即进入批量流程
- 批量：多行粘贴 → 并发识别（歌单自动展开、去重）→ 键盘多选 → 并发下载（p 全部暂停 / r 恢复 / c 取消）→ 失败项重试
- 歌词：下载 `.lrc` 并嵌入 MP3/M4A/FLAC 标签
- 下载历史：分页浏览、状态筛选、关键词搜索、失败重试、打开目录、删除、筛选结果 CSV 导出（防公式注入）
- 设置：下载目录、检测/下载超时、重试次数、并发上限、HTTP/SOCKS5 代理
- 诊断：API/CDN 连通性检测、脱敏日志、诊断报告导出；主菜单可检查新版本
- 格式：mp3/m4a/wav/flac/aac；未安装 ffmpeg 时自动回退保存源格式

## 2. 环境准备

建议 Python 3.10+。

```bash
python3 -m pip install -e ".[dev]"
```

如需格式转换（如 m4a → mp3/wav/flac）还需安装 ffmpeg：

```bash
# macOS
brew install ffmpeg
# Windows
winget install Gyan.FFmpeg
```

## 3. 使用方式

### 交互界面（TUI）

```bash
python3 -m music_fetch.app
# 或安装后直接：
music-fetch
```

进入主菜单后按数字选择功能，常用按键：

| 场景 | 按键 |
| --- | --- |
| 下载中 | `p` 暂停/继续，`c` 取消 |
| 批量下载中 | `p` 全部暂停，`r` 全部恢复，`c` 取消 |
| 批量多选 | `空格` 勾选，`回车` 确认，`Esc` 取消 |
| 多行粘贴 | 粘贴后按 `Esc` + `回车` 提交 |
| 任意界面 | `Ctrl+C` 返回/退出 |

登录采用**唯一的官网扫码方式**：自动打开本机 Chrome/Edge 进入网易云官网登录页，用网易云 App 扫码官网二维码（真实浏览器生成，不会触发工具二维码被风控标记的问题）后自动取回登录凭证并保存。

**未登录时主菜单只显示「登录 / 退出」**，其余功能锁定；登录成功后才开放全部菜单。cookie 过期后同样走官网扫码流程重新登录。登录不要求用户提前在网页登录网易云。

### 脚本模式（CLI）

首次使用请先运行 `music-fetch`（不带参数）完成一次扫码登录；脚本模式会默认复用该登录状态，不需要准备 Cookie 文件。

```bash
music-fetch --url "https://music.163.com/song?id=33894312"
```

可选参数：

```bash
music-fetch \
  --url "https://music.163.com/song?id=33894312" \
  --out "./downloads" \
  --format mp3 \
  --rename "自定义文件名" \
  --retry 3 \
  --timeout 30 \
  --concurrency 4 \
  --lyric \
  --verbose
```

`--cookie-file` 仍作为高级覆盖项保留；正常使用无需指定，CLI 会优先复用扫码登录保存的会话。

CLI 代理示例（密码通过环境变量传入）：

```bash
MUSIC_FETCH_PROXY_PASSWORD="proxy-password" music-fetch \
  --url "33894312" \
  --proxy-type socks5 \
  --proxy-host 127.0.0.1 \
  --proxy-port 1080 \
  --proxy-username proxy-user
```

## 4. 打包与 CI

### 本地打包

```bash
python3 -m pip install -e ".[dev]"
python3 build.py --clean
```

产物在 `dist/music-fetch.exe`（Windows）或 `dist/music-fetch`（macOS）。

### CI 自动构建

推送 `v*` 格式的 tag 会触发 GitHub Actions 自动构建 Windows + macOS 版本并上传到 GitHub Release：

```bash
git tag v3.0.0
git push origin v3.0.0
```

## 5. 错误码

- `INVALID_URL`：链接无效或无法解析歌曲 ID
- `AUTH_EXPIRED`：登录态缺失或过期
- `SONG_UNAVAILABLE`：歌曲不可下载（版权/地区/VIP）
- `NETWORK_ERROR`：网络或接口异常
- `DOWNLOAD_FAILED`：下载请求失败
- `DOWNLOAD_CANCELED`：用户主动取消下载
- `CONVERT_TOOL_MISSING`：缺少 ffmpeg，无法执行格式转换
- `CONVERT_FAILED`：音频格式转换失败
- `UNSUPPORTED_FORMAT`：不支持的输出格式
- `UNKNOWN_ERROR`：未预期异常
- `PROXY_CONFIG_ERROR`：CLI 代理参数无效或不完整

## 6. 项目架构

| 路径 | 职责 |
| --- | --- |
| `music_fetch/app.py` | 入口路由：无参数进入 TUI，带参数走脚本模式 CLI。 |
| `music_fetch/tui.py` | 终端交互界面：主菜单、登录、单曲/搜索/歌单/批量/历史/设置/诊断。 |
| `music_fetch/tui_utils.py` | TUI 组件：菜单、确认、键盘多选、二维码渲染、表格与进度辅助。 |
| `music_fetch/download_runner.py` | 线程下载任务：进度快照、暂停/恢复/取消（替换原 QThread worker）。 |
| `music_fetch/batch_inspect.py` | 批量识别纯逻辑：混合输入解析、歌单展开、去重、并发检测与取消。 |
| `music_fetch/batch_download.py` | 批量下载调度：并发上限、逐行状态、历史记录、全部暂停/恢复/取消与结果摘要。 |
| `music_fetch/api.py` | 网易云接口层：链接解析、cookie、登录校验、歌曲/歌单/账号/搜索/歌词/QR 登录 API。 |
| `music_fetch/audio.py` | 音频下载与处理：候选下载、403 fallback、断点续传、格式推断、ffmpeg 转码、歌词嵌入。 |
| `music_fetch/pipeline.py` | 下载管道：纯逻辑重试+转码编排，TUI 和 CLI 共享。 |
| `music_fetch/cli.py` | 脚本模式 CLI：默认复用 TUI 登录态，单曲/歌单下载、`--lyric`/`--concurrency`/代理/日志参数。 |
| `music_fetch/network.py` | 统一网络传输：直连、HTTP/SOCKS5 代理、认证、远程 DNS。 |
| `music_fetch/browser_login.py` | 官网扫码登录：启动本机 Chrome/Edge，经 DevTools 协议自动取回登录凭证（复用已有登录态或扫码）。 |
| `music_fetch/batch_inputs.py` | 批量输入解析：多行链接、分享文案、去重。 |
| `music_fetch/batch_models.py` | 批量数据模型与格式化工具。 |
| `music_fetch/batch_results.py` | 批量结果纯逻辑：失败筛选、状态汇总、失败原因聚合、安全 CSV 生成。 |
| `music_fetch/app_stores.py` | 本地持久化：扫码登录会话、下载历史；CLI 默认复用同一会话。 |
| `music_fetch/history_results.py` | 下载历史纯逻辑：组合筛选、分页、安全 CSV 导出。 |
| `music_fetch/download_tasks.py` / `download_retry.py` | 任务状态模型与失败重试判断。 |
| `music_fetch/diagnostics.py` | 诊断核心：日志尾部、脱敏、API/CDN 探针与报告生成。 |
| `music_fetch/version_check.py` | GitHub API 版本检查。 |
| `music_fetch/app_settings.py` / `app_logging.py` | 全局常量与日志体系。 |
| `music_fetch/ui_texts.py` / `error_texts.py` | 共享文案与错误码到用户提示的映射。 |
| `music-fetch` | macOS/Linux CLI 包装脚本（无参数进入 TUI）。 |
| `start_mac.command` / `start_windows.bat` | macOS/Windows 双击启动 TUI 脚本。 |
| `pyproject.toml` | 项目元数据与依赖（`mutagen`、`prompt-toolkit`、`qrcode`、`requests[socks]`）。 |
| `tests/` | 338 个单元/回归测试与 15 个参数化子测试（全部可在无显示环境运行）。 |
| `CHANGELOG.md` / `ROADMAP.md` | 版本历史与迭代路线。 |

## 7. 测试

```bash
python3 -m pytest tests/ -q
python3 -m mypy music_fetch/ --strict
```

## 8. 日志与排障

- 默认日志：`~/.config/music-fetch/logs/music-fetch.log`
- 日志不会打印完整 `MUSIC_U` 值与代理密码（已脱敏）
- 主菜单“诊断中心”可查看运行环境、API/CDN 连通性、最近告警并导出脱敏报告

## 9. 合规说明

仅用于你已获得合法授权的音频素材。
本工具不提供 DRM/版权绕过能力。
