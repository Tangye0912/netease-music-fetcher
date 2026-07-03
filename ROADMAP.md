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

## v0.11.0 (Next)

### Goal

- 完成暂停/恢复 UI 集成，补齐 CLI 与 GUI 功能差距，继续拆分大模块。

### Phase 1 — 功能优先

- [x] 暂停/恢复 UI 集成（v0.11.0 已完成）：`DownloadProgressDialog` 和 `BatchDownloadDialog` 添加暂停/恢复按钮，连接 `worker.paused` 信号，新增 `ui_texts` 文案。
- [x] CLI 补全：重新添加 `--format` 参数（v0.11.0 已完成）（支持 `mp3/m4a/wav/flac/aac`），播放列表/批量下载支持，`download_song_with_fallback` 替代 `fetch_playable_url`。
- [x] 补 `_batch_models.py` 单元测试（v0.11.0 已完成）：`format_duration`、`format_bytes`、`probe_media_size_bytes` 零覆盖 → 补全。
- [x] 修复 `_cli.py:75` 裸 `except Exception`（v0.11.0 已完成），改为捕获具体异常类型。

### Phase 2 — 重构与清理

- [x] 拆分 `_dialogs.py`：`LoginDialog` 已提取到 `_dialog_login.py`（v0.11.0 已完成）、`DownloadProgressDialog`、`DownloadManagerDialog` 等独立对话框类提取到 `_dialog_login.py`、`_dialog_progress.py`、`_dialog_manager.py`。
- [ ] 拆分 `_batch_dialogs.py`：将 `BatchRuntimeSettingsDialog` 与 `BatchDownloadDialog` 分离到独立文件。
- [x] 消除重复设置钳位模式：提取 `clamp_download_settings`（v0.11.0 已完成）：`_batch_dialogs.py` 和 `_dialogs.py` 中相同的 4 字段 clamp 初始化 → 提取 `SettingsBundle` 或 `clamp_settings` 辅助函数。
- [ ] 提取 `main.py` 中版本检查逻辑（`fetch_latest_project_version`、`version_key`）到独立模块。
- [x] `_api.py` 返回类型精确化：`dict` → `dict[str, object]`（v0.11.0 已完成）：`dict` → `dict[str, Any]`。

## v0.6.0 (Completed - 2026-05-07)

### Goal

- 在已完成批量并发下载与 0.5.1 技术债修复基础上，继续提升异常批次的可恢复能力、结果可读性与工程边界清晰度。

### Scope

- [x] 批量下载“仅重试失败项”一键入口。
- [x] 批次结果汇总（按失败原因分组统计）。
- [x] 批次导出（CSV 成功/失败明细）。
- [x] 继续拆分 `_dialogs.py`：批量下载对话框与批量运行时设置已迁移到 `_batch_dialogs.py`。
- [x] 为 GUI 关键回调增加轻量 smoke test，覆盖 CLI 入口、单曲检测 worker 导入与批量入口导入。
- [x] 暂不迁移到真正的 `music_fetch/` 包目录，保持 `pyproject.toml` 的 `py-modules` 清单同步。
