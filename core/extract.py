"""
Main extraction orchestrator.
提取主流程编排。

Handles: Chrome launch → tab management → login → doc ready → extract → images → save
"""
import json
import os
import re
import time
import base64

from core.config import get_output_dir, safe_filename
from core.chrome import is_cdp_alive, launch_chrome
from core.cdp import cdp, js, find_tab, get_any_tab, open_tab
from core.session import save_cookies, load_cookies
from core.login import check_login, wait_for_login
from core.markdown import cleanup_markdown


# ============================================================
# Page helpers
# ============================================================

def dismiss_popups(ws):
    """Dismiss any modal dialogs or popups on the page."""
    js(ws, """
    (() => {
        document.querySelectorAll('[class*="modal"] [class*="close"]').forEach(b => b.click());
        document.querySelectorAll('[class*="dialog"] [class*="close"]').forEach(b => b.click());
        document.querySelectorAll('button').forEach(b => {
            if (['知道了','我知道了','确定','关闭','取消'].includes(b.textContent.trim())) b.click();
        });
    })()
    """)


def wait_for_doc_ready(ws, timeout=30):
    """Wait for the Feishu document to finish loading. Returns doc type or None."""
    print("[Wait/等待] Document loading / 文档加载中...")
    start = time.time()
    while time.time() - start < timeout:
        ready = js(ws, """
        (() => {
            if (window.PageMain && window.PageMain.blockManager &&
                window.PageMain.blockManager.rootBlockModel) return 'pagemain';
            if (document.querySelector('#docx > div div[data-block-id]')) return 'docx';
            if (document.querySelector('.help-center-content')) return 'hc';
            return null;
        })()
        """)
        if ready:
            print(f"[Wait/等待] ✅ Document ready (type: {ready}) / 文档就绪")
            return ready
        time.sleep(1)
        dismiss_popups(ws)
    print("[Wait/等待] ⏰ Document load timeout / 文档加载超时")
    return None


# ============================================================
# Sheet scroll-loading
# ============================================================

def scroll_to_load_sheets(ws, timeout=60):
    """Scroll the page to trigger lazy-loading of Sheet blocks."""
    has_sheets = js(ws, """
    (() => {
        const root = window.PageMain?.blockManager?.rootBlockModel;
        if (!root) return false;
        return root.children.some(b => b.type === 'sheet');
    })()
    """)
    if not has_sheets:
        return

    print("[Scroll/滚动] Sheet blocks detected, scroll-loading / 检测到 sheet，滚动加载...")
    js(ws, """
    (() => {
        const c = document.querySelector('#docx > div') || document.querySelector('.bear-web-x-container');
        if (!c) return;
        c.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:300, clientY:300}));
        c.scrollTop = 1; c.scrollTop = 0;
    })()
    """)
    time.sleep(0.3)

    js(ws, """
    (() => {
        window.__sheet_scroll_done__ = false;
        const c = document.querySelector('#docx > div') || document.querySelector('.bear-web-x-container');
        if (!c) { window.__sheet_scroll_done__ = true; return; }
        const ch = c.clientHeight;
        let y = 0, lastSH = 0, stable = 0;
        function go() {
            const sh = c.scrollHeight;
            if (sh === lastSH) stable++; else stable = 0;
            lastSH = sh;
            if (stable >= 3 || y > sh + ch) {
                let sy = 0;
                function scan() {
                    if (sy + ch >= c.scrollHeight - 10) {
                        c.scrollTop = 0;
                        window.__sheet_scroll_done__ = true;
                        return;
                    }
                    sy += ch;
                    c.scrollTop = sy;
                    setTimeout(scan, 200);
                }
                c.scrollTop = 0;
                setTimeout(scan, 300);
                return;
            }
            y += ch * 3;
            c.scrollTop = y;
            setTimeout(go, 60);
        }
        setTimeout(go, 100);
    })()
    """)

    start = time.time()
    while time.time() - start < timeout:
        done = js(ws, "window.__sheet_scroll_done__")
        if done:
            break
        time.sleep(0.5)
    print("[Scroll/滚动] Sheet loading complete / sheet 加载完成")
    time.sleep(1)


# ============================================================
# PageMain extraction
# ============================================================

def _load_pagemain_js():
    """Load the PageMain extraction JS. Reads from pagemain.js if available, else uses inline."""
    js_path = os.path.join(os.path.dirname(__file__), "pagemain.js")
    if os.path.exists(js_path):
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()
    # Fallback: import from legacy feishu_cdp
    from feishu_cdp import PAGEMAIN_EXTRACT_JS
    return PAGEMAIN_EXTRACT_JS


