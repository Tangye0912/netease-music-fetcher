# Release Notes - v0.4.0 (2026-03-23)

## 版本定位

`v0.4.0` 完成了单任务下载流程的“任务中心化”改造，为 `v0.5.0` 批量下载奠定基础。

## 主要新增

- 新增下载任务状态模型：`pending/downloading/success/failed/canceled`
- 下载管理支持任务状态筛选（全部/成功/失败/已取消/待处理/下载中）
- 下载管理新增“重试失败任务”入口
- 新增下载重试辅助模块（仅对网络/下载失败场景重试）
- 新增下载参数设置：
  - 检测超时
  - 下载超时
  - 下载重试次数
  - 并发上限（当前版本为预留参数，默认仍按单任务顺序下载）

## 主要改动

- 主流程接入显式任务生命周期：`pending -> downloading -> success/failed/canceled`
- 下载历史结构扩展 `status/error_code`，并保持历史数据向后兼容
- 关键日志统一携带 `task_id`，便于排障追踪
- 会话持久化扩展下载参数字段，并对参数做边界夹紧

## 测试结果

- `python3 -m unittest discover -s tests`：44 passed
- `python3.13 -m unittest discover -s tests`：44 passed

## 升级说明

- 本版本对终端用户 Python 版本不设强制门槛；开发环境建议优先使用 Python 3.13。
- 并发下载能力将在 `v0.5.0` 启用，当前并发参数仅用于配置预留与兼容后续版本。
