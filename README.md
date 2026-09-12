# music-fetch

网易云音乐单曲、歌单与专辑下载工具。v3.1 起登录采用**官网扫码（浏览器）**唯一方式，并加入登录门槛（未登录只显示登录/退出）。

## 快速上手

### 方式一：直接下载可执行文件（普通用户，免装 Python）

1. 打开本仓库 [Releases](../../releases) 页，下载最新版：
   - Windows：`music-fetch.exe`；
   - macOS：`music-fetch`（首次使用先执行 `chmod +x music-fetch`）。
2. 双击运行，首次启动会自动打开浏览器登录页 → 用**网易云 App** 扫码 → 登录完成即可下载。

### 方式二：Python 安装（开发者 / 有 Python 环境的用户）

```bash
git clone https://github.com/Tangye0912/netease-music-fetcher.git
cd netease-music-fetcher
python -m pip install -e .
music-fetch    # 交互界面（TUI），唯一入口
```

> 无需安装也可以直接运行：`python -m music_fetch.app`（Windows 双击 `start_windows.bat`、macOS 双击 `start_mac.command`，会自动预设终端窗口大小）。

## 1. 版本概览（v3.4.0）

### 1.1 v3.4.0 变更

- **移除脚本模式（CLI）**：`music-fetch` 现在只有终端交互界面（TUI）一种入口；传参数会提示并退出。后续开发专注 TUI 体验。
- **无损/Hi-Res**：请求链新增 lossless 与 Hi-Res FLAC 档位；需要账号本身具备对应权益，不可用时自动选择较低可播放档位。
- **专辑下载**：TUI 和批量输入均支持专辑链接及分享文案，自动展开全部曲目。
- **双语歌词**：单曲可选不下载、原文、翻译或双语。
- **批量体验**：下载结束显示结果汇总卡片和失败原因；“我的歌单”支持分页浏览。
- **明暗主题**：设置中可切换深色/浅色主题，重启后保持选择。
- **可靠性与工程质量**：修复 API 空值、标签写入、Windows 文件名和断点续传问题，CI 增加覆盖率、mypy 与 ruff 门槛。

### 1.2 v3.3.0 变更

- **试听**：单曲检测与搜索结果选中后可选"试听"——下载标准音质临时文件并用系统播放器打开，听完再决定是否下载。
- **打开所在文件夹**：下载完成后一键打开文件所在目录。
- **工程瘦身**：移除已废弃的终端二维码登录链路（`weapi`、`qrcode` 依赖、QR 轮询与冷却逻辑），冻结包更小、攻击面更少。
- **三平台构建**：CI 新增 Linux 构建，Windows/macOS/Linux 三个平台同时出产物。

### 1.3 v3.2.0 变更

- **信息卡片与音质显示**：单曲检测后与下载完成后用带边框卡片展示歌曲信息（歌名/艺人/专辑/音质/时长/大小）；检测接口返回最高可用音质。
- **搜索分页**：搜索结果每页 10 条，`n`/`p` 翻页、`0` 返回，一屏放得下，不再滚动丢失内容。
- **终端窗口体验**：启动脚本预设终端大小（Windows 140×40），内容宽度上限 100→160 列，表格截断时底部提示加宽窗口。
- **检查更新增强**：支持 `MUSIC_FETCH_GITHUB_TOKEN`／`GITHUB_TOKEN` 环境变量鉴权，并区分"匿名限流/私有仓库/网络不可用"三类报错。
- **登录安全加固**：登录凭证原子替换写入 + POSIX `0600` 权限；一律使用隔离临时 profile，绝不复用已有浏览器登录态；登录成功后清理失败只提示不丢凭证。
- **菜单快捷键与加载动画**：主菜单 `q` 退出、菜单底部按键提示；检测/搜索/歌单/检查更新有动画加载提示。

### 1.4 v3.1.x 重大变更

- **官网扫码登录（浏览器，唯一方式）**：启动本机 Chrome/Edge 打开网易云官网登录页，扫码官网二维码后自动取回登录凭证；移除终端二维码登录与粘贴 Cookie。可绕开工具自身二维码被网易云风控标记的问题。
- **登录门槛**：未登录时主菜单只显示「登录 / 退出」，其余功能锁定；cookie 过期自动回到登录流程。
- **登录稳定性**：每次登录使用隔离的临时浏览器 profile，登录完成后自动关闭扫码窗口并清理临时数据。
- **界面优化**：搜索结果/歌单改为 wcwidth 对齐的分列表格（中文全角正确对齐、表头高亮）；所有下载步骤提示"回车用默认 / 0 取消"；错误信息全中文（去掉英文错误码）；返回操作统一（输入框回车返回、列表 0 返回）。
- **新增依赖**：`websocket-client`（浏览器登录取 cookie 用）。
- **3.1.2 发行修复**：无控制台环境回退为普通文本输出，冻结包补齐 `websocket` 与 `wcwidth` 延迟导入，Windows/macOS CI 均可完成测试和打包。

