# music-fetch

网易云音乐单曲下载工具。  
当前版本以 GUI 为主流程，默认输出格式为 `mp3`。

## 1. 版本概览（v0.5.1）

### 1.1 v0.5.1 相对 v0.5.0 的更新

- **重构**：`main.py` 拆分为 `_workers.py`(工作线程) + `_dialogs.py`(对话框)，文件从 3290 行降至 665 行。
- **重构**：`music_fetch.py` 拆分为 `_api.py`(API) + `_audio.py`(下载/转码) + `_cli.py`(CLI)，原文件改为外观层。
- **修复**：6 处 bare `except` 改为捕获具体异常；Lambda 闭包改用 `functools.partial`；修复 2 处运行时 NameError。
- **工程化**：新增 `pyproject.toml`、补齐 `.gitignore`、常量去重、Combo 工具提取。
- **测试**：新增 15 个测试，总数 63→78。

详细发布记录见 [CHANGELOG.md](./CHANGELOG.md)。  
迭代路线见 [ROADMAP.md](./ROADMAP.md)。

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

### 1.3 下一版本计划（v0.6.0）

- 批量下载“仅重试失败项”一键入口
- 批次失败原因分组统计与结果汇总
- 批次结果导出（成功/失败明细）

## 2. 环境准备

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
python3 main.py
```

### Windows（推荐双击）

- 双击项目根目录下的 `start_windows.bat`
- 或终端执行：

```bat
cd /d D:\path\to\music-fetch
py -3 main.py
```

## 4. GUI 使用流程

1. 启动后自动检测登录态。  
2. 未登录/已过期时，弹出扫码登录窗口。  
3. 登录成功后进入主界面，可看到头像、昵称、会员信息。  
4. 可通过“依赖管理”查看 `ffmpeg` 状态与安装建议。  
5. 点击头像菜单可切换账号或退出账号（退出会同步清理内嵌网页登录态）。  
6. 输入歌曲链接并点击“检测”。  
7. 在确认窗口点击“下载”。  
8. 选择保存目录、文件名、目标格式（默认 `mp3`）。  
9. 查看下载进度，完成后弹出文件路径。  
10. 通过“下载管理”查看历史与文件操作。  

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
  --format mp4 \
  --cookie-file "~/.config/music-fetch/cookies.txt" \
  --timeout 30
```

说明：CLI 当前仍按历史约定默认 `mp4` 输出（GUI 默认 `mp3`）。`resolve_output_path` 默认格式已统一为 `mp3`。

## 6. 错误码

- `INVALID_URL`：链接无效或无法解析歌曲 ID
- `AUTH_EXPIRED`：登录态缺失或过期
- `SONG_UNAVAILABLE`：歌曲不可下载（版权/地区/VIP）
- `NETWORK_ERROR`：网络或接口异常
- `DOWNLOAD_FAILED`：下载请求失败
- `DOWNLOAD_CANCELED`：用户主动取消下载
- `CONVERT_TOOL_MISSING`：缺少 ffmpeg，无法执行格式转换
- `CONVERT_FAILED`：音频格式转换失败
- `UNSUPPORTED_FORMAT`：不支持的输出格式（CLI 仍仅支持 `mp4`）
- `UNKNOWN_ERROR`：未预期异常

## 7. 项目架构

```
music_fetch/
├── main.py                  ← 入口：MainWindow + 启动流程
├── _dialogs.py              ← 9个对话框类
├── _workers.py              ← 3个QThread工作线程
├── _api.py                  ← 网易云API：HTTP、cookie、资源解析
├── _audio.py                ← 音频下载 + ffmpeg转码
├── _cli.py                  ← CLI命令行入口
├── music_fetch.py           ← 外观层（重新导出三个子模块）
├── _combo_utils.py          ← 共享QComboBox工具
├── app_settings.py          ← 全局配置
├── ui_texts.py              ← 用户可见文案
├── error_texts.py           ← 错误码→友好文案映射
├── app_stores.py            ← 会话与下载历史持久化
├── app_logging.py           ← 日志初始化
├── batch_inputs.py          ← 批量输入解析
├── download_tasks.py        ← 任务状态模型
├── download_retry.py        ← 重试逻辑
└── tests/                   ← 78个单元测试
```

依赖方向（自底向上）：
```
app_settings → app_logging → app_stores / batch_inputs / download_tasks / error_texts / ui_texts
  → [ _api → _audio → _cli ] → music_fetch (facade)
  → _workers → _dialogs → main
```

新增功能优先复用已有模块，避免业务代码继续写硬编码。

## 8. 提交规范（建议）

后续提交建议使用“标题 + 文件级变更说明”：

```text
feat: 简要说明这次迭代目标

- main.py: 调整登录窗口与输入区交互
- ui_texts.py: 更新弹窗与状态文案
- README.md: 更新启动方式与功能说明
```

这样新同学能快速理解“每个文件改了什么、为什么改”。
完整模板见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 9. 测试

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## 10. 日志与排障

- 默认日志：`~/.config/music-fetch/logs/music-fetch.log`
- GUI 和 CLI 共用日志体系
- 记录节点：登录检测、短链解析、资源检测、下载开始/失败/完成、下载管理操作
- 直链被 CDN 403 拒绝时，会自动尝试 `outer/url` 兜底
- 日志不会打印完整 `MUSIC_U` 值（已脱敏）

## 11. 合规说明

仅用于你已获得合法授权的音频素材。  
本工具不提供 DRM/版权绕过能力。