def extract_via_pagemain(ws):
    """Extract document via window.PageMain. Returns (markdown, title, images_info)."""
    print("[Extract/提取] Extracting via PageMain / 通过 PageMain 提取...")

    ready = js(ws, """
    (() => {
        const root = window.PageMain?.blockManager?.rootBlockModel;
        if (!root) return false;
        return root.children.every(b => b.snapshot && b.snapshot.type !== 'pending');
    })()
    """)
    if not ready:
        print("[Extract/提取] Waiting for blocks to load / 等待 block 加载...")
        time.sleep(3)

    scroll_to_load_sheets(ws)

    pagemain_js = _load_pagemain_js()
    result_str = js(ws, pagemain_js)
    if not result_str:
        print("[Extract/提取] ❌ Script returned empty / 脚本返回空")
        return None, None, None

    try:
        result = json.loads(result_str)
    except json.JSONDecodeError as e:
        print(f"[Extract/提取] ❌ JSON parse failed / JSON 解析失败: {e}")
        return None, None, None

    if result.get("error"):
        print(f"[Extract/提取] ❌ {result['error']}")
        return None, None, None

    md = result.get("markdown", "")
    title = result.get("title", "")
    images = result.get("images", [])
    block_count = result.get("blockCount", 0)

    pipes = md.count("|")
    strikes = md.count("~~")
    fonts = md.count("<font")
    marks = md.count("<mark")
    print(f"[Extract/提取] ✅ {len(md)} chars, {block_count} blocks")
    print(f"[Extract/提取]   pipes: {pipes}, strikethrough: {strikes}, color: {fonts}, background: {marks}")

    return md, title, images


# ============================================================
# Help Center extraction
# ============================================================

def extract_hc_page(ws):
    """Extract a Feishu Help Center page (non-docx)."""
    result = js(ws, r"""
    (() => {
        let title = document.title || '';
        const hc = document.querySelector('.help-center-content')
            || document.querySelector('article')
            || document.querySelector('[role="main"]');
        if (!hc) return JSON.stringify({title: title, content: document.body ? document.body.innerText : ''});
        let html = hc.innerHTML;
        html = html.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n\n');
        html = html.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n\n');
        html = html.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n\n');
        html = html.replace(/<p[^>]*>(.*?)<\/p>/gi, '$1\n\n');
        html = html.replace(/<li[^>]*>(.*?)<\/li>/gi, '- $1\n');
        html = html.replace(/<br\s*\/?>/gi, '\n');
        html = html.replace(/<a href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)');
        html = html.replace(/<code>(.*?)<\/code>/gi, '`$1`');
        html = html.replace(/<[^>]+>/g, '');
        html = html.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
        return JSON.stringify({title: title, content: html.trim()});
    })()
    """)
    if result:
        return json.loads(result)
    return None


def get_doc_title(ws):
    """Get the document title from PageMain or page title."""
    title = js(ws, """
    (() => {
        const root = window.PageMain?.blockManager?.rootBlockModel;
        if (root && root.zoneState && root.zoneState.allText)
            return root.zoneState.allText.replace(/\\n$/, '');
        let t = document.title || '';
        t = t.replace(/ - 飞书云文档$/, '').replace(/ - Feishu$/, '').trim();
        return t || '';
    })()
    """)
    return (title or "").strip() or "feishu_doc"


# ============================================================
# Image download
# ============================================================

