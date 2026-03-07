# music-fetch

网易云音乐单曲下载工具（默认输出 `mp4` 音频资源）。

支持两种模式：
- GUI：账号卡片 + 链接检测 + 歌曲确认 + 下载设置 + 进度条 + 下载管理
- CLI：直接按链接下载

链接输入支持：
- 标准链接：`music.163.com/song?id=...`
- 短链接：`163cn.tv/...`
- 整段分享文案（会自动提取其中的 URL）

## 1. 环境准备

```bash
python3 -m pip install PySide6
```

若需要将音频转为非原始格式（例如 m4a -> mp3/wav/flac），请安装 `ffmpeg`。

## 1.1 维护约定（新增）

为便于后续新增模块统一调用，已抽出底层模块：

- `app_settings.py`：全局配置（路径、默认格式、支持格式、示例链接）
- `ui_texts.py`：所有用户可见文案（弹窗、按钮、状态文本）
- `error_texts.py`：错误码 -> 用户友好提示映射
- `app_stores.py`：会话与下载历史持久化

新增功能优先复用以上模块，避免在业务代码里继续写硬编码路径和文案。

如果你的环境未包含 `QtWebEngine`，GUI 仍可运行，但登录会走手动输入 Cookie 兜底方式。

## 2. GUI 使用（推荐）

```bash
python3 main.py
```

流程：
1. 启动后检测登录态。
2. 已登录则进入主界面并展示当前账号头像、昵称、VIP 信息；未登录/过期则弹登录窗口（内嵌网页登录，支持扫码/账号密码）。
3. 点击头像可打开菜单：`切换账号`、`退出当前账号`。
4. 输入歌曲分享链接，点击“检测”（输入框旁 `?` 可查看长链接示例）。
5. 在歌曲确认窗口点击“下载”。
6. 在下载设置里选择目录、重命名和下载格式（默认 `mp3`）。
7. 进入下载进度窗口，完成后弹出文件路径和文件名。
8. 点击“下载管理”可查看历史下载，支持打开对应文件夹、删除文件并移除记录。

## 3. CLI 使用

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

Cookie 文件格式：

```text
MUSIC_U=...; __csrf=...; other_cookie=...
```

## 4. 错误码

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

## 5. 测试

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## 6. 日志与排障

- 默认日志文件：`~/.config/music-fetch/logs/music-fetch.log`
- GUI 和 CLI 都会写入这份日志
- 日志包含流程节点：登录检测、链接解析、短链展开、资源检测、下载开始/失败/完成
- 关键交互也会记录：账号切换/退出、打开下载管理、打开下载目录、删除下载文件
- 当 API 返回的下载直链被 CDN 拒绝（403）时，会自动尝试 `outer/url` 兜底链路
- 日志不会打印完整 `MUSIC_U` 值（已脱敏）

CLI 可自定义日志路径：

```bash
./music-fetch --url "https://music.163.com/#/song?id=33894312" --log-file "./music-fetch.log"
```

## 7. 合规说明

仅用于你有合法授权的音频素材。
本工具不提供 DRM/版权绕过能力。
