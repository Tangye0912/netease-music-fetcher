# music-fetch

网易云音乐单曲下载工具。  
当前版本以 GUI 为主流程，默认输出格式为 `mp3`。

## 1. 版本概览（v1.0.0）

### 1.1 近期更新（v0.10.0 → v1.0.0）

- **模块拆分**：新增 `_batch_models.py`、`_gui_styles.py`、`_dialog_login.py`、`_dialog_progress.py`、`_dialog_manager.py`、`_dialog_batch_settings.py`、`_version_check.py`，`_dialogs.py` 和 `_batch_dialogs.py` 体积大幅缩减。
- **暂停/恢复**：`DownloadWorker` 支持暂停/恢复与断点续传（`Range` 请求头），GUI 已集成暂停/恢复按钮。
- **暗色主题**：软件设置中可切换浅色/深色主题（Catppuccin 风格），持久化到 `ui_theme`。
- **CLI 补全**：新增 `--format`（mp3/m4a/wav/flac/aac）、`--rename`、`--retry` 参数，支持播放列表批量下载，改用 `download_song_with_fallback`。
- **测试**：从 115 → 206 个测试用例，覆盖 `_dialogs.py`、`_batch_models.py`、`app_logging.py` 等。
- **代码质量**：消除硬编码中文、统一 `__all__` 定义、消除重复钳位模式、类型精确化。
- **架构升级（v0.14.0）**：迁移到 `music_fetch/` 包目录，`ErrorCode` 错误码枚举，`DownloadPipeline` 统一下载管道，`DownloadCanceled`/`DownloadPaused` 专用控制流异常。

详细发布记录见 [CHANGELOG.md](./CHANGELOG.md)。  
迭代路线与后续技术债规划见 [ROADMAP.md](./ROADMAP.md)。  
提交说明模板见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

### 1.2 当前核心能力

- 登录：内嵌网页扫码登录（自动提取登录凭证）
- 主界面：展示账号头像、昵称、会员状态
- 链接检测：支持长链、短链（`163cn.tv`）、整段分享文案
- 资源类型：支持单曲链接与歌单链接
- 批量流程：支持多条输入解析、结果去重、勾选下载、并发下载、取消下载
- 下载：支持选择目录、重命名、格式选择（`mp3/m4a/wav/flac/aac`）
- 下载管理：支持状态筛选、重试失败任务、打开目录、删除记录
- 依赖降级：未安装 `ffmpeg` 时自动回退 `mp3` 并限制转码选项
- 日志：关键流程全链路记录，便于排障
- 主题：支持浅色/深色主题切换
- 暂停/恢复：下载队列支持暂停/恢复与断点续传

### 1.3 下一版本计划

- 下载队列可视化进度条优化
- 批量下载暂停/恢复 UI 交互完善（按钮状态切换、暂停行高亮等）
- 为 1.0.0 做准备：API 稳定性、文档完善、打包分发

## 2. 环境准备

> **从 v0.13 及更早版本升级？** v0.14.0 将模块迁移到了 `music_fetch/` 包目录。如果你有自定义脚本使用了 `import _api` 或 `from _workers import DownloadWorker`，请改为 `from music_fetch.api import ...` 或 `from music_fetch.workers import DownloadWorker`。`import music_fetch` 顶层导入保持不变。

建议开发环境：`Python 3.13`（运行时按依赖实际兼容为准）

```bash
python3 -m pip install PySide6
```

如果要做格式转换（例如 `m4a -> mp3/wav/flac`），还需要安装 `ffmpeg`。
未安装时，开始下载前会弹出确认框（继续则保持 `mp3`，取消则终止本次下载），并在下载设置里自动只保留 `mp3` 可选。
若歌曲源格式与目标格式不一致且未安装 `ffmpeg`，程序会自动按源格式保存并给出提示。

## 3. 启动方式（跨平台）

### macOS（推荐双击）

- 双击项目根目录下的 `start_mac.command`
- 或终端执行：

```bash
cd /path/to/music-fetch
python3 -m music_fetch.main
```

### Windows（推荐双击）

- 双击项目根目录下的 `start_windows.bat`
- 或终端执行：

```bat
cd /d D:\path\to\music-fetch
py -3 -m music_fetch.main
```