### 1.5 v3.0.0 重大变更

- **全面 TUI 化**：移除 PySide6 GUI（约 6000 行 Qt 代码与 WebEngine 依赖），所有交互都在终端完成。
- **终端扫码登录**：调用网易云 QR 登录接口，在终端渲染二维码（ASCII 方块），扫码后自动轮询登录状态并保存凭证。
- **键盘多选下载**：批量识别结果用勾选式列表选择（空格勾选、回车确认），下载中支持 `p` 暂停/继续、`r` 恢复、`c` 取消。
- **体积锐减**：单文件产物从约 185MB（含 WebEngine）降至约 13MB，跨平台打包与启动都更快。
- **保留脚本模式**：`music-fetch --url ...` 等参数化 CLI 原样保留（含 `--concurrency` 歌单并行下载）。

### 1.6 核心能力

- 登录：自动打开 Chrome/Edge 官网二维码页面，扫码后经本机 DevTools 协议取回并保存凭证；无需提前登录网易云网页
- 单曲：链接/分享文案/歌曲 ID → 检测 → 目录/文件名/格式/歌词模式 → 加入后台队列，立即继续浏览
- 搜索：按歌名/歌手名搜索并直接下载
- 我的歌单：登录后分页浏览创建/收藏的歌单，选中即进入批量流程
- 专辑：输入专辑链接或分享文案，自动展开曲目进入批量下载
- 批量：多行粘贴 → 并发识别（歌单/专辑自动展开、去重）→ 键盘多选 → 后台并发下载 → 任务页查看结果、重试和导出批次 CSV
- 歌词：原文、翻译或按时间轴合并的双语 `.lrc`，并嵌入支持的音频标签
- 下载历史：分页浏览、状态筛选、关键词搜索、失败重试、打开目录、删除、筛选结果 CSV 导出（防公式注入）
- 设置：下载目录、检测/下载超时、重试次数、并发上限、HTTP/SOCKS5 代理、明暗主题
- 诊断：API/CDN 连通性检测、脱敏日志、诊断报告导出；主菜单可检查新版本
- 格式：mp3/m4a/wav/flac/aac；未安装 ffmpeg 时自动回退保存源格式

### 后台下载（开发分支）

单曲、搜索、歌单、专辑和历史重试统一进入后台队列。提交后可继续搜索、试听或选择下一首；所有下载共用设置中的并发上限。普通交互终端等待输入期间，底栏每 0.5 秒更新状态、传输量和速度，任务列表按回车刷新。

从主菜单进入“下载任务”，可暂停、恢复、取消、重试、打开目录，或查看本次运行的批次汇总、失败原因并导出结果 CSV。登录失效时任务保留并等待登录，在任务页按 `l` 重新扫码后继续；失败重试保留本次运行中选择的格式、歌词和标签参数。旧历史记录仍按原有字段读取。

队列保存在当前进程内，不跨重启恢复。退出时如有未完成任务，会询问是否取消；确认后等待下载线程和临时文件清理完成再退出。关闭程序后下载也会停止。

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
| 下载任务 | 输入序号操作单条；`p` 暂停全部、`r` 恢复全部、`c` 取消全部、`f` 重试失败 |
| 下载任务分页/导出 | `n` 下一页、`b` 上一页、回车刷新列表、`e` 导出批次、`l` 重新登录、`0` 返回 |
| 批量多选 | `空格` 勾选，`回车` 确认，`Esc` 取消 |
| 搜索/我的歌单分页 | `n` 下一页，`p` 上一页，`0` 返回 |
| 多行粘贴 | 粘贴后按 `Esc` + `回车` 提交 |
| 任意界面 | `Ctrl+C` 返回/退出 |

终端主题参考 Bili-hardcore 的信息层级：居中标题、全宽面板、青色焦点、黄色元信息、绿色/红色结果，并针对中文等宽对齐。可在“软件设置 → 界面主题”切换深色/浅色配色；字体由终端应用控制，程序无法强制修改。Windows Terminal 推荐 Cascadia Mono，macOS Terminal/iTerm2 推荐 SF Mono 或 JetBrains Mono，窗口宽度建议至少 80 列。

登录采用**唯一的官网扫码方式**：应用没有自己的有效凭证时，会自动打开本机 Chrome/Edge 的隔离临时 profile 进入网易云官网登录页。用户用网易云 App 扫码官网二维码后，应用自动取回、校验并保存登录凭证。

应用不会打开、读取或复用玩家日常浏览器 profile 中的 Cookie；浏览器此前是否登录过网易云不会影响本流程。**未登录时主菜单只显示「登录 / 退出」**，其余功能锁定；Cookie 过期后先清除旧凭证，再自动走同一套隔离扫码流程。登录不要求用户提前在网页登录网易云。

