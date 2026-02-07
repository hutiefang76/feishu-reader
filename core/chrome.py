"""
Chrome discovery, launch, and CDP port management.
Chrome 查找、启动、CDP 端口管理。
"""
import os
import platform
import shutil
import subprocess
import time
import urllib.request

from core.config import CDP_PORT, CHROME_PROFILE


def find_chrome():
    """Find Chrome/Chromium executable path. Returns path or None."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
    else:
        candidates = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]

    for c in candidates:
        if os.path.isfile(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def is_cdp_alive():
    """Check if Chrome CDP is responding on the configured port."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        return True
    except Exception:
        return False


def is_chrome_running():
    """Check if any Chrome process is running (even without CDP)."""
    system = platform.system()
    try:
        if system == "Windows":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                               capture_output=True, text=True, timeout=5)
            return "chrome.exe" in r.stdout.lower()
        else:
            r = subprocess.run(["pgrep", "-f", "Google Chrome|chromium"],
                               capture_output=True, timeout=5)
            return r.returncode == 0
    except Exception:
        return False


def launch_chrome(url=None):
    """
    Launch Chrome with CDP debugging enabled.
    Returns True if CDP is ready, False on failure.

    Handles the case where Chrome is already running without CDP
    by using a separate user-data-dir (won't conflict).
    """
    chrome = find_chrome()
    if not chrome:
        print("[Error/错误] Chrome not found / 未找到 Chrome，请运行 setup 脚本")
        return False

    if is_cdp_alive():
        return True

    # If Chrome is running without CDP, warn the user
    if is_chrome_running():
        print("[Info/信息] Chrome is running but CDP is not enabled / Chrome 在运行但未开启 CDP")
        print("[Info/信息] Starting a separate CDP instance / 启动独立 CDP 实例...")

    os.makedirs(CHROME_PROFILE, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-infobars",
        "--hide-crash-restore-bubble",
    ]
    if url:
        args.append(url)

    print(f"[Chrome] Starting CDP on port {CDP_PORT} / 启动 CDP (端口 {CDP_PORT})")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(30):
        time.sleep(1)
        if is_cdp_alive():
            print("[Chrome] ✅ CDP ready / CDP 就绪")
            return True

    print("[Error/错误] Chrome CDP startup timeout / CDP 启动超时")
    return False