## 4. GUI 使用流程

### 单曲下载

1. 启动后自动检测登录态。  
2. 未登录/已过期时，弹出扫码登录窗口。  
3. 登录成功后进入主界面，可看到头像、昵称、会员信息。  
4. 可通过"依赖管理"查看 `ffmpeg` 状态与安装建议。  
5. 点击头像菜单可切换账号或退出账号（退出会同步清理内嵌网页登录态）。  
6. 输入歌曲链接并点击"检测"。  
7. 在确认窗口点击"下载"。  
8. 选择保存目录、文件名、目标格式（默认 `mp3`）。  
9. 查看下载进度，完成后弹出文件路径。  
10. 通过"下载管理"查看历史与文件操作。  

### 批量下载

1. 在主界面输入多行链接/分享文案（或粘贴含多条链接的混合文本）。  
2. 点击"检测"自动进入批量页面。  
3. 批量页在后台并发检测所有歌曲，可下载项默认勾选。  
4. 可全选/反选/逐条勾选，调整下载目录和格式。  
5. 点击"下载选中项"开始并发下载。  
6. 下载中可取消，完成后可重试失败项或导出 CSV 结果。  

输入区支持直接粘贴分享文案，程序会自动提取其中链接并识别资源类型。

## 5. CLI 使用（保留）

```bash
./music-fetch --url "https://music.163.com/#/song?id=33894312"
```

可选参数：

```bash
./music-fetch \
  --url "https://music.163.com/song?id=33894312" \
  --out "./downloads" \
  --cookie-file "~/.config/music-fetch/cookies.txt" \
  --timeout 30
```

说明：CLI 和 GUI 均支持 `mp3/m4a/wav/flac/aac` 多种格式，CLI 默认 `mp3`。播放列表链接会自动展开并逐首下载。

## 6. 错误码

- `INVALID_URL`：链接无效或无法解析歌曲 ID
- `AUTH_EXPIRED`：登录态缺失或过期
- `SONG_UNAVAILABLE`：歌曲不可下载（版权/地区/VIP）
- `NETWORK_ERROR`：网络或接口异常
- `DOWNLOAD_FAILED`：下载请求失败
- `DOWNLOAD_CANCELED`：用户主动取消下载
- `CONVERT_TOOL_MISSING`：缺少 ffmpeg，无法执行格式转换
- `CONVERT_FAILED`：音频格式转换失败
- `UNSUPPORTED_FORMAT`：不支持的输出格式
- `DOWNLOAD_PAUSED`：下载已暂停
- `UNKNOWN_ERROR`：未预期异常

## 7. 项目架构

GitHub 文件列表右侧展示的是“最后修改该文件的提交信息”，不是文件职责说明；文件职责以本节为准。

