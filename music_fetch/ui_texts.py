#!/usr/bin/env python3
"""Centralized user-visible texts for GUI."""

from __future__ import annotations

APP_TITLE = "网易云音乐下载助手"
APP_DESC = "支持检测网易云音乐单曲链接或歌单链接"
STATUS_IDLE = "状态：待输入"
STATUS_DETECTING = "状态：检测中..."
STATUS_DETECT_DONE = "状态：检测完成"
STATUS_DETECT_FAILED = "状态：检测失败"
STATUS_DOWNLOADING = "状态：下载中..."
STATUS_DOWNLOAD_NOT_DONE = "状态：下载未完成"
STATUS_LOGOUT = "状态：已退出登录"
STATUS_LOGIN_UPDATED = "状态：登录已更新，可继续检测。"
STATUS_CANCELING = "正在取消..."
STATUS_CHECKING_UPDATE = "状态：正在检查新版本..."

LOGIN_DIALOG_TITLE = "网易云音乐登录"
LOGIN_INFO = "请在下方页面完成网易云音乐扫码登录，登录成功后点击“确认并继续”。"
LOGIN_REMEMBER = "记住登录状态（下次启动自动检测）"
LOGIN_WEB_GROUP = "扫码登录"
LOGIN_WEB_HINT = "提示：若默认不是扫码页，请点击“扫码登录”。完成登录后点击下方确认按钮。"
LOGIN_FALLBACK_HINT = "当前环境未安装 Qt WebEngine，无法打开内嵌登录页。请安装后重试。"
LOGIN_BTN_CONFIRM = "确认并继续"
BTN_CANCEL = "取消"
BTN_CLOSE = "关闭"
BTN_BACK = "返回"
BTN_DOWNLOAD = "下载"
BTN_START_DOWNLOAD = "开始下载"

ACCOUNT_LABEL_NICKNAME_LOGOUT = "昵称：未登录"
ACCOUNT_LABEL_VIP_UNKNOWN = "会员：-"
ACCOUNT_LABEL_VIP = "会员：VIP"
ACCOUNT_LABEL_NORMAL = "会员：普通用户"
ACCOUNT_BTN_FALLBACK = "账户"
ACCOUNT_MENU_SWITCH = "切换账号"
ACCOUNT_MENU_LOGOUT = "退出当前账号"

BTN_DOWNLOAD_MANAGER = "下载管理"
BTN_DEPENDENCY_MANAGER = "依赖管理"
BTN_UI_SETTINGS = "软件设置"
BTN_DETECT = "检测"
FOOTER_GITHUB_LINK = "GitHub 项目"
FOOTER_VERSION_LINK = "版本：{version}"
INPUT_PLACEHOLDER = "粘贴歌曲或歌单链接（支持单条/多条，自动识别）"
INPUT_MULTI_HINT = "支持多个歌曲或歌单链接识别，直接粘贴即可自动解析。"
INPUT_VALIDATION_EMPTY = "请输入歌曲链接、分享文案，或直接输入歌曲 ID。"
INPUT_VALIDATION_OK_ID = "输入格式有效：将按歌曲 ID 直接检测。"
INPUT_VALIDATION_OK_URL = "输入格式有效：可开始检测。"
INPUT_VALIDATION_SHORT_LINK = "输入内容已识别，可点击检测。"
INPUT_VALIDATION_BAD_HOST = "仅支持 music.163.com 或 163cn.tv 链接。"
INPUT_VALIDATION_ID_MISSING = "未识别到歌曲 ID，请检查链接是否完整。"
INPUT_ANALYZING = "正在识别输入内容..."
INPUT_DETECT_SINGLE = "识别结果：【单个歌曲/歌单】"
INPUT_DETECT_MULTIPLE = "识别结果：【多个歌曲/歌单】（{count} 条）"
INPUT_DETECT_INVALID = "未识别到可用链接，请检查后重试。"

