"""
Paths, constants, platform detection.
路径、常量、平台检测。
"""
import os
import re
import sys
import io
import platform

# Ensure UTF-8 output (critical for Chinese content)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

CDP_PORT = 9222
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_cache_dir():
    """Platform-specific cache directory for cookies, Chrome profile, etc."""
    system = platform.system()
    if system == "Darwin":
        base = os.path.expanduser("~/Library/Caches")
    elif system == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    cache = os.path.join(base, "feishu-reader")
    os.makedirs(cache, exist_ok=True)
    return cache


def get_output_dir():
    """Default output directory for extracted documents."""
    out = os.path.join(PROJECT_DIR, "output")
    os.makedirs(out, exist_ok=True)
    return out


CACHE_DIR = get_cache_dir()
COOKIE_FILE = os.path.join(CACHE_DIR, "cookies.json")
CHROME_PROFILE = os.path.join(CACHE_DIR, "chrome-profile")


def safe_filename(title, max_len=80):
    """Sanitize a string for use as a filename."""
    return re.sub(r'[\\/:*?"<>|\s]+', '_', title).strip('_')[:max_len] or "feishu_doc"


def parse_doc_type(url):
    """Detect Feishu document type from URL: docx/wiki/sheet/hc/unknown."""
    if '/hc/' in url:
        return 'hc'
    if '/docx/' in url:
        return 'docx'
    if '/wiki/' in url:
        return 'wiki'
    if '/sheets/' in url or '/base/' in url:
        return 'sheet'
    return 'unknown'
