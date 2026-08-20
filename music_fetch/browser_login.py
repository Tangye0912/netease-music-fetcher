#!/usr/bin/env python3
"""Official NetEase web login via the user's real browser.

The tool's own QR codes (generated through the encrypted API) get flagged by
NetEase risk control ("设备环境异常"), so instead of rendering a terminal QR
we open the official music.163.com login page in a real browser and let the
user scan the *official* QR (or reuse an existing browser session).  The
resulting cookie is captured through the Chrome DevTools Protocol (CDP).

Two capture paths are handled automatically:

  1. Reuse an existing login: launch the user's default browser profile; if a
     MUSIC_U cookie is already present, grab it with no scanning at all.
  2. Scan flow: otherwise prompt the user to scan the official QR in the
     opened browser and poll until the cookie appears.

Requires a local Chrome/Edge and the `websocket-client` package (a declared
dependency, imported lazily so the rest of the app still imports without it).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional
from urllib import request

from music_fetch.api import MusicFetchError, normalize_cookie
from music_fetch.network import open_url

LOGIN_URL = "https://music.163.com/#/login"

# Common install locations for Edge and Chrome (in preference order).
_BROWSER_CANDIDATES = [
    # Windows Edge
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # Windows Chrome
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
]


class BrowserLoginError(Exception):
    """Raised when the official-browser login flow cannot run."""


def find_browser_exe() -> Optional[str]:
    """Locate an installed Chrome/Edge executable (or None)."""
    for candidate in _BROWSER_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("msedge", "chrome", "google-chrome", "chromium", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def pick_free_port() -> int:
    """Return a currently free TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_cookie_string(cookies: list[dict[str, object]]) -> str:
    """Build a 'k=v; k=v' cookie string from CDP cookie objects."""
    pairs: list[tuple[str, str]] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        if name and value:
            pairs.append((name, value))
    return "; ".join(f"{k}={v}" for k, v in pairs)