## 4. 打包与 CI

### 本地打包

```bash
python3 -m pip install -e ".[dev]"
python3 build.py --clean
```

产物在 `dist/music-fetch.exe`（Windows）或 `dist/music-fetch`（macOS/Linux）。

### CI 自动构建

推送 `v*` 格式的 tag 会触发 GitHub Actions 自动构建 Windows、macOS、Linux 版本并上传到 GitHub Release：

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

## 6. 项目架构

| 路径 | 职责 |
| --- | --- |
| `music_fetch/app.py` | 入口：无参数进入 TUI；传参数提示"脚本模式已移除"并退出。 |
| `music_fetch/tui.py` | 终端交互界面：主菜单、登录、单曲/搜索/歌单/专辑/批量/历史/设置/诊断。 |
| `music_fetch/tui_utils.py` | TUI 组件：菜单、确认、键盘多选、信息卡片、加载动画、表格与进度辅助。 |
| `music_fetch/download_queue.py` | 应用后台队列、统一并发、任务控制、登录恢复与结果落盘。 |
| `music_fetch/download_runner.py` | 线程下载任务：进度快照、暂停/恢复/取消（替换原 QThread worker）。 |
| `music_fetch/batch_inspect.py` | 批量识别纯逻辑：混合输入解析、歌单/专辑展开、去重、并发检测与取消。 |
| `music_fetch/batch_download.py` | 批量下载调度：并发上限、逐行状态、历史记录、全部暂停/恢复/取消与结果摘要。 |
| `music_fetch/api.py` | 网易云接口层：链接解析、cookie、登录校验、歌曲/歌单/专辑/账号/搜索/歌词 API。 |
| `music_fetch/audio.py` | 音频下载与处理：候选下载、403 fallback、断点续传、格式推断、ffmpeg 转码、歌词嵌入。 |
| `music_fetch/pipeline.py` | 下载管道：纯逻辑重试+转码编排，TUI 与批量下载共用。 |
| `music_fetch/network.py` | 统一网络传输：直连、HTTP/SOCKS5 代理、认证、远程 DNS。 |
| `music_fetch/browser_login.py` | 官网扫码登录：始终用隔离临时 profile 启动 Chrome/Edge，经 DevTools 协议取回本次扫码产生的凭证，不读取玩家日常浏览器数据。 |
| `music_fetch/batch_inputs.py` | 批量输入解析：多行链接、分享文案、去重。 |
| `music_fetch/batch_models.py` | 批量数据模型与格式化工具。 |
| `music_fetch/batch_results.py` | 批量结果纯逻辑：失败筛选、状态汇总、失败原因聚合、安全 CSV 生成。 |
| `music_fetch/app_stores.py` | 本地持久化：扫码登录会话、下载历史。 |
| `music_fetch/history_results.py` | 下载历史纯逻辑：组合筛选、分页、安全 CSV 导出。 |
| `music_fetch/download_tasks.py` / `download_retry.py` | 任务状态模型与失败重试判断。 |
| `music_fetch/diagnostics.py` | 诊断核心：日志尾部、脱敏、API/CDN 探针与报告生成。 |
| `music_fetch/version_check.py` | GitHub API 版本检查。 |
| `music_fetch/app_settings.py` / `app_logging.py` | 全局常量与日志体系。 |
| `music_fetch/ui_texts.py` / `error_texts.py` | 共享文案与错误码到用户提示的映射。 |
| `music-fetch` | macOS/Linux 包装脚本（进入 TUI）。 |
| `start_mac.command` / `start_windows.bat` | macOS/Windows 双击启动 TUI 脚本。 |
| `pyproject.toml` | 项目元数据与依赖（`mutagen`、`prompt-toolkit`、`pycryptodome`、`requests[socks]`、`websocket-client`）。 |
| `tests/` | 完整的单元/回归测试与参数化子测试（全部可在无显示环境运行）。 |
| `CHANGELOG.md` / `ROADMAP.md` | 版本历史与迭代路线。 |

## 7. 测试

```bash
python3 -m pytest tests/ -q
python3 -m pytest tests/ -q --cov=music_fetch --cov-report=term-missing
python3 -m mypy music_fetch/ --strict
python3 -m ruff check music_fetch/ tests/
```

## 8. 日志与排障

- 默认日志：`~/.config/music-fetch/logs/music-fetch.log`
- 日志不会打印完整 `MUSIC_U` 值与代理密码（已脱敏）
- 主菜单“诊断中心”可查看运行环境、API/CDN 连通性、最近告警并导出脱敏报告

## 9. 合规说明

仅用于你已获得合法授权的音频素材。
本工具不提供 DRM/版权绕过能力。
