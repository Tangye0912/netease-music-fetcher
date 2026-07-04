# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；不要再为单个历史版本新增独立 release notes。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口，避免复制完整版本说明。
- `ROADMAP.md` 只记录规划和仍需推进的技术方向；已完成细节沉淀到 `CHANGELOG.md`。
- 每条功能改动必须补对应测试（单元测试或流程测试）。
- 发现未使用代码或文档时，优先删除；若需要保留历史兼容，再显式说明原因。

## v0.7.0 (Completed - 2026-07-01)

### Goal

- 修复已知 bug，清理技术债，为后续版本奠定代码质量基础。

### Scope

- [x] 修复批量下载 worker 异常结束遗漏历史记录。
- [x] 修复批量检测后无条件重置选中状态。
- [x] CLI 移除无效的 `--format` 参数。
- [x] 下载取消标志改用 `threading.Event`。
- [x] 清理 `main.py` 约 15 处重复局部导入，移除未使用导入。
- [x] `fetch_song_metadata` 网络错误时添加日志。

## v0.8.0 (Completed - 2026-07-01)

### Goal

- 补核心功能缺口（歌单分页），提升批量检测性能，大幅增加测试覆盖。

### Scope

- [x] 歌单分页获取：`fetch_playlist_song_ids` 支持分页循环拉取，大歌单不再截断。
- [x] 批量检测并发化：`BatchInspectWorker` 使用 `ThreadPoolExecutor` 并行 `detect_song`。
- [x] 新增 `tests/test_batch_dialogs.py`（17 个用例），覆盖选择、调度、历史、取消。
- [x] 新增 `tests/test_audio.py`（12 个用例），覆盖 header 轮换、403 重试、取消、日志脱敏。

## v0.9.0 (Completed - 2026-07-01)

### Goal

- 消除阻断级技术债，清理星号导入、硬编码中文、异常处理。

### Scope

- [x] 消除 `main.py` 星号导入，改为显式导入 17 个名字。
- [x] 定义 `error_texts.UNKNOWN_ERROR` 常量，统一 5 处散落引用。
- [x] 提取硬编码中文错误消息到 `ui_texts.py`。
- [x] 版本检查异常处理区分 `RuntimeError` 和网络错误。
- [x] 设置状态文本复用 `T.status_ui_settings_updated()`。

## v0.10.0 (Completed - 2026-07-03)

### Goal

- 继续清理技术债，降低模块耦合度，补测试覆盖。

### Scope

- [x] 提取通用 `clamp` 函数，消除 17 处重复钳位模式。（v0.9.1 已完成）
- [x] 消除 `BatchRuntimeSettingsDialog` 和 `UiSettingsDialog` 的重复钳位逻辑。（v0.9.1 已完成）
- [x] 拆分 `_workers.py` 中工具函数和模型到 `_batch_models.py`。（v0.10.0 已完成）
- [x] 拆分 `_dialogs.py` 中样式工具到 `_gui_styles.py`。（v0.10.0 已完成）
- [x] 补 `_dialogs.py` 中 7 个对话框类的单元测试。（v0.10.0 已完成）
- [x] 下载队列暂停/恢复与断点续传。（v0.10.0 已完成）
- [x] 软件设置增加暗色主题切换。（v0.10.0 已完成）

## v0.11.0 (Completed - 2026-07-03)

### Goal

- 完成暂停/恢复 UI 集成，补齐 CLI 与 GUI 功能差距，继续拆分大模块。

### Phase 1 — 功能优先

- [x] 暂停/恢复 UI 集成（v0.11.0 已完成）
- [x] CLI 补全：`--format`、`--rename`、播放列表批量下载、`download_song_with_fallback`（v0.11.0 已完成）
- [x] 补 `_batch_models.py` 单元测试（v0.11.0 已完成）
- [x] 修复 `_cli.py` 裸 `except Exception`（v0.11.0 已完成）

### Phase 2 — 重构与清理

- [x] 拆分 `_dialogs.py`：`LoginDialog` → `_dialog_login.py`（v0.11.0 已完成）
- [x] 消除重复设置钳位模式：`clamp_download_settings`（v0.11.0 已完成）
- [x] `_api.py` 返回类型精确化（v0.11.0 已完成）

## v0.12.0 (Next)

### Goal

- 修复已知 bug，清理硬编码中文，继续拆分大模块，补测试和类型覆盖。

### Bug 修复

- [x] 修复暂停后取消时 `.part` 文件残留（v0.12.0 已完成）：`_stop_download_flow` 应清理暂停 worker 的 `.part` 临时文件。
- [x] 修正 ROADMAP v0.11.0 中 `DownloadProgressDialog`（v0.12.0 已完成）/`DownloadManagerDialog` 误标为已完成 → 实际未拆分。

### 硬编码清理

- [x] `_batch_dialogs.py` 硬编码中文状态消息提取到 `ui_texts`（v0.12.0 已完成）（`下载设置已更新`、`并发 N 路`、`已完成` 等）。
- [x] `main.py` 硬编码中文状态消息提取到 `ui_texts`（v0.12.0 已完成）（`发现新版本`、`已是最新版本`、`下载完成`、`网络错误`）。
- [x] `_batch_dialogs.py` / `_dialogs.py` 中 `"次"` / `"路"` 后缀提取到 `ui_texts`（v0.12.0 已完成）。

### 模块拆分

