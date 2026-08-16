#!/usr/bin/env python3
"""Shared user-visible texts for the CLI, TUI, and export layers."""

from __future__ import annotations

MSG_UNKNOWN = "未知"
MSG_NEED_LOGIN_ANY = "当前未登录任何账号，请登录任一网易云音乐账号"
MSG_DOWNLOAD_CANCELED = "下载已取消。"
MSG_BATCH_DUPLICATE_SONG = "与前序条目重复（song_id={song_id}）"
MSG_DOWNLOADS_EMPTY = "暂无下载记录"
MSG_DOWNLOADS_FILTER_EMPTY = "当前筛选条件下暂无记录"

MANAGER_FILTER_ALL = "全部"
MANAGER_FILTER_PENDING = "待处理"
MANAGER_FILTER_DOWNLOADING = "下载中"
MANAGER_FILTER_SUCCESS = "成功"
MANAGER_FILTER_FAILED = "失败"
MANAGER_FILTER_CANCELED = "已取消"
MANAGER_EXPORT_EMPTY = "当前筛选条件下没有可导出的记录。"

BATCH_SOURCE_SONG = "单曲"
BATCH_SOURCE_PLAYLIST = "歌单"

BATCH_STATUS_READY = "可下载"
BATCH_STATUS_UNAVAILABLE = "不可下载"
BATCH_STATUS_FAILED = "识别失败"
BATCH_STATUS_DUPLICATE = "重复已跳过"
BATCH_STATUS_DOWNLOADING_ITEM = "下载中"
BATCH_STATUS_DOWNLOAD_SUCCESS = "下载成功"
BATCH_STATUS_DOWNLOAD_FAILED = "下载失败"
BATCH_STATUS_DOWNLOAD_CANCELED = "下载已取消"
BATCH_STATUS_DOWNLOAD_PAUSED = "下载已暂停"

BATCH_DOWNLOAD_SUMMARY = "批量下载完成：成功 {success}，失败 {failed}，取消 {canceled}。"
BATCH_DOWNLOAD_STOPPED = "批量下载已停止：已完成 {processed}/{total}，成功 {success}，失败 {failed}，取消 {canceled}，未开始 {pending}。"
BATCH_FAILURE_REASON_SUMMARY = "失败原因：{reasons}"


def code_message(code: str, message: str) -> str:
    return f"{code}: {message}"


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


__all__ = [
    "BATCH_DOWNLOAD_STOPPED",
    "BATCH_DOWNLOAD_SUMMARY",
    "BATCH_FAILURE_REASON_SUMMARY",
    "BATCH_SOURCE_PLAYLIST",
    "BATCH_SOURCE_SONG",
    "BATCH_STATUS_DOWNLOAD_CANCELED",
    "BATCH_STATUS_DOWNLOAD_FAILED",
    "BATCH_STATUS_DOWNLOAD_PAUSED",
    "BATCH_STATUS_DOWNLOAD_SUCCESS",
    "BATCH_STATUS_DOWNLOADING_ITEM",
    "BATCH_STATUS_DUPLICATE",
    "BATCH_STATUS_FAILED",
    "BATCH_STATUS_READY",
    "BATCH_STATUS_UNAVAILABLE",
    "MANAGER_EXPORT_EMPTY",
    "MANAGER_FILTER_ALL",
    "MANAGER_FILTER_CANCELED",
    "MANAGER_FILTER_DOWNLOADING",
    "MANAGER_FILTER_FAILED",
    "MANAGER_FILTER_PENDING",
    "MANAGER_FILTER_SUCCESS",
    "MSG_BATCH_DUPLICATE_SONG",
    "MSG_DOWNLOADS_EMPTY",
    "MSG_DOWNLOADS_FILTER_EMPTY",
    "MSG_DOWNLOAD_CANCELED",
    "MSG_NEED_LOGIN_ANY",
    "MSG_UNKNOWN",
    "batch_detect_status_text",
    "code_message",
    "manager_status_text",
]