| 路径 | 职责 |
| --- | --- |
| `music_fetch/main.py` | GUI 主入口，负责登录态检查、主窗口、单曲流程入口和批量页入口。 |
| `music_fetch/dialogs.py` | 通用 GUI 对话框（单曲确认、下载选项、依赖管理、软件设置）和输入校验。 |
| `music_fetch/batch_dialogs.py` | 批量识别与批量下载界面，包含失败项重试、CSV 导出和并发下载调度。 |
| `music_fetch/batch_results.py` | 批量结果纯逻辑：失败项筛选、状态汇总、失败原因聚合、CSV 文本生成。 |
| `music_fetch/workers.py` | 后台 QThread：单曲识别、批量识别、下载执行（含暂停/恢复/取消）。 |
| `music_fetch/api.py` | 网易云接口层：链接解析、cookie 处理、登录校验、歌曲/歌单/账号 API。 |
| `music_fetch/audio.py` | 音频下载与处理：候选下载、403 fallback、断点续传、格式推断、ffmpeg 转码。 |
| `music_fetch/pipeline.py` | 下载管道：纯逻辑重试+转码编排，GUI 和 CLI 共享。 |
| `music_fetch/cli.py` | CLI 命令行入口，支持单曲/播放列表下载。 |
| `music_fetch/__init__.py` | 包外观层，重新导出 `api`/`audio`/`cli` 的公共 API。 |
| `music_fetch/batch_models.py` | 批量数据模型（`BatchDetectRow`）和格式化工具。 |
| `music_fetch/gui_styles.py` | QSS 样式表构建（浅色/深色主题）、按钮角色和标签状态辅助。 |
| `music_fetch/dialog_login.py` | 登录对话框：内嵌网页扫码登录，cookie 提取与校验。 |
| `music_fetch/dialog_progress.py` | 单曲下载进度对话框：进度条、暂停/恢复、取消。 |
| `music_fetch/dialog_manager.py` | 下载管理对话框：历史记录浏览、状态筛选、文件操作、失败重试。 |
| `music_fetch/dialog_batch_settings.py` | 批量运行时设置对话框：超时/重试/并发参数调整。 |
| `music_fetch/version_check.py` | GitHub API 版本检查：获取最新 release/tag。 |
| `music_fetch/combo_utils.py` | `QComboBox` 构建、取值和就近选择辅助。 |
| `music_fetch/app_settings.py` | 全局常量：版本号、默认路径、超时/重试/并发范围、URL 匹配规则。 |
| `music_fetch/app_stores.py` | 本地持久化：登录会话、下载历史、状态字段兼容和边界值夹紧。 |
| `music_fetch/app_logging.py` | 日志路径、日志初始化和敏感值脱敏。 |
| `music_fetch/batch_inputs.py` | 批量输入解析：多行链接、分享文案、歌单/歌曲来源提示和去重。 |
| `music_fetch/download_tasks.py` | 下载任务状态模型与最新任务快照。 |
| `music_fetch/download_retry.py` | 下载管理中失败任务重试的状态判断和目标格式推断。 |
| `music_fetch/error_texts.py` | 错误码到用户友好提示的映射。 |
| `music_fetch/ui_texts.py` | GUI 用户可见文案集中管理。 |
| `music-fetch` | macOS/Linux CLI 包装脚本。 |
| `start_mac.command` | macOS 双击启动 GUI 脚本。 |
| `start_windows.bat` | Windows 双击启动 GUI 脚本。 |
| `pyproject.toml` | Python 项目元数据、依赖声明、console script 和包声明。 |
| `tests/` | 206 个单元/回归测试。 |
| `README.md` | 用户入口文档：能力说明、启动方式、架构和维护约定。 |
| `CHANGELOG.md` | 唯一版本历史来源。 |
| `ROADMAP.md` | 版本规划与后续技术债方向。 |
| `CONTRIBUTING.md` | 提交信息模板和提交前检查命令。 |
| `.gitignore` | 忽略缓存、日志、本地配置和系统生成物。 |

依赖方向（自底向上）：
```
app_settings → app_logging → app_stores / batch_inputs / download_tasks / error_texts / ui_texts
  → [ api → audio → pipeline → cli ]
  → workers / batch_results → dialogs / batch_dialogs → main
```

新增功能优先复用已有模块，避免业务代码继续写硬编码。

## 8. 文档与维护约定

- `README.md`：用户入口、功能概览、启动方式、项目结构与测试命令。
- `CHANGELOG.md`：唯一版本历史来源；历史 release notes 已合并到这里。
- `ROADMAP.md`：后续规划与仍需推进的技术债。
- `CONTRIBUTING.md`：提交信息模板与提交前检查命令。
- `tests/`：回归测试目录，不属于可清理文档；新增行为变更时优先补这里。

## 9. 提交规范（建议）

后续提交建议使用“标题 + 文件级变更说明”：

```text
feat: 简要说明这次迭代目标

- main.py: 调整登录窗口与输入区交互
- ui_texts.py: 更新弹窗与状态文案
- README.md: 更新启动方式与功能说明
```

这样新同学能快速理解“每个文件改了什么、为什么改”。
完整模板见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 10. 测试

```bash
python3 -m pytest tests/ -q
```

## 11. 日志与排障

- 默认日志：`~/.config/music-fetch/logs/music-fetch.log`
- GUI 和 CLI 共用日志体系
- 记录节点：登录检测、短链解析、资源检测、下载开始/失败/完成、下载管理操作
- 直链被 CDN 403 拒绝时，会自动尝试 `outer/url` 兜底
- 日志不会打印完整 `MUSIC_U` 值（已脱敏）

## 12. 合规说明

仅用于你已获得合法授权的音频素材。  
本工具不提供 DRM/版权绕过能力。