TITLE_WARNING = "提示"
TITLE_PARAM_ERROR = "参数错误"
TITLE_LOGIN_FAIL = "登录失败"
TITLE_LOGIN_EXPIRED = "登录过期"
TITLE_NETWORK_CHECK_FAIL = "网络校验失败"
TITLE_NOT_LOGIN = "未登录"
TITLE_SWITCH_CANCELED = "未切换账号"
TITLE_AVATAR_FAIL = "头像加载失败"
TITLE_LOGOUT = "退出账号"
TITLE_DETECT_FAIL = "检测失败"
TITLE_DOWNLOAD_FAIL = "下载失败"
TITLE_DOWNLOAD_DONE = "下载完成"
TITLE_DOWNLOAD_CANCELED = "已取消"
TITLE_DELETE_CONFIRM = "确认删除"
TITLE_PATH_MISSING = "路径不存在"
TITLE_DELETE_FAIL = "删除失败"
TITLE_PATH_ERROR = "路径错误"
TITLE_LOGIN_INVALID = "登录失效"
TITLE_DEP_MISSING = "依赖缺失"

MSG_NEED_LOGIN_ANY = "当前未登录任何账号，请登录任一网易云音乐账号"
MSG_NO_LOGIN_ON_START = "未登录网易云账号，无法正常使用，请登录账号"
MSG_SWITCH_CANCELED = "未切换账号，仍使用当前登录状态"
MSG_AVATAR_LOAD_FAILED = "账号头像加载失败，已使用默认头像"
MSG_LOGIN_COOKIE_MISSING = "未检测到登录凭证。请先完成扫码登录后再继续。"
MSG_LOGIN_INVALID = "登录态无效或已过期，请重新登录。"
MSG_LOGIN_REQUIRES_WEBENGINE = "当前环境缺少 Qt WebEngine，无法完成登录。请先执行：python3 -m pip install PySide6-Addons"
MSG_FFMPEG_NEED_INSTALL = "未检测到 ffmpeg，当前仅支持 MP3 下载。安装后可开启其他格式。"
MSG_FFMPEG_CONFIRM_MP3 = "未检测到 ffmpeg，将保持默认 MP3 格式下载。\n点击“是”继续进入下载设置，点击“否”取消本次下载。"
MSG_FFMPEG_INSTALL_GUIDE = "安装建议：macOS 执行 `brew install ffmpeg`；Windows 执行 `winget install Gyan.FFmpeg`。"
MSG_NEED_INPUT_URL = "请先输入歌曲链接或歌曲 ID。"
MSG_NEED_PICK_DIR = "请选择有效的下载目录。"
MSG_EMPTY_FILENAME = "文件名不能为空。"
MSG_DOWNLOAD_CANCELED = "下载已取消。"
MSG_LOGOUT_CONFIRM = "确定退出当前登录账号吗？"
MSG_NOT_LOGGED_IN = "当前未登录。"
MSG_NOT_SELECTED_RECORD = "请先选择一条下载记录。"
MSG_DOWNLOADS_EMPTY = "暂无下载记录"
MSG_UNSUPPORTED_FORMAT = "不支持的格式：{fmt}"
MSG_UNKNOWN = "未知"
MSG_UPDATE_CHECK_FAIL = "检查更新失败：{message}"
MSG_UPDATE_AVAILABLE = "发现新版本：{latest}\n当前版本：{current}\n是否打开 GitHub 项目页查看？"
MSG_UPDATE_LATEST = "当前已是最新版本（{current}）。"

DOWNLOAD_OPTIONS_TITLE = "下载设置"
DOWNLOAD_OPTIONS_DIR = "保存目录"
DOWNLOAD_OPTIONS_NAME = "文件名（不含后缀）"
DOWNLOAD_OPTIONS_FORMAT = "下载格式"
DOWNLOAD_OPTIONS_PREVIEW = "预估输出：{path}"
DOWNLOAD_OPTIONS_HINT_PICK_DIR = "请先选择有效保存目录。"
DOWNLOAD_OPTIONS_HINT_RENAME = "请填写文件名。"
DOWNLOAD_OPTIONS_HINT_READY = "参数已就绪，可开始下载。"
DOWNLOAD_DIR_PICKER_TITLE = "选择下载目录"
DOWNLOAD_DIR_PICKER_BTN = "选择..."

