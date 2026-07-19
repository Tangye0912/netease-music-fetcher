# Roadmap

## Maintenance Rules

- `CHANGELOG.md` 是唯一版本历史来源；已完成内容不再重复保留在 ROADMAP。
- `README.md` 只保留用户启动、功能概览、项目结构和测试入口。
- `ROADMAP.md` 只记录尚未完成、可以验证的后续工作。
- 每条行为改动必须补对应测试，并优先采用小而可审查的提交。

## Current Backlog (after v1.9.0)

### Proxy Integration

- [ ] 在软件设置中提供代理类型、地址、端口和可选凭据配置，并增加输入校验。
- [ ] 应用启动和设置变更时调用 `configure_proxy()`，让已持久化配置真正进入当前网络会话。
- [ ] 统一 API、短链接解析、头像和音频下载的代理传输层，避免只有部分请求经过代理。
- [ ] 验证 SOCKS5 和代理认证行为；若继续基于 `urllib` 无法可靠支持，则引入明确依赖并补端到端 mock 测试。

### Performance and Scalability

- [ ] 下载历史超过 1000 条时分页或增量加载，避免一次性构造全部表格行。

### Type Safety and Tests

- [ ] 为 `MainWindow` 的检测、批量路由、设置切换和下载结果流程补行为级测试。
- [ ] 补齐 `_download_audio_stream` 的 header 轮换、403 重试和断点续传边界覆盖。
- [ ] 收紧 `music_fetch/__init__.py` 的公开 API，并用更明确的结构类型替换 `BatchResultRow` Protocol。
- [ ] 重新测量覆盖率并逐步提升到 95% 以上，避免仅依赖测试数量判断质量。

### Logging and Diagnostics

- [ ] GUI 默认日志级别调整为 WARNING，CLI 继续由 `--verbose` / `--debug` 控制详细程度。
- [ ] 增加 GUI 日志查看入口，便于用户在不查找配置目录的情况下导出排障信息。
- [ ] 下载失败时汇总脱敏后的 Cookie 状态、网络连通性和 CDN 可达性诊断。

### Distribution

- [ ] 为 macOS 构建补代码签名、公证和可重复的启动冒烟检查。
- [ ] 评估 PyInstaller WebEngine 资源裁剪，降低当前 onefile 产物体积，同时保持扫码登录可用。
