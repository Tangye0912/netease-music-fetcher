# music-fetch

网易云音乐单曲下载工具。
当前版本以 GUI 为主流程，默认输出格式为 `mp3`。

## 1. 版本概览（v1.10.0）

### 1.1 近期更新（v1.4.2 → 当前版本）

- **统一代理支持**（v1.10.0）：GUI/CLI 支持 HTTP、SOCKS5、可选认证和远程 DNS，API、短链、头像、音频、封面及版本检查共用同一传输层。
- **批量识别可取消**（v1.9.0）：识别大歌单时可随时取消，保留已完成结果并支持直接下载或重新识别。
- **Material Design UI**（v1.9.0）：在浅色/深色主题基础上加入卡片式主界面、语义状态色和统一控件细节。
- **歌词下载**（v1.7.0）：`--lyric` 参数，下载 `.lrc` 歌词文件并嵌入音频标签（MP3/M4A/FLAC）。
- **macOS CI 构建**（v1.6.0）：GitHub Actions 双平台（Windows + macOS）自动打包。
- **mypy strict mode**（v1.5.0）：28 个源文件零类型错误，`pyproject.toml` 启用 `strict = true`。
- **CI 矩阵策略**：串行构建避免抢 runner 超时，只在推送 `v*` tag 时触发。
- **测试**：396 个测试用例，覆盖 API、代理传输、下载管道、对话框、CLI、版本检查和主窗口结构等。

详细发布记录见 [CHANGELOG.md](./CHANGELOG.md)。
迭代路线见 [ROADMAP.md](./ROADMAP.md)。

### 1.2 当前核心能力

- 登录：内嵌网页扫码登录（自动提取登录凭证）
- 主界面：展示账号头像、昵称、会员状态
- 链接检测：支持长链、短链（`163cn.tv`）、整段分享文案
- 资源类型：支持单曲链接与歌单链接
- 批量流程：多条输入解析、结果去重、识别取消与部分结果保留、并发下载、取消/暂停/恢复
- 下载：支持选择目录、重命名、格式选择（`mp3/m4a/wav/flac/aac`）
- 歌词：`--lyric` 下载 `.lrc` 文件并嵌入音频标签
- 下载管理：状态筛选、重试失败任务、打开目录、删除记录、导出 CSV
- 搜索下载：直接搜索歌名/歌手名下载
- 用户歌单：登录后浏览歌单一键下载
- 依赖降级：未安装 `ffmpeg` 时自动回退 `mp3` 并限制转码选项
- 主题：Material Design 浅色/深色主题切换
- 系统托盘：最小化到托盘，下载完成通知
- 剪贴板检测：自动检测剪贴板中的网易云链接
- 窗口记忆：主窗口位置和大小持久化
- 日志：全链路记录，敏感值脱敏，CLI 支持 `--verbose`/`--debug`
- 网络代理：软件设置支持 HTTP/SOCKS5 与可选认证；SOCKS5 默认由代理端解析域名

## 2. 环境准备

建议开发环境：`Python 3.10+`

```bash
python3 -m pip install -e ".[dev]"
```

如果要做格式转换（例如 `m4a -> mp3/wav/flac`），还需要安装 `ffmpeg`。

## 3. 启动方式

### GUI

```bash
python3 -m music_fetch.main
```

或双击 `start_windows.bat`（Windows）/ `start_mac.command`（macOS）。

### CLI

```bash
music-fetch --url "https://music.163.com/song?id=33894312"
```

可选参数：

```bash
music-fetch \
  --url "https://music.163.com/song?id=33894312" \
  --out "./downloads" \
  --cookie-file "~/.config/music-fetch/cookies.txt" \
  --format mp3 \
  --rename "自定义文件名" \
  --retry 3 \
  --timeout 30 \
  --lyric \
  --verbose
```

