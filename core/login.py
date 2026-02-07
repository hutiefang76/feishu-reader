"""
Feishu login flow with helper page.
飞书登录流程 + 提醒页面。
"""
import http.server
import threading
import time

from core.cdp import cdp, js, open_tab, close_tab_by_ws
from core.session import save_cookies

# Module-level state for login helper
_login_server = None
_login_server_thread = None
_login_status_flag = "waiting"  # waiting / logged_in / timeout
_login_ws_ref = None
_login_ws_lock = threading.Lock()


# ============================================================
# Helper page HTML
# ============================================================

def _make_login_html(screenshot_b64=None):
    img_tag = '<p style="color:#aaa">Screenshot loading... Please switch to Chrome to scan QR<br>截图加载中，请切到 Chrome 窗口扫码</p>'
    if screenshot_b64:
        img_tag = f'<img src="data:image/png;base64,{screenshot_b64}" style="max-width:360px;border-radius:8px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,.15)">'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Feishu Login / 飞书登录</title>
<style>
body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f5f5f5}}
.card{{background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.1);
text-align:center;max-width:480px}}
h2{{color:#333;margin-bottom:16px}}
p{{color:#666;line-height:1.6}}
.status{{color:#999;font-size:14px;margin-top:12px}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;
margin-right:6px;animation:pulse 1.5s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
</style></head><body><div class="card">
<h2>🔐 Feishu Login / 飞书登录</h2>
<p>Scan QR code or enter credentials in the Feishu login page<br>请在飞书登录页面扫码或输入账号密码</p>
{img_tag}
<p class="status"><span class="dot"></span>Waiting... auto-refresh every 3s / 等待中... 每 3 秒刷新</p>
<p style="color:#bbb;font-size:12px">This page closes automatically on login / 登录成功后自动关闭</p>
</div>
<script>setTimeout(()=>location.reload(), 3000);</script>
</body></html>"""


def _make_login_success_html():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Login Success</title>
<style>
body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4}
.card{background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.1);
text-align:center;max-width:400px}
</style></head><body><div class="card">
<h2>✅ Login Successful / 登录成功</h2>
<p style="color:#16a34a">Session saved. This page will close automatically.<br>Session 已保存，此页面将自动关闭</p>
</div>
<script>setTimeout(()=>window.close(), 2000);</script>
</body></html>"""


# ============================================================
# Live screenshot + HTTP server
# ============================================================

def _live_screenshot():
    """Thread-safe screenshot of the Feishu login page."""
    global _login_ws_ref
    if not _login_ws_ref:
        return None
    if not _login_ws_lock.acquire(timeout=3):
        return None
    try:
        result = cdp(_login_ws_ref, "Page.captureScreenshot", {"format": "png", "quality": 60})
        if result and result.get("data"):
            return result["data"]
    except Exception:
        pass
    finally:
        _login_ws_lock.release()
    return None


def _start_login_helper():
    """Start local HTTP server for login helper page. Returns port number."""
    global _login_server, _login_server_thread, _login_status_flag
    _login_status_flag = "waiting"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if _login_status_flag == "logged_in":
                self.wfile.write(_make_login_success_html().encode("utf-8"))
            else:
                fresh_b64 = _live_screenshot()
                self.wfile.write(_make_login_html(fresh_b64).encode("utf-8"))

        def log_message(self, *a):
            pass

    _login_server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = _login_server.server_address[1]
    _login_server_thread = threading.Thread(target=_login_server.serve_forever, daemon=True)
    _login_server_thread.start()
    return port


def _stop_login_helper():
    global _login_server, _login_ws_ref
    if _login_server:
        _login_server.shutdown()
        _login_server = None
    _login_ws_ref = None


# ============================================================
# Login detection and wait
# ============================================================

def check_login(ws):
    """Check if the current page indicates logged-in state."""
    result = js(ws, """
    (() => {
        if (location.href.includes('/accounts/page/login')
            || location.href.includes('passport.feishu.cn')) return 'not_logged_in';
        if (document.querySelector('#docx') || document.querySelector('.help-center-content')
            || document.querySelector('[data-content-editable-root]')) return 'logged_in';
        if (document.body && document.body.innerText &&
            (document.body.innerText.includes('无权限') || document.body.innerText.includes('请登录')))
            return 'not_logged_in';
        return 'unknown';
    })()
    """)
    return result or 'unknown'


def wait_for_login(ws, feishu_url, timeout=300):
    """
    Wait for user to complete Feishu login.
    Opens a helper page with live screenshots, polls for login completion.
    Returns True if login succeeded, False on timeout.
    """
    global _login_status_flag, _login_ws_ref

    print("[Login/登录] Checking login status / 检查登录状态...")
    status = check_login(ws)
    if status == 'logged_in':
        print("[Login/登录] ✅ Already logged in / 已登录")
        save_cookies(ws)
        return True

    print("[Login/登录] Feishu login required / 需要登录飞书...")
    _login_ws_ref = ws

    # Start helper server first (instant, non-blocking)
    helper_port = _start_login_helper()

    # Check if already on login page
    current_url = js(ws, "location.href") or ""
    already_on_login = "passport.feishu.cn" in current_url or "accounts/page/login" in current_url

    helper_ws = None
    if not already_on_login:
        js(ws, f'window.location.href = "https://passport.feishu.cn/accounts/page/login?redirect_uri={feishu_url}";')
        try:
            helper_ws = open_tab(f"http://127.0.0.1:{helper_port}")
        except Exception:
            pass
        time.sleep(3)
    else:
        try:
            helper_ws = open_tab(f"http://127.0.0.1:{helper_port}")
        except Exception:
            pass
        time.sleep(1)

    print("[Login/登录] ════════════════════════════════════════")
    print("[Login/登录]  Please scan QR code or enter credentials in Chrome")
    print("[Login/登录]  请在 Chrome 飞书登录页扫码或输入账号密码")
    print("[Login/登录]  Helper page auto-refreshes every 3s / 提醒页面每 3 秒自动刷新")
    print("[Login/登录]  Waiting for login... (5 min timeout) / 等待登录...（最长 5 分钟）")
    print("[Login/登录] ════════════════════════════════════════")

    # Poll for login completion
    start = time.time()
    doc_url_fragments = ["feishu.cn/docx/", "feishu.cn/wiki/", "feishu.cn/hc/",
                         "feishu.cn/sheets/", "feishu.cn/base/"]

    while time.time() - start < timeout:
        time.sleep(3)
        elapsed = int(time.time() - start)
        try:
            with _login_ws_lock:
                current_url = js(ws, "location.href") or ""

            if any(x in current_url for x in doc_url_fragments):
                return _login_success(ws, helper_ws)

            with _login_ws_lock:
                if check_login(ws) == 'logged_in':
                    return _login_success(ws, helper_ws)
        except Exception:
            pass

        if elapsed > 0 and elapsed % 30 == 0:
            remaining = timeout - elapsed
            print(f"[Login/登录] ⏳ Waited {elapsed}s, {remaining}s remaining / 已等待 {elapsed}s，剩余 {remaining}s...")

    print("[Login/登录] ⏰ Login timeout (5 min), please retry / 登录超时，请重新运行")
    _login_status_flag = "timeout"
    if helper_ws:
        close_tab_by_ws(helper_ws)
    _stop_login_helper()
    return False


def _login_success(ws, helper_ws):
    """Handle successful login: save cookies, close helper."""
    global _login_status_flag
    print("[Login/登录] ✅ Login successful / 登录成功！")
    _login_status_flag = "logged_in"
    with _login_ws_lock:
        save_cookies(ws)
    time.sleep(2)
    if helper_ws:
        close_tab_by_ws(helper_ws)
    _stop_login_helper()
    return True


def login_only():
    """Standalone login flow — open browser, wait for user to log in."""
    import websocket
    from core.chrome import is_cdp_alive, launch_chrome
    from core.cdp import get_any_tab, open_tab
    from core.session import load_cookies

    if not is_cdp_alive():
        if not launch_chrome("https://passport.feishu.cn/accounts/page/login"):
            return False
        time.sleep(3)

    ws_url = get_any_tab()
    if not ws_url:
        ws_url = open_tab("https://passport.feishu.cn/accounts/page/login")
        time.sleep(2)

    ws = websocket.create_connection(ws_url, timeout=60)
    cdp(ws, "Network.enable")
    load_cookies(ws)
    js(ws, 'window.location.href = "https://passport.feishu.cn/accounts/page/login";')
    time.sleep(3)

    print("[Login/登录] Please complete login in browser / 请在浏览器中完成登录...")
    start = time.time()
    while time.time() - start < 300:
        time.sleep(3)
        try:
            url = js(ws, "location.href") or ""
            if "passport.feishu.cn" not in url and "accounts/page/login" not in url:
                print("[Login/登录] ✅ Login successful / 登录成功")
                save_cookies(ws)
                ws.close()
                return True
        except Exception:
            pass
    ws.close()
    return False
