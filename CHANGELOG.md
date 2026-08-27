# Changelog

## Unreleased

### Added

- **信息卡片**：单曲检测后与下载完成后用带边框的卡片展示 歌名/艺人/专辑/音质/时长/大小（新增 `tui_utils.print_panel`）。
- **音质显示**：`SongDetectionResult` 新增 `level`/`encode_type` 字段，`detect_song` 返回最高可用音质，单曲界面展示"音质：较高（aac）"。
- **加载动画**：检测/搜索/歌单/检查更新改为动画加载提示（仅 ASCII 帧，兼容 GBK 控制台）。
- **菜单快捷键与底部提示**：主菜单支持 `q` 退出；菜单底部提示栏显示可用按键与返回方式。

### Fixed

- 修复官网登录**成功后**临时扫码数据清理失败会覆盖登录结果的问题：现在登录成功时清理失败只给出提示（不再抛错丢失已取得的凭证），失败路径仍保留原始错误。
- 浏览器登录访问本机 DevTools 端点时强制直连，不再受应用 HTTP/SOCKS5 代理影响；本机 WebSocket 同样显式绕过代理。
- 会话凭证改为同目录临时文件原子替换，POSIX 系统下 `session.json` 权限固定为 `0600`，避免 `MUSIC_U` 与代理密码被其他本机用户读取。
- 完全移除真实浏览器 profile 与已有登录态复用能力；无论玩家浏览器是否登录过网易云，应用都只使用隔离临时 profile 并要求扫码。
- TUI 与 CLI 无凭证时都会自动进入隔离扫码；运行中凭证过期会先清空持久化旧凭证、锁定功能，再重新扫码。批量任务检测到过期后停止继续派发旧凭证任务。
- 扫码浏览器退出后会等待进程释放文件，必要时强制结束，再删除临时 profile；清理失败会显式报错，不再静默遗留凭证数据。
- 浏览器登录诊断只报告是否检测到 Cookie，不再输出可能包含 `MUSIC_U` 的内容预览。
- 未安装 Chrome/Edge 时不再提示已经移除的“粘贴 Cookie”登录方式。
- TUI 视觉参考 Bili-hardcore 重构：新增居中全宽标题、青色状态带、带边框菜单/表格、黄绿红灰信息层级、图标化状态提示，以及统一的多选框和进度条深色主题。
- 修复批量多选界面提示 Esc 可取消但实际无响应的问题；现在按 Esc 会立即取消并返回上一级。
- README 当前版本、登录能力与章节编号同步到 3.1.2。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（388 通过，15 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ tests/`（60 文件零错误）。

## v3.1.2 (2026-08-20)

### Fixed

- **CI 构建修复**：`test_pick_format_cancel_returns_none` 改为确定性测试（mock ffmpeg 状态与警告输出），不再因 CI 环境未装 ffmpeg 触发 `NoConsoleScreenBufferError`。
- **无控制台健壮性**：TUI 的 `print_*` 输出在无交互控制台（CI、管道重定向、无头环境）时回退为普通 `print`，不再崩溃。
- **PyInstaller 打包修复**：`music-fetch.spec` 补充 `websocket`（浏览器登录取 cookie 用，延迟导入易被 PyInstaller 漏掉）与 `wcwidth`（中文表格对齐）的 hiddenimports。

### QA

- 回归测试：Windows CI 370 通过、1 跳过；macOS CI 371 通过；两端均有 15 个参数化子测试通过。
- 类型检查：`python3 -m mypy music_fetch/ tests/`（60 文件零错误）。

## v3.1.1 (2026-08-20)

### Fixed

- 修复下载时网络错误后 `.part` 残留导致换候选源拼接损坏的问题（网络错误现在统一清理临时文件）。
- 菜单选项按终端宽度截断，超长歌名/路径不再撑爆菜单行。
- 首次运行不再生成空的 `session.json`。
- 去掉 ffmpeg 检测的进程级缓存：现在安装 ffmpeg 后无需重启即可识别。
- 403 判定改用单一常量，避免判定与报错文案脱节。

### QA

- 类型检查：`python3 -m mypy music_fetch/ tests/`（**60 个文件零错误**，含测试文件的全部类型问题清理）。
- 回归测试：`python3 -m pytest tests/ -q`（370 通过，1 跳过，15 个参数化子测试通过）。

## v3.1.0 (2026-08-20)

### Changed

- **登录只保留扫码入口**：移除“从浏览器导入 Cookie”和“手动粘贴 Cookie”两条路径。用户不需要提前登录网易云网页，也不要求从浏览器获取或复制任何 Cookie。
- **CLI 复用 TUI 登录态**：脚本模式默认读取 `music-fetch` 扫码登录后保存的会话凭证，不再默认要求用户准备 `cookies.txt`；`--cookie-file` 仅作为显式覆盖保留。
- **8821 风控提示修正**：扫码被网易云风控拦截时，提示改为"等待 24 小时 / 切换网络后再试，期间勿反复操作"（不再引导用户去浏览器取 Cookie）。
- **扫码登录传输层重构（默认仍为 eapi）**：新增 `music_fetch/weapi.py`（AES-128-CBC+RSA 网页加密）作为可选 QR 登录通道，`music_fetch.api.QR_TRANSPORT` 可在 eapi/weapi 间切换；实测网易云服务器已拒绝 weapi 扫码流（`/weapi/*` 全部返回空响应、`/api/*`+weapi 返回"参数错误"），故默认仍用 eapi+type=3（移动端流程）。
- **QR 登录改用网易云移动端 UA**：eapi QR 请求（unikey 与状态轮询）改用 `NeteaseMusic/9.x (Android)` 移动端 User-Agent（`music_fetch.api.NETEASE_MOBILE_UA`），与 type=3 移动客户端流程保持一致，尝试规避确认步骤的 8821 风控；`QR_USE_MOBILE_UA=False` 可回退桌面 UA。
- **QR 登录防风控优化**：状态轮询间隔 2s→5s（登录接口请求量降 ~60%）；被 8821 拦截后启用 30 分钟强制冷却（`QR_REJECT_COOLDOWN_SEC`），期间拒绝再次发起登录并显示倒计时，冷却时间持久化到会话文件（跨重启生效），登录成功后自动解除——从源头避免"频繁操作"触发 24h 限制。
- **官网扫码登录（浏览器）成为唯一登录方式**：新增 `music_fetch/browser_login.py`，启动本机 Chrome/Edge（临时 profile）打开网易云官网登录页，扫码官网二维码（真实浏览器生成，可绕开工具二维码被风控标记的问题）后通过 DevTools 协议自动取回登录凭证。v3.1.0 初始实现曾提供真实浏览器登录态复用选项，该能力现已移除；当前版本只允许隔离扫码。**移除终端二维码登录与粘贴 Cookie 两个入口**；新增 `websocket-client` 依赖。
- **登录门槛（未登录时锁定菜单）**：启动时校验会话 cookie，过期/无效则自动清除；未登录时主菜单只显示「登录 / 退出」，其余功能全部锁定，登录成功后才开放全部菜单。cookie 过期后同样走官网扫码流程。
- **界面与返回体验优化**：输入框统一"回车返回"（单曲、搜索关键词、批量）；列表选择统一为对齐表格（表头彩色加粗）+「0 返回」提示（搜索、歌单）；搜索结果改为分列展示（序号/歌名/歌手/专辑/时长），不再一行挤满。
- **CJK 表格对齐修复**：`print_table` 改用 `wcwidth` 计算显示宽度，中文全角字符按 2 列对齐（此前按 `len()` 计算导致中文表格长短不齐），并修正分隔线宽度。
- **下载向导提示优化**：保存目录/文件名等步骤的提示写明"直接回车用默认、输入 0 取消"，格式选择菜单新增「取消」项；整个下载流程统一支持「0 取消」返回，避免新用户不知道如何退出。
- **新手友好文案优化（一轮 UX 审查）**：界面错误不再显示英文错误码（如 `INVALID_URL:`），只显示中文说明；搜索结果/歌单的"输入序号下载（0 返回）"去重；历史记录操作项显示对应歌名；批量多选提示补充"Esc 取消"；多行输入说明改直白；修复历史删除确认里 `\n` 未换行的问题；检查更新失败文案友好化。

### Removed

- 删除 `music_fetch/browser_cookies.py` 及 Chrome/Edge 本地 Cookie 解密逻辑。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（370 通过，1 跳过，15 个参数化子测试通过；跳过项为无显示环境下的控制台相关测试）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（29 个源文件零错误）。

## v3.0.0 (2026-08-16)

### Added

- **纯终端应用（TUI）**：新增 `music_fetch/app.py` 入口路由与 `music_fetch/tui.py` 交互界面——无参数启动进入键盘菜单，覆盖单曲、搜索、歌单、批量、历史、设置、诊断与版本检查。
- **终端扫码登录**：`api.py` 新增 `fetch_qr_unikey`/`build_qr_login_url`/`poll_qr_login_status`，TUI 用紧凑半块字符二维码展示（bili-hardcore 风格，约 35 列 x 18 行，无需调整终端窗口）并轮询登录状态；登录支持扫码与手动粘贴 Cookie 两种方式。
- **键盘多选与进度控制**：批量识别结果用勾选式列表多选（空格/回车/Esc）；单曲与批量下载进度条支持 `p` 暂停、`r` 恢复、`c` 取消。
- 新增 `download_runner.py`（线程下载任务，替换 QThread `DownloadWorker`）、`batch_inspect.py`（批量识别纯逻辑）、`batch_download.py`（批量下载调度）、`tui_utils.py`（TUI 组件）、`eapi.py`（AES-128-ECB 加密的 /eapi/ 传输层）。
- `history_results.py` 新增 `paginate_download_history` 分页纯函数。

### Changed

- **移除 Qt 层**：删除 `main.py`、`dialogs.py`、`batch_dialogs.py`、`dialog_*.py`、`search_dialog.py`、`playlist_dialog.py`、`gui_styles.py`、`workers.py`、`combo_utils.py` 等 13 个模块及 12 个 Qt 测试文件，共约 6000 行。
- 依赖改为 `mutagen`、`prompt-toolkit`、`pycryptodome`、`qrcode`、`requests[socks]`；移除 PySide6、qt-material、WebEngine。
- 入口脚本：`music-fetch`（无参数进 TUI、带参数走 CLI）、`start_mac.command`/`start_windows.bat` 改为启动 TUI；`pyproject.toml` 入口指向 `music_fetch.app:main`。
- `ui_texts.py` 精简为剩余模块实际使用的文案；`music_fetch/__init__.py` 公开 API 补入 QR 登录与下载运行器。
- PyInstaller spec：入口改为 `music_fetch/app.py`、`console=True`，hiddenimports 更新为 prompt_toolkit/qrcode。

### Fixed

- 修复 v2.1.0 发布时 README.md 残留 3 行 git 冲突标记（`<<<<<<<`/`=======`/`>>>>>>>`）的问题（本次 README 整体重写）。
- 修复扫码确认后返回 8821 的问题：QR 登录改走加密 eapi 传输 + type=3（真机联调中发现并修正）；8821 风控拦截改为明确提示并引导手动 Cookie 登录。
- 修复 TUI 默认值输入被追加拼接、二维码过大需调整终端窗口等问题（真机联调中发现）。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（322 通过，14 个参数化子测试通过）——全部测试可在无显示环境运行。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（26 个源文件零错误）。
- 打包验证：PyInstaller 单文件产物 185MB → 13MB，冻结二进制完成 CLI 帮助与 TUI 主菜单冒烟。
- 交互冒烟：pty 下验证主菜单、下载历史、单曲检测未登录提示等流程。

## v2.1.0 (2026-08-06)

### Added

- **CLI 歌单并行下载**：新增 `--concurrency` 参数，支持 1-8 路并行下载大歌单，结果按歌单原顺序返回。
- 新增 `music_fetch/csv_utils.py` 共享 CSV 安全工具，统一历史与批量导出的公式注入防护实现。
- `music_fetch/__init__.py` 新增显式 `__all__`，收紧公开 API 并阻止内部符号意外泄漏。
- 新增 9 个回归测试：CSV 安全工具、批量 CSV 公式注入防护、`--concurrency` 解析、歌单标签/歌词透传与并行上限。

### Changed

- `run_playlist_download` 现在把 `tags`（标题/歌手/专辑/封面）与 `download_lyric` 透传给下载管道，歌单下载与单曲下载保持一致。

### Fixed

- 修复 CLI 歌单下载接受 `--lyric` 却不透传导致歌词被静默忽略、且音频标签不写入的问题。
- 修复批量结果 CSV 导出未对以 `=`、`+`、`-`、`@` 开头的字段做公式注入防护的问题（现在与下载历史导出行为对齐）。

### QA

- 回归测试：本地无显示环境验证 291 个纯逻辑测试 + 10 个参数化子测试通过（Qt GUI 测试由 CI 的图形环境覆盖）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（33 个源文件零错误）。

## v2.0.0 (2026-08-06)

### Added

- 单曲检测成功后在主窗口内联展示结果与下载面板，包含封面、歌名、歌手、专辑、时长、保存目录、文件名、格式、进度、速度、暂停/恢复、取消和完成状态。
- 新增主窗口行为覆盖：内联结果展示、单曲下载不再实例化旧弹窗、成功/失败/取消历史记录、ffmpeg 缺失格式限制、新输入清空旧结果。
- 新增大歌单分页回归测试，覆盖超过 1000 首时继续请求后续分页。

### Changed

- 单曲主流程改为“检测 → 主窗口内联确认与下载”，保留旧 `SongConfirmDialog`、`DownloadOptionsDialog`、`DownloadProgressDialog` 代码但正常路径不再使用。
- 多链接和歌单仍进入现有批量下载页，主窗口只补充批量路由状态提示。
- GitHub Actions 构建产物保留期调整为 3 天，降低 Actions storage 占用。

### Fixed

- 避免 PySide6 主窗口测试通过 class-level `MagicMock` patch Qt 方法时触发访问冲突。

### QA

- 回归测试：`python -m pytest tests/ -q`（437 通过，1 跳过，10 个参数化子测试通过）。
- 类型检查：`python -m mypy music_fetch/ --strict`（32 个源文件零错误）。

## v1.14.0 (2026-07-19)
### Added

- 新增 8 个 `MainWindow` 行为测试，覆盖单曲检测启动、批量路由、搜索/歌单快捷入口、设置取消，以及成功、失败、取消三种下载结果。

### Changed

- 搜索结果和用户歌单统一通过 `_submit_selected_input()` 写入、同步分析并提交，避免不同快捷入口各自维护易失的输入状态。
- ROADMAP 移除已完成的主窗口行为测试项，保留公开 API、覆盖率和发行体积等后续工作。

### Fixed

- 修复搜索对话框选中歌曲后只填入歌曲 ID、不会实际开始检测的问题。
- 修复用户歌单选中后只填入歌单链接、不会进入批量检测页面的问题。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（432 通过，10 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（32 个源文件零错误）。

## v1.13.0 (2026-07-19)

### Added

- **下载历史检索**：下载管理器新增可清除搜索框，支持按歌曲名、歌曲 ID、文件名、完整路径、任务状态和错误码进行大小写不敏感的多关键词匹配。
- **筛选结果导出**：新增“导出 CSV”，导出状态与关键词组合筛选后的全部记录，不受当前 50 行分页限制。
- 新增 `history_results.py` 与 9 个行为测试，覆盖组合查询、中文状态、跨页导出、CSV 转义、空结果和写盘失败。

### Changed

- 搜索文本或状态筛选变化时自动回到第一页，并同步更新结果总数、空状态和导出按钮可用性。
- 历史 CSV 使用固定字段与 `utf-8-sig` 写入，Excel 可直接识别中文；未填写扩展名时自动补 `.csv`。
- README 中“下载管理导出 CSV”的既有说明现在由实际功能和回归测试支撑。

### Fixed

- 修复 README 声称下载管理支持 CSV、实际只有批量结果页可导出的文档—代码不一致。
- CSV 文本对去除前导空白后以 `=`、`+`、`-`、`@` 开头的字段添加安全前缀，避免歌曲元数据被电子表格解释为公式。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（424 通过，10 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（32 个源文件零错误）。

## v1.12.0 (2026-07-19)

### Added

- **GUI 诊断中心**：主界面快捷入口新增运行概览、最近失败任务、API/CDN 连通性和脱敏日志预览。
- **异步网络检测**：独立线程检测网易云 API 与音乐外链/CDN，不阻塞 GUI；HTTP 2xx/4xx/5xx 均正确表示服务端可达。
- **诊断报告导出**：可将版本、Python/系统、登录状态、代理摘要、ffmpeg、最近错误码、网络结果和最近警告导出为文本文件。
- 新增 `diagnostics.py` 与 14 个行为测试，覆盖缺失日志、Cookie/代理凭据脱敏、网络成功/失败、报告、导出、线程保护和主界面入口。

### Changed

- GUI 默认日志级别由 INFO 调整为 WARNING，减少日常日志噪声；CLI 继续由默认/`--verbose`/`--debug` 控制 WARNING/INFO/DEBUG。
- 诊断日志预览只显示 WARNING、ERROR、CRITICAL，导出前再次应用显式敏感值、Cookie 字段和代理 URL 凭据脱敏。
- 网络检测按钮作为主操作，其余刷新、目录和关闭操作复用现有次要/返回按钮样式。

### Fixed

- 修复 CDN 探针缺少网易云 Referer/Accept 请求头导致实际下载可用却被诊断为不可达的问题；真实探针验证 API `HTTP 200`、CDN `HTTP 206`。
- 修复非法持久化代理已回退直连后，诊断报告仍显示旧代理字段的问题；现在读取当前实际生效的传输配置。
- 修复网络检测线程运行时关闭对话框可能销毁活动 QThread 的风险；检测完成前会阻止关闭。
- 避免成功导出报告被记录为 WARNING 后反向污染下一份诊断报告。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（415 通过，10 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（31 个源文件零错误）。
- 深色主题主窗口与诊断中心完成离屏渲染检查，真实 API/CDN 网络探针通过。

## v1.11.0 (2026-07-19)

### Added

- **下载历史分页**：下载管理器新增上一页、下一页和页码摘要，每页只构造 50 行表格，千条历史不再一次性渲染。
- 新增大历史分页、跨页选择映射、筛选重置、页码回退和存储上限回归测试。

### Changed

- 状态筛选切换时自动回到第一页；刷新、删除或重试使总页数减少时自动回退到最后一个有效页。
- 分页按钮复用次要操作样式，保持下载管理器的操作层级清晰。
- ROADMAP 移除已完成的历史分页，以及已有测试覆盖的音频 header 轮换、403 重试和断点续传条目。

### Fixed

- 修复下载历史 1000 条上限只在首次读盘时生效、缓存建立后仍可持续无限增长的问题；现在缓存和落盘始终只保留最新 1000 条。
- 修复第二页及后续页面选择记录时仍按完整筛选列表索引、可能对错误历史记录执行操作的风险。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（401 通过，10 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（29 个源文件零错误）。

## v1.10.0 (2026-07-19)

### Added

- **代理设置界面**：软件设置新增直连、HTTP、SOCKS5、主机、端口和可选用户名/密码，保存前执行完整输入校验并立即生效。
- **统一网络传输层**：新增 `music_fetch.network`，集中管理代理配置、认证、HTTP/SOCKS5 传输与 urllib 兼容响应。
- **CLI 代理参数**：新增 `--proxy-type`、`--proxy-host`、`--proxy-port`、`--proxy-username`；密码仅从 `MUSIC_FETCH_PROXY_PASSWORD` 读取。
- **SOCKS5 明确依赖**：加入 `requests[socks]`，使用 `socks5h` 让目标域名由代理端解析。

### Changed

- API、短链接解析、头像、媒体大小探测、音频流、封面下载和版本检查统一使用应用代理状态。
- 应用在登录态在线校验前应用持久化代理；设置变更后同步刷新项目传输层和 Qt 应用代理。
- SessionStore 对代理类型、端口和可选凭据进行规范化，非法旧配置启动时安全回退直连。

### Fixed

- 修复代理设置只能持久化、重启后却从未调用 `configure_proxy()` 的无效配置问题。
- 修复代理用户名和密码字段已存在但 HTTP/SOCKS5 请求完全未使用的问题。
- 修复音频 CDN、短链接、头像和封面仍绕过 API 代理处理器的问题。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（396 通过，10 个参数化子测试通过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（29 个源文件零错误）。
- 本地 HTTP/SOCKS5 端到端测试验证 Basic 认证、SOCKS5 用户名/密码握手与远程 DNS。

## v1.9.0 (2026-07-19)

### Added

- **应用级视觉系统**：在 `qt-material` 基础主题之上恢复可维护的应用样式层，统一浅色/深色调色板、卡片、按钮、输入框、表格、进度条和语义状态反馈。
- **代理基础能力**：API 层新增 HTTP/SOCKS5 代理配置接口，会话存储可持久化代理字段；GUI/CLI 配置入口、SOCKS5 行为验证和下载链路统一代理仍列入 ROADMAP。
- **持续类型检查**：开发依赖补入 mypy，Windows/macOS 发布工作流在测试后执行 `music_fetch/` strict 检查。

### Changed

- **主窗口重构**：调整为品牌区、账户卡片、快捷入口、主输入卡片、状态区和页脚的分层布局。
- **动态视觉尺寸**：字体大小变更后同步刷新头像、输入区和主操作按钮尺寸；恢复窗口尺寸时不再允许小于当前最小布局。
- **键盘导航**：补全主输入、检测、搜索、歌单、下载管理、依赖管理和软件设置之间的 Tab 顺序。
- **批量识别取消**：识别按钮在运行时切换为取消入口；取消后保留已完成结果，可直接下载或重新识别同一输入。
- **有限任务调度**：批量识别只维持并发上限数量的待执行任务，取消后不再继续启动长队列中的网络请求。

### Fixed

- **WebEngine 退出崩溃**：关闭登录对话框时按顺序释放 WebView 和 WebEnginePage，避免 profile 先销毁导致进程异常退出。
- **重新登录丢失设置**：登录流程直接复用完整 `AppSession`，保留代理等新增字段；未勾选“记住登录”时仍仅在当前进程使用 cookie。
- **主题状态对比度**：禁用的主按钮不再显示为可点击高亮色，页脚链接颜色随浅色/深色主题切换。
- **批量结果错配**：识别结果绑定任务启动时的输入签名，并在识别期间锁定可变输入，避免旧结果误用于新输入。
- **按钮状态残留**：语义按钮从主操作切换为次操作时同步清除默认按钮状态；空批量输入初始化时正确隐藏并禁用识别按钮。

### QA

- 回归测试：`python3 -m pytest tests/ -q`（369 通过，退出码 0）。
- 语法检查：`python3 -m compileall -q music_fetch`。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（28 个源文件零错误）。
- PyInstaller 打包和 GUI/WebEngine 启动冒烟测试通过。

## v1.8.0 (2026-07-09)

### Changed

- **Material Design UI**：引入 `qt-material` 库，替代手写 QSS 样式表。
  - 亮色主题：`light_red_500.xml`，暗色主题：`dark_red.xml`。
  - 统一 Qt 控件的基础调色板、圆角和交互状态。
  - 移除 390 行手写 QSS 代码（`build_app_stylesheet`、`build_dark_stylesheet`）。
  - 保留按钮角色（primary/secondary/back）和标签状态（success/warning/error/muted）语义化 API。
  - 新增依赖：`qt-material>=2.14`。

### QA

- 回归测试：`python3 -m pytest tests/`（331 通过，1 跳过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（零错误）。

## v1.7.0 (2026-07-09)

### Added

- **歌词下载**：支持下载 `.lrc` 歌词文件并嵌入音频标签（MP3 USLT、M4A lyrics、FLAC lyrics）。
  - `api.py`：新增 `fetch_lyric()` 和 `LyricResult` 数据类。
  - `audio.py`：新增 `save_lyric_file()` 和 `embed_lyric_tag()`。
  - `pipeline.py`：`run_download_pipeline` 新增 `download_lyric` 参数。
  - CLI：新增 `--lyric` 参数。

### QA

- 回归测试：`python3 -m pytest tests/`（332 通过，1 跳过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（零错误）。

## v1.6.0 (2026-07-09)

### Added

- **macOS CI 构建**：新增 `build-macos` job，发布 macOS 可执行文件。
- **测试覆盖**：新增 `cli.py` 集成测试（5 个）和 `api.py` 网络 mock 测试（`fetch_playable_candidates`、`detect_song` 共 5 个）。测试总数 323 → 332（+9）。

### Fixed

- CI `Upload to Release` 403 错误，添加 `permissions: contents: write`。

### QA

- 回归测试：`python3 -m pytest tests/`（332 通过，1 跳过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（零错误）。
- CI：Windows + macOS 双平台构建。

## v1.5.0 (2026-07-09)

### Added

- **mypy strict mode**：28 个源文件零类型错误，`pyproject.toml` 启用 `strict = true`。
- **CLI 日志分级**：新增 `--verbose`（INFO）和 `--debug`（DEBUG）参数。
- **BatchInspectWorker 取消支持**：检测流程可通过 `request_cancel()` 中途取消。
- **测试覆盖**：新增 `test_search_dialog.py`（4 个）、`test_playlist_dialog.py`（4 个）、`test_api.py`（18 个网络 mock 测试）。测试总数从 297 → 323。

### Changed

- `DownloadHistoryStore` 加载时限制最多保留最近 1000 条记录，避免内存无限增长。
- `pyproject.toml` 中 mypy 禁用 PySide6 相关的 `attr-defined`/`no-untyped-def` 等噪声错误码，忽略 `mutagen`/`PySide6`/`shiboken6` incomplete stubs。

### Fixed

- CI 上 2 个测试因 ffmpeg 缺失而失败：`test_is_ffmpeg_available` 添加 `invalidate_ffmpeg_cache()` 调用，`test_convert_failure_cleans_temp_files` mock `is_ffmpeg_available`。
- `build.py` 中 exe 未找到时返回非零退出码。

### QA

- 回归测试：`python3 -m pytest tests/`（323 通过，1 跳过）。
- 类型检查：`python3 -m mypy music_fetch/ --strict`（零错误）。

## v1.4.2 (2026-07-09)

### Fixed

- **歌单翻页 bug**：`fetch_playlist_song_ids` 翻页循环中始终使用第一页的 `first_page_body` 而非当前页的 `body`，导致超过 1000 首的歌单无法完整下载。
- **批量下载进度计数偏差**：`_on_download_worker_finished` 与 status 回调（succeeded/failed/canceled）双重调用 `_finalize_download_worker`，可能导致 `_download_cursor` 重复递增。

### Refactored

- **QThread.run 猴子补丁**：`main.py` 和 `dialog_login.py` 中 3 处 `thread.run = fn` 替换为 `_TaskThread(QThread)` 子类，避免 PySide6 兼容性隐患。
- **PyInstaller onefile 模式**：打包从 `COLLECT`（目录）改为单文件 `EXE`，避免源码泄露到 `dist/` 中。

### Changed

- `pyproject.toml` 中 `requires-python` 从 `>=3.9` 收紧为 `>=3.10`（PySide6 实际要求）。
- CI workflow 适配 onefile 输出，移除 zip 打包步骤。

### Removed

- `_download_audio_stream` 中不可达的 `except MusicFetchError` 死代码块。
- `ui_texts.py` 中重复的 `ACC_BTN_LOGIN_CONFIRM` 和 `ACC_BTN_DETECT_SHORT` 常量定义。
- `dist/` 中的 `__pycache__` 目录。

### QA

- 回归测试：`python3 -m pytest tests/`（297 通过，1 跳过）。

## v1.4.1 (2026-07-08)

### Added

- **测试覆盖提升**：新增 67 个单元测试，覆盖 `api.py`（链接解析、cookie、短链）、`dialog_login.py`（异步登录检查流程）、`dialog_progress.py`（暂停/恢复/取消按钮状态）、`pipeline.py`（MP3/MP4/FLAC 标签写入分支、convert 异常清理）。

### QA

- 回归测试：`python3 -m pytest tests/`（290 通过，1 跳过）。

## v1.4.0 (2026-07-08)

### Added

- **批量下载暂停/恢复 UI 完善**：暂停时正在下载的行状态切换为"下载已暂停"并灰色高亮，恢复时切回"下载中"并蓝色高亮。
- **下载进度条实时更新**：批量下载过程中累加所有活跃 worker 的下载比例实时更新进度条，不再只在每首完成时跳变。

### Fixed

- **进度条截断 bug**：`int(downloaded/total)` 截断后几乎总是 0，进度条在下载过程中不动。改为累加所有 worker 的部分进度并四舍五入。
- **暂停状态矛盾**：暂停后 worker 仍 emit progress 信号导致 status_label 显示下载速度文本与"已暂停"矛盾。暂停时跳过 status_label 更新。
- **登录检查异常未兜底**：`check_status` 子线程只捕获 `MusicFetchError`，其他异常导致 `_login_checking` 永久 True、confirm 按钮永久禁用。添加 `except Exception` 兜底。

### QA

- 回归测试：`python3 -m pytest tests/`（223 通过，1 跳过）。

## v1.3.1 (2026-07-08)

### Fixed

- **playlist 断网保留**：`fetch_playlist_song_ids` 分页拉取中途网络断开时，返回已获取的歌曲 ID 而非直接抛异常，避免已获取列表丢失。
- **CLI ffmpeg 降级提示**：`run_download` / `run_playlist_download` 在 ffmpeg 缺失导致输出格式降级时，向 stderr 输出 WARNING 提示实际保存格式。
- **删除空 `__init__.py`**：根目录残留的空文件已删除。
- **type: ignore 迁移**：`batch_dialogs.py` 中 2 处 `type: ignore[override]` 行内注释迁移到 `pyproject.toml` 的 `[tool.mypy] disable_error_code` 全局配置。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.3.0 (2026-07-05)

### Added

- **PyInstaller 打包**：新增 `music-fetch.spec` 和 `build.py`，支持一键打包独立应用（`python build.py --clean`），无需安装 Python。
- **GitHub Actions CI**：新增 `.github/workflows/build.yml`，推送 `v*` 标签时自动构建 Windows 安装包并上传到 GitHub Release（草稿状态）。
- **开发依赖**：`pyproject.toml` 新增 `[dev]` 可选依赖（pyinstaller + pytest）。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.2.0 (2026-07-05)

### Added

- **搜索下载**：主界面新增"搜索"按钮，输入歌曲名/歌手名直接搜索网易云曲库，点击结果即可下载。新增 `search_dialog.py` 和 `search_songs` API。
- **用户歌单**：主界面新增"我的歌单"按钮，登录后展示用户创建/收藏的歌单列表，点击歌单一键进入批量下载。新增 `playlist_dialog.py` 和 `fetch_user_playlists` API。
- **自动更新下载**：`version_check.py` 新增 `fetch_release_download_url`，检测到新版本时获取安装包下载链接。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.1.0 (2026-07-05)

### Added

- **系统托盘最小化**：关闭窗口时最小化到系统托盘，双击托盘图标恢复窗口。托盘菜单支持"显示"和"退出"。
- **下载完成通知**：单曲下载成功/失败时通过系统托盘弹出通知。
- **剪贴板自动检测**：每 2 秒检查剪贴板，检测到网易云链接时自动填入输入框（仅当输入框为空时）。
- **窗口位置/大小记忆**：主窗口位置和大小持久化到 session，下次启动恢复。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.0.14 (2026-07-04)

### Fixed

- 恢复 v1.0.1 声称修复但实际未生效的 3 处主线程异步化（、、）。

## v1.0.10 (2026-07-04)

### Removed

-  死代码。
-  4 个未使用的导入。
-  中  死代码检查。
-  docstring 中  引用。

## v1.0.9 (2026-07-04)

### Fixed

-  添加  捕获。
-   包裹 。
-  传递 // 到 。

## v1.0.8 (2026-07-04)

### Fixed

-  回退使用 。
-   捕获 。
-  移除重复 。
-  load 方法添加 。
-  修复  生命周期。

## v1.0.7 (2026-07-04)

### Fixed

-  添加  导入。
-   添加  处理。

## v1.0.6 (2026-07-04)

### Fixed (CRASH)

-  中  复制粘贴错误导致 。
-  分页使用  而非 。

## v1.0.5 (2026-07-04)

### Fixed (CRASH)

- `workers.py` 中 `DownloadPaused` 死代码 handler 残留（v1.0.4 清理不完整），引用未定义的异常类和 `paused` 信号，触发即 `NameError`/`AttributeError` 崩溃。

### Fixed

- **批量下载 ID3 标签缺失**：`BatchDownloadDialog` 创建 `DownloadWorker` 时未传 `tags`，批量下载文件无歌曲名/艺人/专辑标签。
- **播放列表分页可能无限循环**：当所有歌曲 ID 都被去重时，`raw_track_ids` 仍有值但 `page_ids` 为空，循环永不退出。
- **播放列表回退逻辑错误**：`tracks` 回退只检查最后一页的 `body`，应使用第一页。
- **双击检测导致重复 worker**：`_on_detect_clicked` 未断开旧 `InspectWorker` 信号，快速双击触发两个并行检测。
- `batch_dialogs.py` `__all__` 错误列出 `BatchRuntimeSettingsDialog`（不在本模块）。
- `dialog_batch_settings.py` 文档字符串拼写错误。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.0.4 (2026-07-04)

### Fixed (CRASH)

- `fetch_song_metadata` 错误路径返回 2 个值但调用方解包 5 个 → `ValueError` crash。修复为返回 5 个 `None`。
- `detect_song` 丢弃 `cover_url`/`artist`/`album_name`，导致单曲下载封面图和标签写入失效。

### Removed

- `DownloadPaused` 异常类（v1.0.3 暂停改为阻塞等待后已成死代码）。
- `workers.py` 中 `DownloadPaused` 死代码 handler。
- `audio.py` 中 `urlopen` 死代码 `status >= 400` 检查（`HTTPError` 在进入 `with` 前抛出）。
- `dialog_progress.py` 中重复 `request_cancel()` 调用。
- `audio.py` 循环内 `import time` 局部导入 → 模块级导入。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.0.3 (2026-07-04)

### Fixed (CRITICAL)

- **暂停/恢复实际不可用**：暂停后 worker 线程立即退出导致恢复无效。改为阻塞等待（`_audio.py` 下载循环中 `sleep(0.1)` 直到 resume 或 cancel），移除 `DownloadPaused` 异常和 `paused` 信号。暂停/恢复现在真正可用。

### Fixed (HIGH)

- **SongConfirmDialog 高度不够**：封面图 + 7 行网格在 320px 高度下被裁剪 → 增至 400px。
- **BatchDownloadDialog 按钮溢出**：10 个按钮在 980px 宽度下过于拥挤 → 窗口宽度增至 1020px。
- **封面图暗色模式不可见**：`cover_label` 添加边框和浅色背景。

### QA

- 回归测试：`python3 -m pytest tests/`（217 通过，1 跳过）。

## v1.0.2 (2026-07-04)

### Added

- **封面图**：`SongConfirmDialog` 显示 120×120 专辑封面、艺人名称、专辑名称。`fetch_song_metadata` 扩展返回 `cover_url`、`artist`、`album_name`。
- **ID3 标签**：下载文件自动嵌入歌曲名、艺人、专辑、封面图（MP3/MP4/FLAC）。依赖 `mutagen` 库。
- **Cookie 过期处理**：检测到 `AUTH_EXPIRED` 时弹出 Ok/Cancel 对话框，点击 Ok 自动触发重新登录。

### QA

- 回归测试：`python3 -m pytest tests/`（219 通过，1 跳过）。

## v1.0.1 (2026-07-04)

### Fixed

- **主线程阻塞**：3 处网络 I/O（账号刷新、版本检查、登录校验）改为 `QThread` 异步执行，UI 不再冻结。
- **暗色主题颜色**：`SongConfirmDialog` 硬编码 `setStyleSheet` 改为 `set_label_state`，暗色模式下正确显示。
- **按钮样式**：`DownloadProgressDialog` 的暂停/取消按钮添加 `set_secondary_button` 样式，与其他对话框一致。
- **响应式尺寸**：主窗口和输入框改为屏幕/字体比例自适应，高 DPI 和大字体不再截断。
- **缺失导入**：`dialog_manager.py` 添加 `DownloadProgressDialog` 显式导入。
- **Light 主题**：补全 `QTableWidget`、`QHeaderView`、`QGroupBox`、`QMenu`、`QCheckBox`、`QProgressBar` 样式。
- **状态栏**：添加最小高度防止布局跳动。
- **无障碍**：`main.py` 和 `dialog_login.py` 关键控件添加 `AccessibleName`。
- **下载管理**：重试成功时移除旧记录避免重复。
- **键盘快捷键**：`Ctrl+D` 触发检测。

### QA

- 回归测试：`python3 -m pytest tests/`（219 通过，1 跳过）。

## v1.0.0 (2026-07-04)

### Breaking

- 包结构：所有模块从根目录迁移到 `music_fetch/` 包，`import _api` → `from music_fetch.api import ...`。`import music_fetch` 顶层导入保持不变。
- `music_fetch/__init__.py` 公开 API 收紧：`perform_json_post`、`perform_json_get`、`USER_AGENT` 等内部实现不再通过星号导入暴露。

### Added

- `ErrorCode` 枚举（11 个错误码），`MusicFetchError` 接受 `str | ErrorCode`。
- `DownloadCanceled` / `DownloadPaused` 专用异常类，从 `MusicFetchError` 中分离控制流。
- `DownloadPipeline`（`run_download_pipeline`）：GUI 和 CLI 共享的纯逻辑下载管道。
- 暗色主题：`QScrollBar`、`QToolTip`、`QStatusBar`、`QTableWidget`、`QMenu` 等全面覆盖。
- `tests/test_gui_styles.py`（7 个测试）、`tests/test_pipeline.py`（7 个测试）。

### Fixed

- `music-fetch` shell wrapper 引用修复（`-m _cli` → `-m music_fetch.cli`）。
- `load_cookie` 添加 `UnicodeDecodeError` 捕获（cookie 文件损坏）。
- 下载目录不可写时映射为友好错误码。
- `from music_fetch import X` 间接导入改为直接子模块导入（6 个模块）。
- PySide6 版本约束加 `<7.0` 上限。

### QA

- 回归测试：`python3 -m pytest tests/`（219 通过，1 跳过）。

## v0.14.0 (2026-07-04)

### Architecture

- **包结构迁移**：26 个平铺模块迁移到 `music_fetch/` 包目录，`music_fetch.py` 外观层替换为 `music_fetch/__init__.py`，`pyproject.toml` 从 `py-modules` 改为 `packages`。
- **错误处理重构**：新增 `ErrorCode` 枚举（11 个错误码），`MusicFetchError.__init__` 接受 `str | ErrorCode`；新增 `DownloadCanceled`/`DownloadPaused` 专用异常类，从 `MusicFetchError` 中分离控制流信号。
- **下载管道抽象**：新增 `music_fetch/pipeline.py`（`run_download_pipeline` + `DownloadPipelineResult`），GUI 的 `DownloadWorker.run()` 从 120 行简化到 55 行，CLI 的 `run_download`/`run_playlist_download` 共用同一套逻辑。

### QA

- 回归测试：`python3 -m pytest tests/`（206 通过，1 跳过）。

## v0.13.0 (2026-07-03)

### Fixed

- 修复 `_dialog_batch_settings.py` 两处遗漏导入：`set_label_state`（`NameError`）和 `clamp_download_settings`。
- 修复 CLI `--retry` 参数死代码：`run_download`/`run_playlist_download` 现在接收 `retry_count` 并在 `download_song_with_fallback` 外层包装重试循环。

### Added

- 新增 `tests/test_cli.py`（8 个测试用例），覆盖 `build_parser`、`run_download`（含重试）、`main`。
- 新增 `tests/test_version_check.py`（7 个测试用例），覆盖 `version_key`、`fetch_latest_project_version`。
- 新增 `tests/test_dialog_batch_settings.py`（3 个测试用例），覆盖 `BatchRuntimeSettingsDialog`。
- 暗色主题补全：`QScrollBar`（垂直/水平）、`QToolTip`、`QStatusBar` 样式。

### Changed

- `_dialog_progress.py`：恢复后状态标签从 `"准备下载..."` 改为 `"下载恢复中..."`。
- `ui_texts.py`：`status_ui_settings_updated` 新增 `prefix` 参数（默认 `True`），消除 `_dialogs.py` 中 `.replace("状态：", "")` hack。
- `main.py`：移除未使用导入 `json`、`time`、`parse`、`request`。

### QA

- 回归测试：`python3 -m pytest tests/`（208 通过，1 跳过）。

## v0.12.0 (2026-07-03)

### Fixed

- 修复暂停后取消时 `.part` 临时文件残留：`_stop_download_flow` 和 `DownloadWorker.finally` 块清理 `.part` 文件，暂停时保留断点续传文件。

### Changed

- 硬编码中文清理：`_batch_dialogs.py` 中 6 处硬编码状态消息提取到 `ui_texts`（`batch_runtime_settings_updated`、`batch_download_concurrency_label` 等）。
- `main.py` 中 4 处硬编码状态消息提取到 `ui_texts`（`status_update_available`、`status_update_latest`、`status_download_done`）。
- Combo 后缀 `"次"`/`"路"` 提取到 `ui_texts.COUNT_SUFFIX` / `CONCURRENCY_SUFFIX`。
- CLI 新增 `--retry` 参数，移除无效的 `argparse.ArgumentError` 捕获。

### Refactored

- 拆分 `_dialogs.py`：`DownloadProgressDialog` → `_dialog_progress.py`，`DownloadManagerDialog` → `_dialog_manager.py`。
- 拆分 `_batch_dialogs.py`：`BatchRuntimeSettingsDialog` → `_dialog_batch_settings.py`。
- 提取 `main.py` 版本检查：`version_key` + `fetch_latest_project_version` → `_version_check.py`。
- 补 `__all__` 定义：11 个模块（`_batch_dialogs`、`_dialogs`、`_dialog_login`、`_batch_models`、`_batch_results`、`_gui_styles`、`_combo_utils`、`_dialog_progress`、`_dialog_manager`、`_dialog_batch_settings`、`_version_check`）。

### QA

- 新增 `tests/test_app_logging.py`（8 个测试用例），覆盖 `setup_logging`、`get_logger`、`mask_value`、`default_log_path`。
- 回归测试：`python3 -m pytest tests/`（188 通过，1 跳过）。

## v0.11.0 (2026-07-03)

### Added

- 暂停/恢复 UI：`DownloadProgressDialog` 新增暂停/继续按钮，`BatchDownloadDialog` 新增全部暂停/全部恢复按钮，`ui_texts.py` 新增暂停/恢复相关文案。
- CLI 补全：重新添加 `--format` 参数（支持 `mp3/m4a/wav/flac/aac`），新增 `--rename` 参数，播放列表自动检测和批量下载（`run_playlist_download`），改用 `download_song_with_fallback` 替代 `fetch_playable_url`。
- `tests/test_batch_models.py`（19 个测试用例），覆盖 `format_duration`、`format_bytes`、`probe_media_size_bytes`、`BatchDetectRow`。
- `app_settings.py` 新增 `clamp_download_settings` 辅助函数，统一 4 字段下载参数钳位。

### Changed

- 拆分 `_dialogs.py`：`LoginDialog` + `build_cookie_from_fields` + `WEB_ENGINE_AVAILABLE` 提取到 `_dialog_login.py`。
- `_batch_dialogs.py`、`_dialogs.py`、`_workers.py` 中重复的 4 字段 clamp 改为调用 `clamp_download_settings`。
- `_api.py` 返回类型精确化：`dict` → `dict[str, object]`。
- `_cli.py` 修复裸 `except Exception` 为 `except (OSError, ValueError, argparse.ArgumentError)`。
- `pyproject.toml` 新增 `_dialog_login` 模块声明。

### QA

- 回归测试：`python3 -m pytest tests/`（178 通过，1 跳过）。

## v0.10.0 (2026-07-01)

### Added

- 新增 `_batch_models.py`：从 `_workers.py` 提取 `BatchDetectRow`、`format_bytes`、`format_duration`、`probe_media_size_bytes` 等纯数据模型和格式化工具，降低模块耦合度。
- 新增 `_gui_styles.py`：从 `_dialogs.py` 提取样式构建（`build_app_stylesheet`、`apply_app_style`）、按钮角色（`set_button_role`、`set_back_button`、`set_secondary_button`）和标签状态（`set_label_state`）等样式辅助函数。
- 新增 `tests/test_dialogs.py`（42 个测试用例），覆盖 `_dialogs.py` 中 7 个对话框类（`LoginDialog`、`SongConfirmDialog`、`DownloadOptionsDialog`、`DownloadProgressDialog`、`DependencyManagerDialog`、`DownloadManagerDialog`、`UiSettingsDialog`）和纯函数（`build_cookie_from_fields`、`validate_song_input`、`load_avatar_icon`、`clear_embedded_login_state`）。
- 下载暂停/恢复：`DownloadWorker` 新增 `paused` 信号、`request_pause()` 和 `request_resume()` 方法，`_audio.py` 新增 `pause_checker` 回调支持，暂停时保留 `.part` 文件以便恢复。
- 断点续传：`_download_audio_stream` 支持从 `.part` 文件恢复下载（使用 `Range: bytes={offset}-` 请求头），避免重复下载已传输数据。
- 暗色主题：新增 `build_dark_stylesheet`（Catppuccin 风格），`UiSettingsDialog` 新增主题切换下拉框，`app_stores.py` 新增 `ui_theme` 持久化字段，`apply_app_style` 支持 `theme` 参数。
- `error_texts.py` 新增 `DOWNLOAD_PAUSED` 错误码映射。
- `_api.py` 新增 `PauseChecker` 类型别名。

### Changed

- `_workers.py` 从 `_batch_models.py` 导入并重新导出 `BatchDetectRow`、`format_bytes`、`format_duration`、`probe_media_size_bytes`，保持向后兼容。
- `_dialogs.py` 从 `_gui_styles.py` 导入样式函数，原有本地定义已移除。
- `_batch_dialogs.py` 和 `main.py` 改为直接从 `_batch_models.py` / `_gui_styles.py` 导入。
- `pyproject.toml` 新增 `_batch_models` 和 `_gui_styles` 模块声明。
- `UiSettingsDialog` 新增 `current_theme` 参数（默认 `"light"`），窗口高度略微增加以容纳主题选择器。

### QA

- 回归测试：`python3 -m pytest tests/`（159 通过，1 跳过）。

## v0.9.1 (2026-07-01)

### Fixed

- `pyproject.toml` 版本号从 0.6.0 同步到 0.9.1（之前 3 个版本遗漏同步）。
- 为 `_api.py`、`_audio.py`、`_cli.py` 添加 `__all__` 定义，`music_fetch.py` 星号导入不再泄漏内部实现。
- 修复 `_api.py` `__all__` 遗漏 `SHORT_LINK_HOSTS` 导致 `from music_fetch import *` 丢失该符号。

### Changed

- 批量检测 0 条结果时弹窗提示用户"未识别到任何歌曲"。
- 删除 `BatchDetectRow` 中未使用的 `can_download` 属性。
- 提取通用 `clamp(value, default, min_val, max_val)` 函数，统一 `app_stores.py`、`_dialogs.py`、`_batch_dialogs.py`、`_workers.py` 中约 17 处重复钳位模式。

### QA

- 回归测试：`python3 -m pytest tests/`（115 通过，1 跳过）。

## v0.9.0 (2026-07-01)

### Fixed

- 消除 `main.py` 中的星号导入（`from _dialogs import *`），改为显式导入 17 个名字。
- 定义 `error_texts.UNKNOWN_ERROR` 常量，统一 `_workers.py` 和 `_batch_dialogs.py` 中 5 处散落引用。
- 提取硬编码中文错误消息到 `ui_texts.MSG_BATCH_WORKER_UNEXPECTED`。
- `main.py:465` 设置状态文本复用 `T.status_ui_settings_updated()`。
- `main.py:230` 版本检查异常处理区分 `RuntimeError` 和网络错误。

### Changed

- 测试总数 115（+0，无新增测试）。

### QA

- 回归测试：`python3 -m pytest tests/`（115 通过，1 跳过）。

## v0.8.0 (2026-07-01)

### Added

- 歌单分页获取：`fetch_playlist_song_ids` 支持分页循环拉取，超过 1000 首的大歌单不再被静默截断。
- 批量检测并发化：`BatchInspectWorker` 使用 `ThreadPoolExecutor` 并行执行 `detect_song` 调用，大幅提升大歌单的检测速度。
- 新增 `tests/test_batch_dialogs.py`（17 个用例），覆盖选择逻辑、下载调度、历史记录和取消操作。
- 新增 `tests/test_audio.py`（12 个用例），覆盖下载流 header 轮换、HTTP/HTTPS fallback、403 重试、取消和日志脱敏。

### Fixed

- 修复 `_batch_dialogs.py` 中 `_initialized` 在 `_on_input_changed` 信号触发前未被设置的问题。

### Changed

- 测试总数从 86 增加到 115（+29 个新测试用例）。

### QA

- 回归测试：`python3 -m pytest tests/`（115 通过，1 跳过）。

## v0.7.0 (2026-07-01)

### Fixed

- 修复批量下载中 worker 线程异常结束时未写入下载历史记录的问题。
- 修复批量检测完成后无条件重置所有可下载歌曲为未选中状态的问题，现在默认保持 `BatchInspectWorker` 设置的选中状态。
- 修复 CLI 中 `--format` 参数被接受但无效的问题（移除该参数，CLI 输出固定为 mp4）。

### Changed

- `DownloadWorker` 的取消标志从普通 `bool` 改为 `threading.Event`，确保跨线程可见性。
- `BatchDownloadDialog` 中用显式 `_initialized` 标志位替换 `hasattr` 防御性检查。
- `fetch_song_metadata` 在网络错误时添加 `logger.warning` 日志，不再静默吞掉错误。
- 清理 `main.py` 中约 15 处重复的局部导入（`set_label_state` 等），移除 `_workers.py` 和 `_dialogs.py` 中未使用的导入。
- 优化 `tests/test_entrypoints.py`：删除脆弱的字符串匹配断言，为 shell wrapper 测试添加 Windows 平台跳过。

### QA

- 回归测试：`python3 -m pytest tests/`（全部通过，Windows 平台上 1 个 shell wrapper 测试正确跳过）。

## v0.6.0 (2026-05-07)

### Added

- 批量页新增“重试失败项”，仅重试 `download_failed` 行，不重新处理识别失败、不可下载、重复、取消或已成功行。
- 批量页新增 CSV 导出，字段包含来源、原始输入、歌曲信息、状态、消息、资源大小和选中状态。
- 新增 `_batch_results.py`，集中批次失败筛选、状态汇总和 CSV 生成逻辑。
- 新增 `_batch_dialogs.py`，承载批量设置与批量下载对话框。
- 新增 `tests/test_batch_results.py`，覆盖批量失败筛选、汇总和 CSV 转义。

### Fixed

- 修复主界面单曲检测入口错误导入 `InspectWorker` 导致点击检测失败的问题。
- 修复 `./music-fetch` 与 `python3 music_fetch.py` CLI 入口空跑问题。
- 修复下载完成后进入转码阶段时取消操作状态不一致的问题：取消后会清理临时文件与最终输出。
- 修正 `pyproject.toml` 打包配置，当前平铺模块结构改用显式 `py-modules` 与 `music-fetch` console script。

### Changed

- 精简历史文档：`RELEASE_NOTES_v0.4.0.md`、`RELEASE_NOTES_v0.5.0.md` 的有效信息已合并到本文件与 `ROADMAP.md`，后续以 `CHANGELOG.md` 作为唯一版本历史来源。
- 批量下载完成或停止时会附带下载失败原因聚合摘要。
- `BatchRuntimeSettingsDialog` 与 `BatchDownloadDialog` 从 `_dialogs.py` 迁移到 `_batch_dialogs.py`，降低主对话框模块体积。

### QA

- 回归测试：`python3 -m unittest discover -s tests`（87 通过）。
- 入口验证：`./music-fetch --help`、`python3 music_fetch.py --help` 均正常输出 CLI 帮助。

## v0.5.1 (2026-05-07)

### Changed

- 重构：`main.py` 拆分为 `_workers.py`(工作线程) + `_dialogs.py`(对话框)，文件从 3290 行降至 665 行。
- 重构：`music_fetch.py` 拆分为 `_api.py`(API) + `_audio.py`(下载/转码) + `_cli.py`(CLI)，原文件改为外观层。
- 常量去重：`URL_IN_TEXT_PATTERN`、`TRAILING_URL_PUNCTUATION`、`SHORT_LINK_HOSTS` 集中到 `app_settings.py`。
- Combo 工具提取到 `_combo_utils.py`，消除两处对话框间的重复代码。
- `resolve_output_path` 默认格式 `"mp4"` → `"mp3"`（与 GUI 默认一致）。

### Fixed

- 6 处 `except Exception: pass` 改为捕获具体异常类型。
- Lambda 闭包捕获循环变量改为 `functools.partial`。
- `MainWindow` 构造函数中 `QSize` 未导入导致 NameError。
- `main()` 中 `DOWNLOAD_HISTORY_FILE` 未导入导致 NameError。
- `_analyze_input_after_delay` 中 `BATCH_ROUTE_MIN_COUNT` 引用了错误的模块。

### Added

- 新增 `pyproject.toml`（项目元数据 + 依赖声明）。
- 补全 `.gitignore`（Python/IDE/缓存条目）。
- 新增 `tests/test_app_settings.py`、`tests/test_combo_utils.py`，新增 15 个测试，总数 63 → 78。
- `fetch_playlist_song_ids` 在歌曲数达到 API 上限(1000)时添加日志警告。

## v0.5.0 (2026-03-26)

版本定位：批量下载稳定版，重点是让用户可以粘贴混合链接（单曲/歌单/分享文案）并完成可中断、可继续的批量下载流程。

### Added

- 新增 `batch_inputs.py` 批量输入解析模块，支持多行混合文本中提取多个链接并去重。
- 新增 `tests/test_batch_inputs.py`，覆盖批量输入提取与去重逻辑。
- 主输入框支持多行输入；当检测到输入超过 2 条时，自动进入批量识别与批量下载流程。
- 新增歌单链接识别能力：支持 `playlist` 分享链接解析并展开歌单内歌曲。
- 批量识别支持：
  - 多行链接/分享文案识别
  - 歌单链接展开为歌曲列表后识别
  - 识别结果列表展示（来源、song_id、歌曲名、资源大小、状态）
  - 可下载项按 `song_id` 去重
- 批量下载支持对“可下载项”并发执行（并发上限来自软件设置）并写入下载历史记录。
- 批量识别列表新增“可勾选下载”与“资源大小”列，可按歌曲粒度选择下载。

### Changed

- 下载进度弹窗新增 `notify_each_result` 开关，支持批量场景下静默成功/失败提示，避免弹窗刷屏。
- “界面设置”统一更名为“软件设置”；字体与下载参数改为下拉选择，避免不合理数值输入。
- 批量下载流程改为页内执行与页内取消，不再逐首弹出二级下载弹窗。
- 当批量输入未变化且已完成识别时，“开始识别”按钮自动禁用并给出提示。
- 批量页交互优化：输入框改为随内容长度自适应高度、默认不勾选下载项并新增“全选/反选”快捷操作、取消下载按钮仅在下载中显示。
- 批量识别“来源”列支持分享文案解析（如 `歌单-xxx`、`歌曲-xxx`），并在 tooltip 保留完整原始链接文案。
- 批量识别结果表头宽度改为稳定固定布局，避免全选/反选后列宽抖动。
- 主界面底部信息改为“版本号 + GitHub 链接”；点击版本号可手动检查最新版本。
- 软件设置界面去除下载设置分组背景，下载参数下拉框统一宽度并对齐。
- 软件设置超时策略简化：检测超时固定为 `1/3/5s`，下载超时固定为 `3/5/10s`。
- 下载管理“状态筛选”下拉框加宽，并修复无记录时筛选栏位置抖动问题。
- 批量下载页新增“下载设置”入口，支持不离开批量页调整超时/重试/并发参数并继续下载剩余任务。
- 批量识别结果增加缓存恢复：同一批输入再次进入批量页时可直接复用上次识别结果，无需重新解析。

### Notes

- 操作路径：主界面输入链接后点击“检测”；多候选或歌单输入会进入批量页；批量页可调整下载设置、勾选歌曲、下载选中项或取消下载。
- 关键行为：批量下载按设置的并发上限执行；取消后可调整并发/超时参数并继续处理剩余项。

### QA

- 回归测试：`python3 -m unittest discover -s tests`（63 通过）
- Python 3.13 回归：`python3.13 -m unittest discover -s tests`（63 通过）

## v0.4.0 (2026-03-23)

版本定位：单任务下载流程的任务中心化改造，为 v0.5.0 批量下载奠定任务状态、重试和历史记录基础。

### Added

- 新增 `download_tasks.py` 任务状态模型，统一 `pending/downloading/success/failed/canceled` 状态定义。
- 新增 `ROADMAP.md`，记录 `v0.4.0` 进行中范围与 `v0.5.0` 批量下载目标。
- 新增 `tests/test_download_tasks.py`，覆盖任务状态模型与快照更新行为。
- 新增 `download_retry.py` 重试辅助逻辑与 `tests/test_download_retry.py` 对应测试。
- 下载管理新增“状态筛选”能力（全部/成功/失败/已取消/待处理/下载中）。
- 下载管理新增“重试失败任务”入口，支持单任务快速重试。
- 界面设置新增下载参数组：检测超时、下载超时、下载重试次数、并发上限（预留）。
- 新增会话参数持久化字段与范围夹紧：`detect_timeout_sec/download_timeout_sec/download_retry_count/download_concurrency`。
- 新增 `tests/test_app_stores.py` 对下载参数持久化与边界夹紧的覆盖。

### Changed

- `MainWindow` 下载主流程接入显式任务生命周期（`pending -> downloading -> success/failed/canceled`）。
- 下载进度弹窗 `result_state` 语义与任务状态模型统一（`success/failed/canceled`）。
- 下载历史存储结构扩展 `status/error_code`，并保持旧数据向后兼容。
- 下载、重试与进度弹窗关键日志统一附带 `task_id`，提升问题排查可追踪性。
- 检测与下载流程改为使用用户可配置超时；下载流程支持可配置重试次数（仅对网络/下载失败重试）。

### QA

- 回归测试：`python3 -m unittest discover -s tests`（44 通过）
- Python 3.13 回归：`python3.13 -m unittest discover -s tests`（44 通过）

## v0.3.0 (2026-03-08)

### Added

- 新增 `界面设置` 弹窗，支持调整全局字体大小（12px~20px）并持久化到会话配置。
- 新增链接输入实时校验提示，覆盖空输入、ID 识别、短链识别、域名限制和缺失歌曲 ID 场景。
- 新增主界面可访问性标注（关键控件 `AccessibleName`）与回车触发检测能力。

### Changed

- 开发环境切换为优先使用 `Python 3.13`，启动脚本优先选择 3.13 解释器但保留 Python 3 兼容回退。
- 统一弹窗次级操作为“返回”按钮，并固定主/次按钮视觉层级（主按钮高亮）。
- 引入全局 UI 设计令牌样式：统一按钮高度、输入框高度、焦点高亮、状态色规范。
- 主页面检测按钮改为状态驱动启用：仅在“已登录 + 输入合法 + 非忙碌”时可点击。
- 下载设置弹窗增加就地表单反馈，参数不完整时禁用“开始下载”。
- 字体大小设置交互由下拉框调整为步进输入（`QSpinBox`），避免部分系统下列表悬停渲染异常。

### Fixed

- 修复旧会话配置缺失新字段时的兼容性问题（字体大小自动回退默认值）。
- 修复会话中异常字体值导致界面显示不一致的问题（读写均做范围夹紧）。
- 修复“依赖管理”弹窗底部按钮行不齐平的问题（刷新/返回垂直对齐）。
- 修复 SSL 证书链异常场景下提示文案不明确的问题（明确指向证书/代理配置）。

## v0.2.0 (2026-03-08)

### Added

- 新增 `依赖管理` 入口与详情弹窗，展示依赖状态、功能影响、安装方法。
- 新增跨平台启动脚本：
  - `start_mac.command`（macOS）
  - `start_windows.bat`（Windows）
- 新增 `ffmpeg` 缺失时的下载前确认流程（继续 MP3 / 取消本次下载）。

### Changed

- 登录流程调整为网页扫码优先，移除手动输入 Cookie 的交互入口。
- 登录窗口默认尝试聚焦“扫码登录”入口，并按屏幕尺寸自适应窗口大小。
- 链接输入区去掉无效问号按钮，改为固定示例链接与提示说明。
- 下载候选优先匹配目标格式，降低转码触发概率。

### Fixed

- 修复“退出账号后内嵌网页登录仍保留登录态”导致切换账号异常的问题。
- 修复未安装 `ffmpeg` 时部分歌曲直接失败的问题：支持按源格式兜底保存。
- 修复部分 `403 + outer-url 不可用` 场景错误分类不准确的问题，归类为 `SONG_UNAVAILABLE`。

### Docs

- 更新 `README.md`：补齐 v0.2.0 功能说明、依赖管理与启动方式。
- 新增 `CONTRIBUTING.md`：统一提交信息模板（含文件级变更说明）。

## v0.1.0 (2026-03-08)

- 初始版本：GUI 下载主流程、账号信息展示、链接解析、下载管理、格式转换、日志体系与基础测试。
