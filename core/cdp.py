"""
CDP (Chrome DevTools Protocol) communication primitives.
CDP 通信原语：发送命令、执行 JS、管理标签页。
"""
import json
import urllib.request
import urllib.parse

from core.config import CDP_PORT

_cdp_id = 0


# ============================================================
# Low-level CDP communication
# ============================================================

def cdp(ws, method, params=None):
    """Send a CDP command and wait for the response."""
    global _cdp_id
    _cdp_id += 1
    msg = {"id": _cdp_id, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == _cdp_id:
            if "error" in resp:
                print(f"[CDP Error] {resp['error']}")
            return resp.get("result", {})


def js(ws, expr, await_promise=False):
    """Execute JavaScript in the page and return the result value."""
    r = cdp(ws, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": await_promise,
    })
    val = r.get("result", {})
    if val.get("type") == "undefined":
        return None
    return val.get("value")


# ============================================================
# Tab management
# ============================================================

def get_tabs():
    """List all Chrome tabs via CDP HTTP API."""
    try:
        data = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5).read()
        return json.loads(data)
    except Exception:
        return []


def find_tab(url_fragment):
    """Find a tab whose URL contains the given fragment. Returns WebSocket URL or None."""
    for t in get_tabs():
        if t.get("type") == "page" and url_fragment in t.get("url", ""):
            return t.get("webSocketDebuggerUrl")
    return None


def get_any_tab():
    """Get the WebSocket URL of any open page tab."""
    for t in get_tabs():
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    return None


def open_tab(url):
    """Open a new tab and return its WebSocket URL."""
    encoded = urllib.parse.quote(url, safe='')
    req = urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/new?{encoded}", method="PUT")
    data = urllib.request.urlopen(req, timeout=10).read()
    return json.loads(data)["webSocketDebuggerUrl"]


def close_tab_by_ws(ws_url):
    """Close a tab identified by its WebSocket URL."""
    try:
        for t in get_tabs():
            if t.get("webSocketDebuggerUrl") == ws_url:
                tid = t.get("id", "")
                if tid:
                    urllib.request.urlopen(
                        urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/close/{tid}"),
                        timeout=5
                    )
                return
    except Exception:
        pass