def resolve_and_download_images(ws, md_text, imgs_dir):
    """Resolve __IMAGE_TOKEN__ placeholders and download images."""
    tokens = re.findall(r'__IMAGE_TOKEN__(\w+)', md_text)
    if not tokens:
        return md_text, 0

    os.makedirs(imgs_dir, exist_ok=True)
    imgs_folder = os.path.basename(imgs_dir)
    count = 0

    for token in tokens:
        try:
            url = js(ws, f"""
            (async () => {{
                const PM = window.PageMain;
                if (!PM) return null;
                const root = PM.blockManager.rootBlockModel;
                function findImage(block) {{
                    if (block.type === 'image' && block.snapshot?.image?.token === '{token}') return block;
                    for (const child of (block.children || [])) {{
                        const found = findImage(child);
                        if (found) return found;
                    }}
                    return null;
                }}
                const imgBlock = findImage(root);
                if (!imgBlock || !imgBlock.imageManager) return null;
                return new Promise((resolve) => {{
                    imgBlock.imageManager.fetch(
                        {{ token: '{token}', isHD: true, fuzzy: false }},
                        {{}},
                        (sources) => resolve(sources?.src || sources?.originSrc || null)
                    );
                }});
            }})()
            """, await_promise=True)

            if not url:
                continue

            b64 = js(ws, f"""
            (async () => {{
                try {{
                    const resp = await fetch("{url}", {{ credentials: 'include' }});
                    const blob = await resp.blob();
                    return new Promise((resolve) => {{
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result.split(',')[1]);
                        reader.readAsDataURL(blob);
                    }});
                }} catch(e) {{ return null; }}
            }})()
            """, await_promise=True)

            if b64:
                ext = ".png"
                for e, exts in [(".jpg", [".jpg", ".jpeg"]), (".gif", [".gif"]), (".webp", [".webp"])]:
                    if any(x in url for x in exts):
                        ext = e
                        break
                fname = f"img_{count}{ext}"
                fpath = os.path.join(imgs_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(base64.b64decode(b64))
                md_text = md_text.replace(f"__IMAGE_TOKEN__{token}", f"{imgs_folder}/{fname}")
                count += 1
                print(f"[Image/图片] ✅ {fname}")
        except Exception as e:
            print(f"[Image/图片] Download failed / 下载失败 ({token}): {e}")

    if count:
        print(f"[Image/图片] Downloaded {count}/{len(tokens)}")
    return md_text, count


# ============================================================
# Main entry: extract_via_cdp
# ============================================================

def extract_via_cdp(feishu_url, output_path=None, wait=10):
    """
    Extract a Feishu document via CDP + PageMain.
    Returns {"success": bool, "md_path": str, "title": str, ...}
    """
    import websocket

    # 1. Ensure Chrome is running with CDP
    if not is_cdp_alive():
        if not launch_chrome():
            return {"success": False, "error": "Chrome launch failed / Chrome 启动失败"}

    # 2. Open or reuse tab
    ws_url = find_tab(feishu_url)
    if ws_url:
        ws = websocket.create_connection(ws_url, timeout=60)
        cdp(ws, "Network.enable")
        cdp(ws, "Page.enable")
        js(ws, "location.reload()")
    else:
        any_ws = get_any_tab()
        if any_ws:
            tmp = websocket.create_connection(any_ws, timeout=60)
            cdp(tmp, "Network.enable")
            load_cookies(tmp)
            tmp.close()
        ws_url = open_tab(feishu_url)
        ws = websocket.create_connection(ws_url, timeout=60)
        cdp(ws, "Network.enable")
        cdp(ws, "Page.enable")
        load_cookies(ws)

    # 3. Wait for page load
    time.sleep(max(wait, 5))
    dismiss_popups(ws)

    # 4. Check login
    login_status = check_login(ws)
    if login_status != 'logged_in':
        print("[CDP] Login required / 需要登录...")
        if not wait_for_login(ws, feishu_url):
            ws.close()
            return {"success": False, "error": "Login failed or timeout / 登录失败或超时"}
        js(ws, f'window.location.href = "{feishu_url}";')
        time.sleep(max(wait, 5))
        dismiss_popups(ws)

    # 5. Wait for document ready
    doc_type = wait_for_doc_ready(ws)
    if not doc_type:
        ws.close()
        return {"success": False, "error": "Document load timeout / 文档加载超时"}

    save_cookies(ws)

    # 6. Extract
    md_text = None
    if doc_type in ('pagemain', 'docx'):
        md_text, title_from_pm, images_info = extract_via_pagemain(ws)
    elif doc_type == 'hc':
        hc_result = extract_hc_page(ws)
        if hc_result:
            md_text = f"# {hc_result['title']}\n\n{hc_result['content']}"

    if not md_text or len(md_text.strip()) < 10:
        ws.close()
        return {"success": False, "error": "Extracted content is empty / 提取内容为空"}

    # 7. Title and output path
    title = get_doc_title(ws)
    safe_title = safe_filename(title)
    if not output_path:
        output_path = os.path.join(get_output_dir(), f"{safe_title}.md")
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # 8. Download images
    imgs_dir = os.path.join(
        os.path.dirname(output_path),
        os.path.splitext(os.path.basename(output_path))[0] + "_imgs"
    )
    md_text, img_count = resolve_and_download_images(ws, md_text, imgs_dir)
    ws.close()

    # 9. Cleanup and save
    md_text = cleanup_markdown(md_text, title)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"[CDP] ✅ Output: {output_path}")
    return {
        "success": True,
        "md_path": os.path.abspath(output_path),
        "title": title,
        "method": "cdp_pagemain",
        "image_count": img_count,
    }
