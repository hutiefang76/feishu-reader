"""
通过Chrome CDP提取飞书文档内容（含自动滚动、富文本样式、表格、图片）
需要Chrome以 --remote-debugging-port=9222 --remote-allow-origins=* 启动

用法:
    python extract_feishu.py <feishu_url> [--wait 8] [--output markdown|text]
    python extract_feishu.py https://xxx.feishu.cn/docx/xxx
"""
import argparse
import json
import sys
import io
import time
import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CDP_ID = 0

def cdp(ws, method, params=None):
    global CDP_ID
    CDP_ID += 1
    msg = {"id": CDP_ID, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == CDP_ID:
            return resp.get("result", {})

def js(ws, expr):
    """执行JS并返回值"""
    r = cdp(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return r.get("result", {}).get("value")


def find_feishu_tab(url):
    """通过CDP HTTP接口查找飞书标签页的WebSocket URL"""
    import urllib.request
    try:
        data = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5).read()
        tabs = json.loads(data)
        for t in tabs:
            if t.get("type") == "page" and url in t.get("url", ""):
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


def open_tab(url):
    """打开新标签页"""
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:9222/json/new?{url}", method="PUT")
    data = urllib.request.urlopen(req, timeout=10).read()
    info = json.loads(data)
    return info["webSocketDebuggerUrl"]


def auto_scroll(ws, max_scrolls=60, scroll_step=800, pause=0.5):
    """自动滚动页面以触发飞书懒加载"""
    # 找到可滚动容器
    container = js(ws, """
    (() => {
        // 飞书文档可能用多种滚动容器
        const candidates = [
            document.querySelector('.docs-reader'),
            document.querySelector('.doc-content-container'),
            document.querySelector('[class*="scrollable"]'),
            document.scrollingElement,
            document.documentElement
        ];
        for (const c of candidates) {
            if (c && c.scrollHeight > c.clientHeight + 10) {
                return c.tagName + '.' + (c.className || '').substring(0, 60);
            }
        }
        return 'BODY';
    })()
    """)

    prev_height = 0
    stable_count = 0
    for i in range(max_scrolls):
        info = js(ws, f"""
        (() => {{
            const el = document.querySelector('.docs-reader')
                || document.scrollingElement
                || document.documentElement;
            el.scrollTop += {scroll_step};
            return JSON.stringify({{
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight
            }});
        }})()
        """)
        if info:
            d = json.loads(info)
            at_bottom = d["scrollTop"] + d["clientHeight"] >= d["scrollHeight"] - 20
            if d["scrollHeight"] == prev_height:
                stable_count += 1
            else:
                stable_count = 0
            prev_height = d["scrollHeight"]
            if at_bottom and stable_count >= 2:
                break
        time.sleep(pause)

    # 滚回顶部
    js(ws, """
    (document.querySelector('.docs-reader') || document.scrollingElement || document.documentElement).scrollTop = 0;
    """)
    time.sleep(0.5)


def extract_content(ws, fmt="markdown"):
    """提取文档主体内容"""
    return js(ws, """
    (() => {
        const root = document.querySelector('[data-content-editable-root]')
            || document.querySelector('.doc-content')
            || document.querySelector('.docs-reader')
            || document.body;
        return root.innerText;
    })()
    """) or ""


def extract_headings(ws):
    return js(ws, """
    (() => {
        const root = document.querySelector('[data-content-editable-root]') || document.body;
        const hs = root.querySelectorAll('h1,h2,h3,h4,h5,h6');
        let out = [];
        hs.forEach(h => out.push(h.tagName + ': ' + h.innerText.replace(/\\s+/g,' ').substring(0, 120)));
        return out.length ? out.join('\\n') : '';
    })()
    """) or ""


def extract_tables(ws):
    return js(ws, """
    (() => {
        const root = document.querySelector('[data-content-editable-root]') || document.body;
        // 飞书表格：标准table 或 grid-based div
        const tables = root.querySelectorAll('table');
        if (!tables.length) return '';
        let out = [];
        tables.forEach((t, i) => {
            const rows = t.querySelectorAll('tr');
            let data = [];
            rows.forEach((r, ri) => {
                let cells = [];
                r.querySelectorAll('td,th').forEach(c => cells.push(c.innerText.replace(/\\n/g,' ').trim()));
                data.push(cells.join(' | '));
                if (ri === 0) data.push(cells.map(() => '---').join(' | '));
            });
            out.push('[表格' + (i+1) + ' (' + rows.length + '行)]\\n' + data.join('\\n'));
        });
        return out.join('\\n\\n');
    })()
    """) or ""


def extract_styles(ws):
    """提取删除线、颜色高亮、加粗等富文本标记"""
    return js(ws, """
    (() => {
        const root = document.querySelector('[data-content-editable-root]') || document.body;
        let out = [];

        // 删除线 (飞书用 strike-through class + line-through style)
        const strikes = root.querySelectorAll('.strike-through, [style*="line-through"], del, s');
        if (strikes.length) {
            out.push('~~删除线~~ (' + strikes.length + '处):');
            let seen = new Set();
            strikes.forEach(s => {
                const t = s.innerText.trim().substring(0, 120);
                if (t && !seen.has(t)) { seen.add(t); out.push('  ~~' + t + '~~'); }
            });
        }

        // 颜色高亮 (飞书用 text-highlight-background-* CSS class)
        const highlights = root.querySelectorAll('[class*="text-highlight-background"]');
        if (highlights.length) {
            let colorMap = {};
            highlights.forEach(el => {
                const cls = Array.from(el.classList).find(c => c.startsWith('text-highlight-background-'));
                const color = cls ? cls.replace('text-highlight-background-', '') : 'unknown';
                if (!colorMap[color]) colorMap[color] = [];
                const t = el.innerText.trim().substring(0, 80);
                if (t && colorMap[color].length < 5) colorMap[color].push(t);
            });
            for (let color in colorMap) {
                out.push('背景色[' + color + '] (' + colorMap[color].length + '处):');
                colorMap[color].forEach(t => out.push('  - ' + t));
            }
        }

        // 文字颜色 (飞书用 text-color-* CSS class)
        const textColors = root.querySelectorAll('[class*="text-color-"]');
        if (textColors.length) {
            let cMap = {};
            textColors.forEach(el => {
                const cls = Array.from(el.classList).find(c => c.startsWith('text-color-') && !c.includes('highlight'));
                if (!cls) return;
                const color = cls.replace('text-color-', '');
                if (!cMap[color]) cMap[color] = [];
                const t = el.innerText.trim().substring(0, 80);
                if (t && cMap[color].length < 5) cMap[color].push(t);
            });
            for (let color in cMap) {
                out.push('文字色[' + color + '] (' + cMap[color].length + '处):');
                cMap[color].forEach(t => out.push('  - ' + t));
            }
        }

        // inline color style (fallback)
        const inlineColored = root.querySelectorAll('[style*="color:"]');
        let inlineMap = {};
        inlineColored.forEach(el => {
            const c = el.style.color;
            if (c && c !== 'rgb(0, 0, 0)' && c !== 'black' && c !== '') {
                if (!inlineMap[c]) inlineMap[c] = [];
                const t = el.innerText.trim().substring(0, 80);
                if (t && inlineMap[c].length < 3) inlineMap[c].push(t);
            }
        });
        for (let c in inlineMap) {
            out.push('inline颜色(' + c + '):');
            inlineMap[c].forEach(t => out.push('  - ' + t));
        }

        return out.join('\\n');
    })()
    """) or ""


def extract_images(ws):
    return js(ws, """
    (() => {
        const imgs = document.querySelectorAll('img');
        let out = [];
        imgs.forEach((img, i) => {
            const src = img.src || '';
            const alt = img.alt || '';
            const w = img.naturalWidth || img.width;
            const h = img.naturalHeight || img.height;
            if (src && !src.includes('data:image/svg') && w > 50) {
                out.push('[图片' + (i+1) + '] ' + w + 'x' + h + (alt ? ' alt="'+alt+'"' : '') + ' ' + src.substring(0, 150));
            }
        });
        return out.join('\\n');
    })()
    """) or ""


def run(feishu_url, wait=8, output_fmt="text"):
    # 查找或打开标签页
    ws_url = find_feishu_tab(feishu_url)
    if ws_url:
        print(f"[复用已有标签页]")
    else:
        print(f"[打开新标签页] {feishu_url}")
        ws_url = open_tab(feishu_url)

    ws = websocket.create_connection(ws_url, timeout=60)
    print(f"[等待页面加载 {wait}s...]")
    time.sleep(wait)

    # 获取标题
    title = js(ws, "document.title") or ""
    # 清理飞书标题中的零宽字符
    clean_title = ''.join(c for c in title if ord(c) > 31 and c not in '\u200b\u200c\u200d\u2060\ufeff\u2061\u2062\u2063\u2064\u2065\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f\u2028\u2029')
    print(f"\n{'='*60}")
    print(f"文档: {clean_title}")
    print(f"URL: {feishu_url}")
    print(f"{'='*60}")

    # 自动滚动加载全文
    print("[自动滚动加载全文...]")
    auto_scroll(ws)
    time.sleep(1)

    # 提取标题结构
    headings = extract_headings(ws)
    if headings:
        print(f"\n--- 文档结构 ---")
        print(headings)

    # 提取正文
    text = extract_content(ws)
    if text:
        # 清理零宽字符
        text = ''.join(c for c in text if ord(c) > 31 or c in '\n\t')
        print(f"\n--- 正文 ({len(text)}字) ---")
        print(text)

    # 表格
    tables = extract_tables(ws)
    if tables:
        print(f"\n--- 表格 ---")
        print(tables)

    # 富文本样式
    styles = extract_styles(ws)
    if styles:
        print(f"\n--- 富文本标记 ---")
        print(styles)

    # 图片
    images = extract_images(ws)
    if images:
        print(f"\n--- 图片资源 ---")
        print(images)

    print(f"\n{'='*60}")
    print("[提取完成]")
    ws.close()


def main():
    parser = argparse.ArgumentParser(description="飞书文档内容提取 (Chrome CDP)")
    parser.add_argument("url", help="飞书文档URL")
    parser.add_argument("--wait", type=int, default=8, help="页面加载等待秒数 (默认8)")
    parser.add_argument("--output", choices=["text", "markdown"], default="text", help="输出格式")
    args = parser.parse_args()
    run(args.url, args.wait, args.output)


if __name__ == "__main__":
    main()