- [x] 拆分 `_dialogs.py`：`DownloadProgressDialog` → `_dialog_progress.py`（v0.12.0 已完成），`DownloadManagerDialog` → `_dialog_manager.py`。
- [x] 拆分 `_batch_dialogs.py`：`BatchRuntimeSettingsDialog` → `_dialog_batch_settings.py`（v0.12.0 已完成）。
- [x] 提取 `main.py` 中版本检查逻辑（v0.12.0 已完成）（`fetch_latest_project_version`、`version_key`）到 `_version_check.py`。

### 测试与质量

- [x] 补 `__all__` 定义（v0.12.0 已完成）：`_batch_dialogs.py`、`_dialogs.py`、`_dialog_login.py`、`_batch_models.py`、`_batch_results.py`、`_gui_styles.py`、`_combo_utils.py`。
- [x] 补 `app_logging.py` 单元测试（v0.12.0 已完成）。
- [x] CLI 添加 `--retry` 参数（v0.12.0 已完成）。
- [x] 清理 `_cli.py` 中无效的 `argparse.ArgumentError` 捕获（v0.12.0 已完成）。

## v1.0.0 (Completed - 2026-07-04)

### Goal

- 1.0.0 就绪：修复阻塞性 bug、收紧公开 API、补文档和测试、清理代码质量。

### Must-fix

- [x] 修复 music-fetch shell wrapper（v1.0.0 已完成） 引用 -m _cli 改为 -m music_fetch.cli。
- [x] 收紧 music_fetch/__init__.py（v1.0.0 已完成） 公开 API，移除 perform_json_post 等内部实现。
- [x] README 添加 pre-package（v1.0.0 已完成） 到 package 迁移指南。

### Should-fix

- [x] MusicFetchError 构造改用 ErrorCode（v1.0.0 已完成） 枚举成员。
- [x] from music_fetch import X 间接导入（v1.0.0 已完成）改为直接子模块导入。
- [x] load_cookie 添加 UnicodeDecodeError（v1.0.0 已完成） 捕获。
- [x] 下载目录不可写映射为友好错误码（v1.0.0 已完成）。
- [x] 补 main.py / dialog_manager.py（v1.0.0 已完成） / gui_styles.py / pipeline.py 测试。
- [x] PySide6 版本约束加（v1.0.0 已完成） <7.0 上限。

### Nice-to-have

- [ ] 删除根目录空 __init__.py。
- [ ] batch_dialogs.py 的 type: ignore[override] 迁移到全局配置。
- [ ] playlist 下载中途网络断开时保留已获取 ID。
- [ ] CLI ffmpeg 缺失时提示输出格式已降级。

## v0.14.0 (Completed - 2026-07-04)

### Goal

- 结构性大升级：包迁移、错误处理重构、下载管道抽象，为 1.0.0 奠定基础。

### Scope

- [x] 包结构迁移：26 个平铺模块迁移到 music_fetch/ 包，music_fetch.py 替换为 __init__.py。
- [x] 错误处理重构：ErrorCode 枚举 + DownloadCanceled/DownloadPaused 专用异常。
- [x] 下载管道抽象：DownloadPipeline 纯逻辑类，GUI/CLI 统一下载逻辑。

## v0.13.0 (Completed - 2026-07-03)

### Goal

- 修复 v0.12.0 遗留的 HIGH 严重度 bug，补关键模块测试，继续 UI 完善。

### Bug 修复（HIGH）

- [x] 修复 `_dialog_batch_settings.py:96` `NameError`（v0.13.0 已完成）：`set_label_state` 未导入。
- [x] 修复 CLI `--retry` 参数死代码（v0.13.0 已完成）：`run_download`/`run_playlist_download` 未接收 `retry_count`，`download_song_with_fallback` 无重试循环。

### 测试补全

- [x] 补 `_cli.py` 单元测试（v0.13.0 已完成）（`run_download`、`run_playlist_download`、`build_parser`、`main`）。
- [x] 补 `_version_check.py` 单元测试（v0.13.0 已完成）（`version_key`、`fetch_latest_project_version`）。
- [x] 补 `_dialog_batch_settings.py` 单元测试（v0.13.0 已完成）（`BatchRuntimeSettingsDialog`）。

### UI 与代码完善

- [x] 修复 `_dialog_progress.py` 恢复后状态标签（v0.13.0 已完成）显示 `"准备下载..."` → 应显示 `"下载恢复中..."`。
- [x] 清理 `_dialogs.py` 中 `.replace("状态：", "")` hack（v0.13.0 已完成），为 `status_ui_settings_updated` 添加 `prefix` 参数。
- [x] 清理 `main.py` 未使用导入（v0.13.0 已完成）：`json`、`time`、`parse`、`request`。
- [x] 暗色主题补全（v0.13.0 已完成）：`QScrollBar`、`QToolTip`、`QStatusBar` 样式。

### Goal

- 在已完成批量并发下载与 0.5.1 技术债修复基础上，继续提升异常批次的可恢复能力、结果可读性与工程边界清晰度。

### Scope

- [x] 批量下载“仅重试失败项”一键入口。
- [x] 批次结果汇总（按失败原因分组统计）。
- [x] 批次导出（CSV 成功/失败明细）。
- [x] 继续拆分 `_dialogs.py`：批量下载对话框与批量运行时设置已迁移到 `_batch_dialogs.py`。
- [x] 为 GUI 关键回调增加轻量 smoke test，覆盖 CLI 入口、单曲检测 worker 导入与批量入口导入。
- [x] 暂不迁移到真正的 `music_fetch/` 包目录，保持 `pyproject.toml` 的 `py-modules` 清单同步。
