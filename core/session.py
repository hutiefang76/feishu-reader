"""
Cookie / Session persistence.
Cookie / Session 持久化。
"""
import json
import os

from core.config import COOKIE_FILE
from core.cdp import cdp


def save_cookies(ws):
    """Save Feishu cookies from browser to local cache file."""
    result = cdp(ws, "Network.getAllCookies")
    cookies = result.get("cookies", [])
    feishu = [c for c in cookies if "feishu" in c.get("domain", "")]
    if feishu:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(feishu, f, ensure_ascii=False, indent=2)
        print(f"[Session] Saved {len(feishu)} cookies / 已保存 {len(feishu)} 条 cookie")
    return feishu


def load_cookies(ws):
    """Load cached Feishu cookies into the browser."""
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        if not cookies:
            return False
        for c in cookies:
            params = {k: v for k, v in c.items() if k in (
                "name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires"
            )}
            if params.get("expires") == -1:
                params.pop("expires", None)
            cdp(ws, "Network.setCookie", params)
        print(f"[Session] Loaded {len(cookies)} cached cookies / 已加载 {len(cookies)} 条缓存 cookie")
        return True
    except Exception as e:
        print(f"[Session] Load failed / 加载失败: {e}")
        return False