DOWNLOAD_PROGRESS_TITLE = "下载中"
DOWNLOAD_PROGRESS_INIT = "准备下载..."
DOWNLOAD_PROGRESS_SPEED = "速度：-"
DOWNLOAD_PROGRESS_PATH = "输出路径："
DOWNLOAD_PROGRESS_CANCEL = "取消下载"
DOWNLOAD_PROGRESS_PAUSE = "暂停"
DOWNLOAD_PROGRESS_RESUME = "继续"
DOWNLOAD_PROGRESS_RESUMING = "下载恢复中..."
DOWNLOAD_PROGRESS_PAUSED = "下载已暂停"
DOWNLOAD_PROGRESS_DONE_BODY = "文件：{name}\n大小：{size}\n路径：{path}"
DOWNLOAD_PROGRESS_DONE_FALLBACK_NOTE = "\n提示：未安装 ffmpeg，已按源格式保存。"
DOWNLOAD_PROGRESS_TEXT_SIMPLE = "已下载 {downloaded}"
DOWNLOAD_PROGRESS_TEXT_FULL = "已下载 {downloaded} / {total}"

SONG_CONFIRM_TITLE = "歌曲检测结果"
SONG_CONFIRM_ID = "歌曲 ID"
SONG_CONFIRM_NAME = "歌名"
SONG_CONFIRM_DURATION = "时长"
SONG_CONFIRM_STATUS = "状态"
SONG_CONFIRM_REASON = "原因"
SONG_CONFIRM_ARTIST = "艺人"
SONG_CONFIRM_ALBUM = "专辑"
SONG_CONFIRM_CAN_DOWNLOAD = "可下载"
SONG_CONFIRM_CANT_DOWNLOAD = "不可下载"

MANAGER_TITLE = "下载管理"
MANAGER_COL_SONG = "歌曲"
MANAGER_COL_FILENAME = "文件名"
MANAGER_COL_SIZE = "大小"
MANAGER_COL_TIME = "下载时间"
MANAGER_COL_STATUS = "任务状态"
MANAGER_COL_PATH = "路径"
MANAGER_BTN_OPEN_FOLDER = "打开文件夹"
MANAGER_BTN_DELETE_FILE = "删除文件"
MANAGER_BTN_RETRY_FAILED = "重试失败任务"
MANAGER_BTN_REFRESH = "刷新"
MANAGER_FILTER_LABEL = "状态筛选"
MANAGER_FILTER_ALL = "全部"
MANAGER_FILTER_PENDING = "待处理"
MANAGER_FILTER_DOWNLOADING = "下载中"
MANAGER_FILTER_SUCCESS = "成功"
MANAGER_FILTER_FAILED = "失败"
MANAGER_FILTER_CANCELED = "已取消"
MSG_DOWNLOADS_FILTER_EMPTY = "当前筛选条件下暂无记录"
MSG_RETRY_ONLY_FAILED = "仅失败状态任务支持重试。"
MANAGER_MISSING_FOLDER = "目录不存在：{folder}"
MANAGER_DELETE_CONFIRM = "确定删除文件并移除记录吗？\n{path}"
DEPENDENCY_HINT_LIMITED = "部分功能受限"
DEPENDENCY_HINT_LIMITED_TIP = "检测到依赖缺失。点击“依赖管理”查看详情与安装方法。"
DEP_MANAGER_TITLE = "依赖管理"
DEP_MANAGER_DESC = "查看关键依赖状态。依赖缺失会导致部分功能受限。"
DEP_MANAGER_COL_NAME = "依赖"
DEP_MANAGER_COL_STATUS = "状态"
DEP_MANAGER_COL_IMPACT = "功能影响"
DEP_MANAGER_COL_INSTALL = "安装方法"
DEP_MANAGER_ITEM_FFMPEG = "ffmpeg"
DEP_MANAGER_STATUS_OK = "已安装"
DEP_MANAGER_STATUS_MISSING = "未安装"
DEP_MANAGER_IMPACT_OK = "支持所有下载格式与转码能力。"
DEP_MANAGER_IMPACT_MISSING = "仅支持 MP3 下载，其他格式转码不可用。"
DEP_MANAGER_INSTALL_OK = "-"
DEP_MANAGER_INSTALL_FFMPEG = "macOS: brew install ffmpeg\nWindows: winget install Gyan.FFmpeg"