def _launch_browser(
    exe: str,
    port: int,
    profile_dir: Optional[str],
    url: str,
) -> subprocess.Popen[bytes]:
    cmd = [exe, f"--remote-debugging-port={port}"]
    if profile_dir:
        cmd.append(f"--user-data-dir={profile_dir}")
    # Chrome/Edge (111+) reject DevTools WebSocket handshakes unless the
    # Origin is allow-listed. The debug port only listens on 127.0.0.1, so
    # allowing all origins is safe here.
    cmd.extend(
        [
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            url,
        ]
    )
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _kill_background_browsers(exe: str) -> None:
    """End lingering background processes of the given browser.

    Edge/Chrome keep background processes even after all windows are closed
    (e.g. "continue running background apps").  Those hold the default
    profile, so a new launch with the same profile cannot open a DevTools
    port.  Killing them lets a clean instance start with the debug port.
    """
    name = Path(exe).name  # e.g. msedge.exe / chrome.exe
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/IM", name, "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            subprocess.run(
                ["pkill", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    except OSError:
        pass


def _default_profile_dir(exe: str) -> Optional[str]:
    """Return the default user-data directory for the browser executable."""
    name = Path(exe).name.lower()
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return None
    if "msedge" in name:
        return str(Path(local_appdata) / "Microsoft" / "Edge" / "User Data")
    if "chrome" in name:
        return str(Path(local_appdata) / "Google" / "Chrome" / "User Data")
    return None


def _read_devtools_port(profile_dir: Optional[str]) -> Optional[int]:
    """Read the actual DevTools port the browser wrote, if any."""
    if not profile_dir:
        return None
    port_file = Path(profile_dir) / "DevToolsActivePort"
    try:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        return int(lines[0]) if lines else None
    except (OSError, ValueError, IndexError):
        return None


def _wait_for_cdp_ws(profile_dir: Optional[str], fallback_port: int, timeout: float) -> Optional[int]:
    """Wait for the browser's DevTools HTTP endpoint and return its port.

    The authoritative port comes from the browser's DevToolsActivePort file
    (Chrome/Edge can auto-assign or rebind); fallback_port is used when the
    profile dir is unknown.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        port = _read_devtools_port(profile_dir) or fallback_port
        req = request.Request(f"http://127.0.0.1:{port}/json/version", method="GET")
        try:
            with open_url(req, timeout=2) as resp:
                json.loads(resp.read().decode("utf-8"))
            return port
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


def _find_page_ws(port: int, timeout: float) -> Optional[str]:
    """Return the WebSocket URL of the music.163.com page target, if any."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open_url(
                request.Request(f"http://127.0.0.1:{port}/json/list", method="GET"), timeout=2
            ) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            for target in targets if isinstance(targets, list) else []:
                if target.get("type") != "page":
                    continue
                if "music.163.com" in str(target.get("url") or ""):
                    ws_url = target.get("webSocketDebuggerUrl")
                    if ws_url:
                        return str(ws_url)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


def _read_music_cookies(port: int, timeout: float = 10.0) -> str:
    """Read music.163.com cookies from a live browser via CDP.

    Attaches to the music.163.com *page* target (more reliable than the
    browser-level session) and reads cookies two ways: Runtime.evaluate
    document.cookie (non-HttpOnly) plus Network.getAllCookies (includes
    HttpOnly).  Any connection failure is treated as "not ready yet" and
    returns "" so the caller retries.
    """
    try:
        import websocket
    except ImportError as err:  # pragma: no cover - guarded by project dependency
        raise BrowserLoginError(
            "缺少 websocket-client 依赖，请先执行 `pip install -e .` 安装依赖后重试。"
        ) from err

    page_ws = _find_page_ws(port, timeout=timeout)
    if page_ws is None:
        return ""
    try:
        ws = websocket.create_connection(page_ws, timeout=timeout)
    except Exception:
        return ""
    try:
        ws.settimeout(1)
        eval_id = 1000
        ws.send(
            json.dumps(
                {
                    "id": eval_id,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.cookie", "returnByValue": True},
                }
            )
        )
        cook_id = 1001
        ws.send(json.dumps({"id": cook_id, "method": "Network.getAllCookies", "params": {}}))
        parts: dict[str, str] = {}
        deadline = time.time() + timeout
        while time.time() < deadline and len(parts) < 2:
            try:
                raw = ws.recv()
            except Exception:
                raw = ""
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mid = data.get("id")
            if mid == eval_id:
                value = (((data.get("result") or {}).get("result") or {}).get("value")) or ""
                parts["eval"] = str(value)
            elif mid == cook_id:
                cookies = (data.get("result") or {}).get("cookies") or []
                music = [c for c in cookies if "163.com" in str(c.get("domain") or "")]
                parts["cookies"] = build_cookie_string(music)
        merged = []
        if parts.get("eval"):
            merged.append(normalize_cookie(parts["eval"]))
        if parts.get("cookies"):
            merged.append(parts["cookies"])
        return "; ".join(x for x in merged if x)
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return ""


def run_official_login(
    timeout: float = 300.0,
    reuse_existing: bool = False,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    """Open the official login page and capture the NetEase cookie.

    By default (reuse_existing=False) the flow opens a fresh temp-profile
    browser window and the user scans the official QR once — reliable and
    fast.  Set reuse_existing=True to first attempt attaching to the user's
    real browser profile (reuses an existing login, but is unreliable on some
    Edge installs and can add long waits).

    Returns a normalized cookie string containing MUSIC_U.  Raises
    MusicFetchError (AUTH_EXPIRED/NETWORK_ERROR) or BrowserLoginError.
    """
    log = on_status or (lambda _message: None)
    exe = find_browser_exe()
    if not exe:
        raise BrowserLoginError(
            "未找到可用的浏览器（Chrome/Edge）。请安装后重试，或改用“粘贴 Cookie”方式登录。"
        )

    proc: Optional[subprocess.Popen[bytes]] = None
    temp_profile: Optional[str] = None
    try:
        # 1) Try the user's real profile first so an existing login is reused.
        cdp_port: Optional[int] = None
        active_profile: Optional[str] = None
        if reuse_existing:
            real_profile = _default_profile_dir(exe)
            log("正在检测浏览器中已保存的网易云登录状态...")
            port = pick_free_port()
            proc = _launch_browser(exe, port, None, LOGIN_URL)
            cdp_port = _wait_for_cdp_ws(real_profile, port, timeout=20)
            if cdp_port is None:
                # The profile is likely held by lingering background processes
                # (Edge keeps them even after the window is closed), or the
                # browser started slowly. End background processes and retry
                # the real profile once before falling back to a scan window.
                log("未检测到可复用的浏览器调试连接，正在结束浏览器后台进程后重试...")
                _kill_background_browsers(exe)
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                proc = None
                time.sleep(2)
                port = pick_free_port()
                proc = _launch_browser(exe, port, None, LOGIN_URL)
                cdp_port = _wait_for_cdp_ws(real_profile, port, timeout=25)
                if cdp_port is None:
                    log("仍无法复用浏览器登录态，将打开一个新的扫码窗口。")
                    if proc is not None:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                    proc = None
            else:
                active_profile = real_profile

        # 2) Otherwise open a clean temp-profile window for scanning.
        if cdp_port is None:
            log("正在打开扫码登录窗口...")
            temp_profile = tempfile.mkdtemp(prefix="music-fetch-login-")
            port = pick_free_port()
            proc = _launch_browser(exe, port, temp_profile, LOGIN_URL)
            cdp_port = _wait_for_cdp_ws(temp_profile, port, timeout=15)
            active_profile = temp_profile

        if cdp_port is None:
            raise BrowserLoginError("浏览器未能启动（调试端口未就绪），请关闭浏览器后重试。")

        deadline = time.time() + timeout
        prompted = False
        noted_cookies = False
        stale_reads = 0
        cookie = ""
        while time.time() < deadline:
            cookie = _read_music_cookies(cdp_port, timeout=8)
            if "MUSIC_U=" in cookie:
                break
            if cookie:
                stale_reads = 0
                if not noted_cookies:
                    log("已检测到浏览器返回的 cookie（尚未包含登录凭证），继续等待扫码...")
                    noted_cookies = True
            else:
                # The browser may have restarted on a new DevTools port;
                # re-discover the endpoint after a few empty reads.
                stale_reads += 1
                if stale_reads >= 3 and active_profile is not None:
                    new_port = _wait_for_cdp_ws(active_profile, cdp_port, timeout=10)
                    if new_port is not None:
                        cdp_port = new_port
                    stale_reads = 0
            if not prompted:
                log("请在打开的浏览器中扫码登录网易云音乐（扫码后稍候将自动完成）。")
                prompted = True
            time.sleep(3)

        if "MUSIC_U=" not in cookie:
            raise MusicFetchError(
                "AUTH_EXPIRED",
                f"等待扫码登录超时（{int(timeout)} 秒）。请重新发起官网登录。",
            )
        log("已获取登录凭证。")
        return normalize_cookie(cookie)
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        if temp_profile:
            try:
                shutil.rmtree(temp_profile, ignore_errors=True)
            except Exception:
                pass


def diagnose(timeout: float = 20.0) -> list[str]:
    """Run each step of the browser-login flow and return status lines.

    Lets a user on a real machine pinpoint exactly where the flow breaks and
    paste the output back for debugging.
    """
    lines: list[str] = []
    exe = find_browser_exe()
    lines.append(f"browser_exe={exe}")
    if not exe:
        lines.append("ERROR: no Chrome/Edge found")
        return lines
    port = pick_free_port()
    lines.append(f"debug_port={port}")
    temp_profile = tempfile.mkdtemp(prefix="music-fetch-diagnose-")
    proc: Optional[subprocess.Popen[bytes]] = None
    try:
        proc = _launch_browser(exe, port, temp_profile, LOGIN_URL)
        cdp_port = _wait_for_cdp_ws(temp_profile, port, timeout=timeout)
        lines.append(f"cdp_port={cdp_port}")
        if cdp_port:
            try:
                import websocket

                lines.append("websocket_client=ok")
            except ImportError:
                lines.append("websocket_client=MISSING")
            page_ws = _find_page_ws(cdp_port, timeout=5)
            lines.append(f"music_page_ws={'yes' if page_ws else 'no'}")
            try:
                cookies = _read_music_cookies(cdp_port, timeout=8)
                lines.append(f"cookies_found={bool(cookies)}")
                if cookies:
                    lines.append(f"cookie_preview={cookies[:80]}")
            except Exception as err:  # noqa: BLE001 - diagnostic
                lines.append(f"read_cookies_error={err!r}")
    except Exception as err:  # noqa: BLE001 - diagnostic
        lines.append(f"launch_error={err!r}")
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            shutil.rmtree(temp_profile, ignore_errors=True)
        except Exception:
            pass
    return lines


__all__ = [
    "BrowserLoginError",
    "LOGIN_URL",
    "build_cookie_string",
    "diagnose",
    "find_browser_exe",
    "pick_free_port",
    "run_official_login",
]
