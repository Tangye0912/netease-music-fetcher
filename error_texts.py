#!/usr/bin/env python3
"""Error-code to user-facing text mappings."""

from __future__ import annotations

ERROR_MESSAGE_MAP = {
    "INVALID_URL": "链接格式无效，请粘贴网易云音乐歌曲链接或歌曲 ID。",
    "AUTH_EXPIRED": "登录状态已过期，请重新登录网易云音乐账号。",
    "SONG_UNAVAILABLE": "该歌曲暂不可下载（版权、地区或会员限制）。",
    "NETWORK_ERROR": "网络请求失败，请检查网络后重试。",
    "DOWNLOAD_FAILED": "下载失败，请稍后重试或更换歌曲。",
    "DOWNLOAD_CANCELED": "下载已取消。",
    "UNSUPPORTED_FORMAT": "当前选择的格式不受支持。",
    "CONVERT_TOOL_MISSING": "未检测到 ffmpeg，无法执行格式转换。",
    "CONVERT_FAILED": "音频转换失败，请尝试其他格式或稍后重试。",
    "UNKNOWN_ERROR": "发生未知错误，请稍后重试。",
}


def _network_error_message(fallback_message: str) -> str:
    fallback = (fallback_message or "").strip().lower()
    if not fallback:
        return ERROR_MESSAGE_MAP["NETWORK_ERROR"]
    if "certificate_verify_failed" in fallback or "self-signed certificate" in fallback:
        return "网络证书校验失败（可能是代理证书或本机证书链问题），请检查代理/证书配置后重试。"
    return ERROR_MESSAGE_MAP["NETWORK_ERROR"]


def user_error_message(code: str, fallback_message: str = "") -> str:
    normalized = (code or "").strip().upper()
    if normalized == "NETWORK_ERROR":
        return _network_error_message(fallback_message)
    if normalized in ERROR_MESSAGE_MAP:
        return ERROR_MESSAGE_MAP[normalized]
    fallback = (fallback_message or "").strip()
    if fallback:
        return fallback
    return "操作失败，请稍后重试。"