UI_SETTINGS_TITLE = "软件设置"
UI_SETTINGS_DESC = "统一管理界面字体与下载参数，保存后立即生效并在下次启动时保持。"
UI_SETTINGS_FONT_SIZE = "字体大小"
UI_SETTINGS_DOWNLOAD_GROUP = "下载设置"
UI_SETTINGS_DETECT_TIMEOUT = "检测超时（秒）"
UI_SETTINGS_DOWNLOAD_TIMEOUT = "下载超时（秒）"
UI_SETTINGS_DOWNLOAD_RETRY = "下载重试次数"
UI_SETTINGS_DOWNLOAD_CONCURRENCY = "并发上限"
UI_SETTINGS_DOWNLOAD_CONCURRENCY_HINT = "批量下载同时执行的任务数。网络较慢时建议 1-2 路，更稳定。"
UI_SETTINGS_RESET = "恢复默认"
UI_SETTINGS_SAVE = "保存"
UI_SETTINGS_THEME = "界面主题"
UI_SETTINGS_THEME_LIGHT = "浅色"
UI_SETTINGS_THEME_DARK = "深色"

COUNT_SUFFIX = "次"
CONCURRENCY_SUFFIX = "路"

BATCH_DIALOG_TITLE = "批量识别与下载"
BATCH_DIALOG_DESC = "支持粘贴多行链接或分享文案，先识别再批量下载可下载歌曲。"
BATCH_INPUT_LABEL = "批量输入（支持直接粘贴多个链接/ID或整段分享文案）"
BATCH_INPUT_PLACEHOLDER = "示例：\nhttps://music.163.com/song?id=33894312\nhttps://163cn.tv/xxxxx\n分享文案 ..."
BATCH_OUTPUT_DIR = "保存目录"
BATCH_OUTPUT_PICKER_TITLE = "选择批量下载目录"
BATCH_OUTPUT_PICKER_BTN = "选择..."
BATCH_TARGET_FORMAT = "下载格式"
BATCH_BTN_DETECT = "开始识别"
BATCH_BTN_SETTINGS = "下载设置"
BATCH_BTN_DOWNLOAD = "下载选中项"
BATCH_BTN_CANCEL = "取消下载"
BATCH_BTN_PAUSE = "全部暂停"
BATCH_BTN_RESUME = "全部恢复"
BATCH_BTN_SELECT_ALL = "全选可下载"
BATCH_BTN_CLEAR_ALL = "取消全选"
BATCH_BTN_INVERT = "反选可下载"
BATCH_BTN_INVERT_TIP = "全选后点击“反选可下载”可快速取消全选。"
BATCH_BTN_RETRY_FAILED = "重试失败项"
BATCH_BTN_EXPORT_CSV = "导出 CSV"
BATCH_SELECTION_SUMMARY = "已选 {selected} / 可下载 {ready} 首"
BATCH_COL_SELECT = "选择"
BATCH_COL_SOURCE = "来源"
BATCH_COL_SONG_ID = "歌曲 ID"
BATCH_COL_SONG_NAME = "歌曲名"
BATCH_COL_SIZE = "资源大小"
BATCH_COL_STATUS = "预检状态"
BATCH_SOURCE_SONG = "单曲"
BATCH_SOURCE_PLAYLIST = "歌单"
BATCH_SOURCE_UNKNOWN = "未知"
BATCH_STATUS_IDLE = "状态：等待批量输入"
BATCH_STATUS_DETECTING = "状态：批量识别中..."
BATCH_STATUS_READY = "可下载"
BATCH_STATUS_UNAVAILABLE = "不可下载"
BATCH_STATUS_FAILED = "识别失败"
BATCH_STATUS_DUPLICATE = "重复已跳过"
BATCH_STATUS_DOWNLOADING_ITEM = "下载中"
BATCH_STATUS_DOWNLOAD_SUCCESS = "下载成功"
BATCH_STATUS_DOWNLOAD_FAILED = "下载失败"
BATCH_STATUS_DOWNLOAD_CANCELED = "下载已取消"
BATCH_STATUS_DOWNLOAD_PAUSED = "下载已暂停"
BATCH_STATUS_SUMMARY = "识别完成：共 {total} 条，可下载 {ready} 条，重复 {duplicate} 条，失败/不可下载 {bad} 条。"
BATCH_STATUS_DOWNLOADING = "状态：批量下载中..."
BATCH_STATUS_CANCELING = "状态：正在取消批量下载..."
BATCH_DOWNLOAD_SUMMARY = "批量下载完成：成功 {success}，失败 {failed}，取消 {canceled}。"
BATCH_DOWNLOAD_STOPPED = "批量下载已停止：已完成 {processed}/{total}，成功 {success}，失败 {failed}，取消 {canceled}，未开始 {pending}。"
BATCH_FAILURE_REASON_SUMMARY = "失败原因：{reasons}"
BATCH_EXPORT_CSV_TITLE = "导出批次结果"
BATCH_EXPORT_CSV_FILTER = "CSV 文件 (*.csv)"
MSG_BATCH_NEED_INPUT = "请先输入至少一条链接/ID。"
MSG_BATCH_NEED_READY = "当前没有可下载且已勾选的歌曲。"
MSG_BATCH_NEED_FAILED_RETRY = "当前没有下载失败项可重试。"
MSG_BATCH_DETECT_RUNNING = "批量识别进行中，请稍候。"
MSG_BATCH_DOWNLOAD_RUNNING = "批量下载进行中，请稍候。"
MSG_BATCH_DETECT_FAIL = "批量识别任务失败：{message}"
MSG_BATCH_DOWNLOAD_NO_OUTPUT = "请先选择有效下载目录。"
MSG_BATCH_DUPLICATE_SONG = "与前序条目重复（song_id={song_id}）"
MSG_BATCH_PARTIAL_INPUT = "保留原始输入（非链接文本），识别阶段将继续尝试解析。"
MSG_BATCH_INPUT_UNCHANGED = "输入内容未变化，已完成识别。若需重新识别，请修改输入内容。"
MSG_BATCH_INPUT_CHANGED = "输入已变化，请先重新识别，再下载选中项。"
MSG_BATCH_EXPORT_EMPTY = "当前没有批次结果可导出。"
MSG_BATCH_EXPORT_DONE = "批次结果已导出：{path}"
MSG_BATCH_EXPORT_FAILED = "批次结果导出失败：{message}"
MSG_BATCH_WORKER_UNEXPECTED = "UNKNOWN_ERROR: 下载线程异常结束"
MSG_BATCH_DETECT_EMPTY = "未识别到任何歌曲，请检查输入内容是否为有效的网易云音乐链接。"