CLI 代理示例（密码通过环境变量传入，避免出现在进程参数中）：

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
git tag v1.10.0
git push origin v1.10.0
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
| `music_fetch/main.py` | GUI 主入口，负责登录态检查、主窗口、单曲流程入口和批量页入口。 |
| `music_fetch/dialogs.py` | 通用 GUI 对话框（单曲确认、下载选项、依赖管理、软件设置）和输入校验。 |
| `music_fetch/batch_dialogs.py` | 批量识别与批量下载界面，包含失败项重试、CSV 导出和并发下载调度。 |
| `music_fetch/batch_results.py` | 批量结果纯逻辑：失败项筛选、状态汇总、失败原因聚合、CSV 文本生成。 |
| `music_fetch/workers.py` | 后台 QThread：单曲识别、批量识别、下载执行（含暂停/恢复/取消）。 |
| `music_fetch/api.py` | 网易云接口层：链接解析、cookie 处理、登录校验、歌曲/歌单/账号/歌词 API。 |
| `music_fetch/audio.py` | 音频下载与处理：候选下载、403 fallback、断点续传、格式推断、ffmpeg 转码、歌词嵌入。 |
| `music_fetch/pipeline.py` | 下载管道：纯逻辑重试+转码编排，GUI 和 CLI 共享。 |
| `music_fetch/cli.py` | CLI 命令行入口，支持单曲/播放列表下载、`--lyric`/`--verbose`/`--debug`。 |
| `music_fetch/__init__.py` | 包外观层，重新导出公共 API。 |
| `music_fetch/batch_models.py` | 批量数据模型（`BatchDetectRow`）和格式化工具。 |
| `music_fetch/gui_styles.py` | 基于 qt-material 的应用级浅/深色设计系统，统一卡片、控件、按钮角色和状态反馈。 |
| `music_fetch/dialog_login.py` | 登录对话框：内嵌网页扫码登录、cookie 提取与校验，以及 WebEngine 生命周期清理。 |
| `music_fetch/dialog_progress.py` | 单曲下载进度对话框：进度条、暂停/恢复、取消。 |
| `music_fetch/dialog_manager.py` | 下载管理对话框：历史记录浏览、状态筛选、文件操作、失败重试。 |
| `music_fetch/dialog_batch_settings.py` | 批量运行时设置对话框：超时/重试/并发参数调整。 |
| `music_fetch/version_check.py` | GitHub API 版本检查：获取最新 release/tag。 |
| `music_fetch/combo_utils.py` | `QComboBox` 构建、取值和就近选择辅助。 |
| `music_fetch/app_settings.py` | 全局常量：版本号、默认路径、超时/重试/并发范围、URL 匹配规则。 |
| `music_fetch/app_stores.py` | 本地持久化：登录会话、下载历史。 |
| `music_fetch/app_logging.py` | 日志路径、日志初始化和敏感值脱敏。 |
| `music_fetch/network.py` | 统一网络传输：直连、HTTP/SOCKS5 代理、认证、远程 DNS 和 urllib 兼容响应。 |
| `music_fetch/batch_inputs.py` | 批量输入解析：多行链接、分享文案、歌单/歌曲来源提示和去重。 |
| `music_fetch/download_tasks.py` | 下载任务状态模型与最新任务快照。 |
| `music_fetch/download_retry.py` | 下载管理中失败任务重试的状态判断和目标格式推断。 |
| `music_fetch/error_texts.py` | 错误码到用户友好提示的映射。 |
| `music_fetch/ui_texts.py` | GUI 用户可见文案集中管理。 |
| `music_fetch/search_dialog.py` | 搜索对话框：按关键词搜索歌曲并下载。 |
| `music_fetch/playlist_dialog.py` | 用户歌单对话框：浏览登录用户的歌单并一键下载。 |
| `music-fetch` | macOS/Linux CLI 包装脚本。 |
| `start_mac.command` | macOS 双击启动 GUI 脚本。 |
| `start_windows.bat` | Windows 双击启动 GUI 脚本。 |
| `pyproject.toml` | Python 项目元数据、依赖声明（`PySide6`、`mutagen`、`qt-material`、`requests[socks]`）。 |
| `tests/` | 396 个单元/回归测试。 |
| `CHANGELOG.md` | 唯一版本历史来源。 |
| `ROADMAP.md` | 版本规划与后续技术债方向。 |

## 7. 测试

```bash
python3 -m pytest tests/ -q
```

## 8. 日志与排障

- 默认日志：`~/.config/music-fetch/logs/music-fetch.log`
- GUI 和 CLI 共用日志体系
- 日志不会打印完整 `MUSIC_U` 值（已脱敏）

## 9. 合规说明

仅用于你已获得合法授权的音频素材。
本工具不提供 DRM/版权绕过能力。
