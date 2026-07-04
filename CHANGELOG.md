# Changelog

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