ACC_INPUT_SONG_LINK = "歌曲链接输入框"
ACC_BTN_DETECT = "检测按钮"
ACC_BTN_DEP_MANAGER = "依赖管理按钮"
ACC_BTN_DOWNLOAD_MANAGER = "下载管理按钮"
ACC_BTN_UI_SETTINGS = "软件设置按钮"
ACC_BTN_LOGIN_CONFIRM = "登录确认按钮"
ACC_BTN_DOWNLOAD = "下载按钮"
ACC_BTN_CANCEL = "取消按钮"
ACC_INPUT_URL = "歌曲链接输入框"
ACC_BTN_REMEMBER = "记住登录状态"
ACC_BTN_LOGIN_CONFIRM = "登录确认按钮"
ACC_BTN_DETECT_SHORT = "检测按钮"

# Search
SEARCH_TITLE = "搜索歌曲"
SEARCH_PLACEHOLDER = "输入歌曲名或歌手名..."
SEARCH_BTN = "搜索"
SEARCH_BTN_SEARCHING = "搜索中..."
SEARCH_EMPTY = "未找到相关歌曲"
SEARCH_COL_SONG = "歌曲"
SEARCH_COL_ARTIST = "歌手"
SEARCH_COL_ALBUM = "专辑"
SEARCH_COL_DURATION = "时长"
SEARCH_COL_ACTION = "操作"
SEARCH_DOWNLOAD_BTN = "下载"
SEARCH_HINT = "输入关键词后按回车或点击搜索"

# User playlists
PLAYLIST_TITLE = "我的歌单"
PLAYLIST_COL_NAME = "歌单名称"
PLAYLIST_COL_COUNT = "歌曲数"
PLAYLIST_COL_CREATOR = "创建者"
PLAYLIST_BTN_OPEN = "打开歌单"
PLAYLIST_EMPTY = "暂无歌单"
PLAYLIST_BTN_MY = "我的歌单"

# Tray / notification
TRAY_TOOLTIP = "网易云音乐下载助手"
TRAY_SHOW = "显示主窗口"
TRAY_QUIT = "退出"
TRAY_DOWNLOAD_DONE = "下载完成"
TRAY_DOWNLOAD_DONE_BODY = "{name} 已下载完成。"
TRAY_DOWNLOAD_FAILED = "下载失败"
TRAY_CLIPBOARD_DETECTED = "检测到剪贴板中的链接，已自动填入。"
MSG_TRAY_UNSUPPORTED = "当前系统不支持系统托盘，最小化功能将不可用。"

def code_message(code: str, message: str) -> str:
    return f"{code}: {message}"


def login_network_confirm(code: str) -> str:
    return f"登录状态在线校验失败：{code}\n是否仍然继续？"


def detect_auth_expired(code: str, message: str) -> str:
    return f"{code}: {message}\n请点击头像菜单切换账号。"


def status_download_done(filename: str) -> str:
    return f"状态：下载完成 -> {filename}"


def status_update_available(latest_version: str) -> str:
    return f"状态：发现新版本 {latest_version}"


def status_update_latest(version: str) -> str:
    return f"状态：当前已是最新版本 {version}"


def batch_runtime_settings_updated(
    detect_timeout: int, download_timeout: int, retry_count: int, concurrency: int,
) -> str:
    return (
        f"下载设置已更新：检测超时 {detect_timeout}s，下载超时 {download_timeout}s，"
        f"重试 {retry_count}，并发 {concurrency} 路。"
    )


def batch_download_concurrency_label(concurrency: int) -> str:
    return f"（并发 {concurrency} 路）"


def batch_download_active_status(
    cursor: int, total: int, active_count: int,
) -> str:
    return f"已完成 {cursor}/{total}，并发中 {active_count} 路"


def batch_download_progress_with_song(
    cursor: int, total: int, active_count: int,
    song_info: str, downloaded: str, extra: str,
) -> str:
    return f"{cursor}/{total}（并发中 {active_count}） - {song_info} ({downloaded} {extra})"


def status_ui_settings_updated(
    font_size: int,
    detect_timeout: int,
    download_timeout: int,
    retry_count: int,
    concurrency: int,
    prefix: bool = True,
) -> str:
    body = (
        f"设置已更新（字体 {font_size}px，检测超时 {detect_timeout}s，"
        f"下载超时 {download_timeout}s，重试 {retry_count} 次，并发上限 {concurrency}）"
    )
    return f"状态：{body}" if prefix else body


def speed_text(speed: str) -> str:
    return f"速度：{speed}/s"


def nickname_text(name: str) -> str:
    return f"昵称：{name}"


def ui_settings_preview(font_size: int) -> str:
    return f"预览：当前字体大小 {font_size}px。"


def ui_settings_theme_preview(theme: str) -> str:
    theme_labels = {"light": UI_SETTINGS_THEME_LIGHT, "dark": UI_SETTINGS_THEME_DARK}
    label = theme_labels.get((theme or "").strip().lower(), theme or "")
    return f"主题：{label}"


def manager_status_text(status: str) -> str:
    normalized = (status or "").strip().lower()
    mapping = {
        "pending": MANAGER_FILTER_PENDING,
        "downloading": MANAGER_FILTER_DOWNLOADING,
        "success": MANAGER_FILTER_SUCCESS,
        "failed": MANAGER_FILTER_FAILED,
        "canceled": MANAGER_FILTER_CANCELED,
    }
    return mapping.get(normalized, status or MSG_UNKNOWN)


def batch_detect_status_text(status: str) -> str:
    normalized = (status or "").strip().lower()
    mapping = {
        "ready": BATCH_STATUS_READY,
        "unavailable": BATCH_STATUS_UNAVAILABLE,
        "failed": BATCH_STATUS_FAILED,
        "duplicate": BATCH_STATUS_DUPLICATE,
        "downloading": BATCH_STATUS_DOWNLOADING_ITEM,
        "download_success": BATCH_STATUS_DOWNLOAD_SUCCESS,
        "download_failed": BATCH_STATUS_DOWNLOAD_FAILED,
        "download_canceled": BATCH_STATUS_DOWNLOAD_CANCELED,
        "download_paused": BATCH_STATUS_DOWNLOAD_PAUSED,
    }
    return mapping.get(normalized, status or MSG_UNKNOWN)


def batch_source_text(source_type: str) -> str:
    normalized = (source_type or "").strip().lower()
    mapping = {
        "song": BATCH_SOURCE_SONG,
        "playlist": BATCH_SOURCE_PLAYLIST,
    }
    return mapping.get(normalized, BATCH_SOURCE_UNKNOWN)
