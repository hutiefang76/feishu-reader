"""
飞书文档提取 — CDP 层
通过 Chrome DevTools Protocol 访问飞书内部数据模型 (window.PageMain)，
直接从 block 树提取完整文档内容，转为 Markdown。

核心策略 (PageMain 方案):
  飞书页面暴露了 window.PageMain.blockManager.rootBlockModel，
  包含完整的文档 block 树（文本、标题、表格、图片、代码块等），
  每个 block 的 zoneState.content.ops 包含文本和样式属性
  (bold/italic/strikethrough/textHighlight/textHighlightBackground/link 等)。

  借鉴 cloud-document-converter Chrome 扩展的思路，
  通过 CDP Runtime.evaluate 直接访问这个数据模型，
  在浏览器端完成 block→Markdown 转换，返回结果给 Python。

  优势:
  - 不需要滚动加载（数据模型包含全部内容）
  - 不需要 DOM 解析（直接读内部数据）
  - 不需要剪贴板模拟（无 isTrusted 问题）
  - 保留表格、颜色、删除线、图片等完整信息
"""
import json
import os
import re
import time
import base64
import threading
import http.server
import platform
from feishu_common import (
    cdp, js, CACHE_DIR, CDP_PORT,
    find_chrome, is_cdp_alive, launch_chrome,
    get_tabs, find_tab, get_any_tab, open_tab, close_tab_by_ws,
    save_cookies, load_cookies,
    get_output_dir, safe_filename, parse_doc_type,
)


# ============================================================
# PageMain block 树 → Markdown 注入脚本
# ============================================================
# 这段 JS 会注入到飞书页面执行，直接访问 window.PageMain，
# 递归遍历 block 树，转换为 Markdown 字符串返回。
PAGEMAIN_EXTRACT_JS = r"""
(() => {
    const PM = window.PageMain;
    if (!PM || !PM.blockManager || !PM.blockManager.rootBlockModel) {
        return JSON.stringify({error: 'PageMain not found'});
    }
    const root = PM.blockManager.rootBlockModel;
    const images = [];  // 收集图片信息

    // ---- Sheet 数据访问初始化 ----
    // 构建 sheetId → collaSpread._spread sheet 实例的映射
    const _sheetMap = {};  // sheetId → spread sheet instance
    try {
        const sheetBlocks = root.children.filter(b => b.type === 'sheet');
        if (sheetBlocks.length > 0) {
            const sm = sheetBlocks[0].bridge?.bridge?.sheetManager;
            if (sm && sm.sheetComponents) {
                for (const [sheetId, sc] of sm.sheetComponents) {
                    try {
                        const cs = sc.props?.collaSpread;
                        if (!cs || !cs._spread) continue;
                        const spread = cs._spread;
                        const idMap = spread.sheetIdToIndexMap;
                        let idx = -1;
                        if (idMap instanceof Map) idx = idMap.get(sheetId) ?? -1;
                        else if (idMap) idx = idMap[sheetId] ?? -1;
                        if (idx >= 0 && spread.sheets[idx]) {
                            _sheetMap[sheetId] = spread.sheets[idx];
                        }
                    } catch(e) {}
                }
            }
        }
    } catch(e) {}

    // HTML 转义
    function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    // 从 ops 提取带样式的内联文本
    function opsToMd(ops) {
        if (!ops || !ops.length) return '';
        let parts = [];
        for (const op of ops) {
            const attr = op.attributes || {};
            let text = op.insert || '';
            // 跳过 fixEnter
            if (attr.fixEnter) continue;
            // 纯换行无属性跳过
            if (!op.attributes && text === '\n') continue;

            // 行内公式
            if (attr.equation && attr.equation.length > 0) {
                parts.push('$' + attr.equation.replace(/\n$/, '') + '$');
                continue;
            }
            // 行内代码
            if (attr.inlineCode) {
                parts.push('`' + text + '`');
                continue;
            }
            // mention doc (inline-component)
            if (attr['inline-component']) {
                try {
                    const ic = JSON.parse(attr['inline-component']);
                    if (ic.type === 'mention_doc' && ic.data) {
                        text = text + ic.data.title;
                        attr.link = ic.data.raw_url;
                    }
                } catch(e) {}
            }

            let md = text;
            // 颜色/背景
            if (attr.textHighlight || attr.textHighlightBackground) {
                const fg = attr.textHighlight || 'inherit';
                const bg = attr.textHighlightBackground || 'inherit';
                if (bg !== 'inherit') {
                    md = '<mark style="background:' + bg + '">' + esc(md) + '</mark>';
                } else if (fg !== 'inherit') {
                    md = '<font color="' + fg + '">' + esc(md) + '</font>';
                }
            }
            // 删除线
            if (attr.strikethrough) md = '~~' + md + '~~';
            // 粗体
            if (attr.bold) md = '**' + md + '**';
            // 斜体
            if (attr.italic) md = '*' + md + '*';
            // 链接
            if (attr.link) {
                try { md = '[' + md + '](' + decodeURIComponent(attr.link) + ')'; } catch(e) { md = '[' + md + '](' + attr.link + ')'; }
            }
            parts.push(md);
        }
        return parts.join('');
    }

    // 获取 block 的文本内容
    function blockText(block) {
        if (block.zoneState && block.zoneState.content && block.zoneState.content.ops) {
            return opsToMd(block.zoneState.content.ops);
        }
        if (block.zoneState && block.zoneState.allText) {
            return block.zoneState.allText.replace(/\n$/, '');
        }
        return '';
    }

    // 递归展开 synced_source 和 heading 的子 block
    // 同时为 ordered list 注入 _parent 引用以便计算序号
    function flatChildren(children, parent) {
        const result = [];
        for (const child of children) {
            // 注入 _parent 引用
            if (parent) child._parent = parent;
            if (child.type === 'synced_source') {
                result.push(...flatChildren(child.children || [], child));
            } else if (/^heading\d$/.test(child.type) || child.type === 'text') {
                result.push(child);
                if (child.children && child.children.length > 0) {
                    result.push(...flatChildren(child.children, child));
                }
            } else {
                result.push(child);
                // 对于 quote_container / callout / grid 等容器，不在这里展开子节点
                // 但对于其他可能包含子 block 的类型（如 toggle_heading），展开子节点
                if (child.type === 'toggle_heading' && child.children && child.children.length > 0) {
                    result.push(...flatChildren(child.children, child));
                }
            }
        }
        return result;
    }

    // 表格 block → Markdown 表格
    function tableToMd(block) {
        const colCount = block.snapshot?.columns_id?.length || 0;
        if (!colCount || !block.children || !block.children.length) return '';
        // block.children 是所有 cell，按 colCount 分行
        const cells = block.children;
        const rows = [];
        for (let i = 0; i < cells.length; i += colCount) {
            rows.push(cells.slice(i, i + colCount));
        }
        const lines = [];
        for (let ri = 0; ri < rows.length; ri++) {
            const cellTexts = rows[ri].map(cell => {
                // cell 的子 block 可能有多个段落
                const parts = (cell.children || []).map(child => blockText(child));
                return parts.join(' ').replace(/\|/g, '\\|').replace(/\n/g, ' ');
            });
            lines.push('| ' + cellTexts.join(' | ') + ' |');
            if (ri === 0) {
                lines.push('| ' + cellTexts.map(() => '---').join(' | ') + ' |');
            }
        }
        return lines.join('\n');
    }

    // sheet block — 通过 collaSpread._spread.sheets 读取单元格数据
    function sheetToMd(block) {
        // 从 block.snapshot.token 提取 sheetId（下划线后缀）
        let sheetId = '';
        const token = block.snapshot?.token || '';
        if (token.includes('_')) {
            sheetId = token.split('_').pop();
        }
        // 也尝试从 sheetBlocksState 获取
        if (!sheetId && block.record?.id) {
            try {
                const sheetBlocks = root.children.filter(b => b.type === 'sheet');
                const sm = sheetBlocks[0]?.bridge?.bridge;
                if (sm?.sheetBlocksState?.[block.record.id]) {
                    sheetId = sm.sheetBlocksState[block.record.id].sheetId;
                }
            } catch(e) {}
        }

        const sh = _sheetMap[sheetId];
        if (!sh) {
            // fallback: 尝试 DOM
            const blockEl = document.querySelector('[data-block-id="' + block.id + '"]');
            if (blockEl) {
                const table = blockEl.querySelector('table');
                if (table) return domTableToMd(table);
            }
            return '> ⚠️ Sheet block (数据未加载, sheetId=' + sheetId + ')\n';
        }

        const dm = sh._dataModel;
        const rowCount = dm.rowCount || 0;
        const colCount = dm.colCount || 0;
        if (rowCount === 0 || colCount === 0) return '';

        // 读取所有单元格，用 sh.getValue(r, c) 和 sh.getText(r, c)
        const rows = [];
        for (let r = 0; r < rowCount; r++) {
            const cells = [];
            for (let c = 0; c < colCount; c++) {
                let val = '';
                try {
                    val = sh.getValue(r, c);
                    if (val === null || val === undefined) val = '';
                    val = String(val);
                } catch(e) {
                    try { val = sh.getText(r, c) || ''; } catch(e2) { val = ''; }
                }

                // 通过 sh.getStyle(r, c) 获取单元格样式
                // 返回: {_foreColor, _backColor, _font:{fontSize,fontWeight,fontStyle,textDecoration}, _borderXxx, ...}
                // 飞书默认文字色: #1f2329 / rgb(31, 35, 41)
                const DEFAULT_COLORS = ['#1f2329', 'rgb(31, 35, 41)', 'rgb(31,35,41)', '#000000', 'rgb(0, 0, 0)', 'rgb(0,0,0)', 'inherit', ''];
                try {
                    const style = sh.getStyle(r, c);
                    if (style) {
                        const fc = style._foreColor || style.foreColor || '';
                        const bg = style._backColor || style._backgroundColor || style.backColor || '';
                        const font = style._font || style.font || {};
                        const fontObj = typeof font === 'object' ? font : {};
                        const isBold = fontObj.fontWeight >= 700 || (typeof font === 'string' && font.includes('bold'));
                        const isItalic = fontObj.fontStyle === 'italic' || (typeof font === 'string' && font.includes('italic'));
                        const isStrike = fontObj.textDecoration === 'line-through' || (typeof font === 'string' && font.includes('line-through'));

                        if (isStrike && !val.includes('~~')) val = '~~' + val + '~~';
                        if (isBold && !val.includes('**')) val = '**' + val + '**';
                        if (isItalic && !val.includes('*')) val = '*' + val + '*';
                        if (bg && bg !== 'inherit' && bg !== '' && bg !== 'transparent' && !val.includes('<mark')) {
                            val = '<mark style="background:' + bg + '">' + esc(val) + '</mark>';
                        }
                        if (fc && !DEFAULT_COLORS.includes(fc) && !val.includes('<font')) {
                            val = '<font color="' + fc + '">' + esc(val) + '</font>';
                        }
                    }
                } catch(e) {}

                // fallback: contentModel 富文本段 (_segmentArray)
                try {
                    const node = dm.contentModel.get(r, c);
                    if (node && node._segmentArray && node._segmentArray.length > 0) {
                        const segs = node._segmentArray;
                        const parts = [];
                        for (const seg of segs) {
                            let t = seg.text || seg.value || '';
                            const s = seg.style || seg.attr || {};
                            if (s.strikethrough || s.st) t = '~~' + t + '~~';
                            if (s.bold || s.bl) t = '**' + t + '**';
                            if (s.italic || s.it) t = '*' + t + '*';
                            const sfc = s.fontColor || s.fc || s._foreColor || '';
                            if (sfc && !DEFAULT_COLORS.includes(sfc)) {
                                t = '<font color="' + sfc + '">' + esc(t) + '</font>';
                            }
                            const sbc = s.backgroundColor || s.bc || s._backColor || '';
                            if (sbc && sbc !== 'inherit' && sbc !== 'transparent') {
                                t = '<mark style="background:' + sbc + '">' + esc(t) + '</mark>';
                            }
                            parts.push(t);
                        }
                        if (parts.length > 0) val = parts.join('');
                    }
                } catch(e) {}

                val = val.replace(/\|/g, '\\|').replace(/\n/g, ' ');
                cells.push(val);
            }
            rows.push(cells);
        }

        // 生成 Markdown 表格
        if (rows.length === 0) return '';
        const lines = [];
        for (let ri = 0; ri < rows.length; ri++) {
            lines.push('| ' + rows[ri].join(' | ') + ' |');
            if (ri === 0) {
                lines.push('| ' + rows[ri].map(() => '---').join(' | ') + ' |');
            }
        }
        return lines.join('\n');
    }

    // DOM table → Markdown
    function domTableToMd(table) {
        const rows = table.querySelectorAll('tr');
        if (!rows.length) return '';
        const lines = [];
        let maxCols = 0;
        const allRows = [];
        rows.forEach(row => {
            const cells = row.querySelectorAll('td, th');
            const texts = [];
            cells.forEach(cell => {
                let t = cell.innerText.trim().replace(/\|/g, '\\|').replace(/\n/g, ' ');
                // 尝试保留样式
                const style = cell.getAttribute('style') || '';
                if (style.includes('line-through')) t = '~~' + t + '~~';
                const colorMatch = style.match(/(?<![a-z-])color\s*:\s*([^;]+)/);
                if (colorMatch) {
                    const c = colorMatch[1].trim();
                    if (c !== 'inherit' && c !== 'rgb(0, 0, 0)') {
                        t = '<font color="' + c + '">' + t + '</font>';
                    }
                }
                const bgMatch = style.match(/background[-\s]*color\s*:\s*([^;]+)/);
                if (bgMatch) {
                    t = '<mark style="background:' + bgMatch[1].trim() + '">' + t + '</mark>';
                }
                texts.push(t);
            });
            maxCols = Math.max(maxCols, texts.length);
            allRows.push(texts);
        });
        for (const row of allRows) {
            while (row.length < maxCols) row.push('');
        }
        for (let ri = 0; ri < allRows.length; ri++) {
            lines.push('| ' + allRows[ri].join(' | ') + ' |');
            if (ri === 0) {
                lines.push('| ' + allRows[ri].map(() => '---').join(' | ') + ' |');
            }
        }
        return lines.join('\n');
    }

    // 图片 block
    function imageToMd(block) {
        const img = block.snapshot?.image;
        if (!img) return '';
        const alt = '';
        const token = img.token || '';
        const name = img.name || 'image';
        // 尝试获取图片 URL
        let url = '';
        if (block.imageManager && block.imageManager.fetch) {
            // 异步获取，先用 token 占位
            images.push({token: token, name: name, blockId: block.id});
            url = '__IMAGE_TOKEN__' + token;
        }
        return '![' + name + '](' + url + ')';
    }

    // 主转换函数
    function blockToMd(block, depth) {
        depth = depth || 0;
        const type = block.type;
        const text = blockText(block);

        switch(type) {
            case 'page':
                return flatChildren(block.children || [], block).map(b => blockToMd(b, 0)).join('\n\n');

            case 'heading1': return '# ' + text;
            case 'heading2': return '## ' + text;
            case 'heading3': return '### ' + text;
            case 'heading4': return '#### ' + text;
            case 'heading5': return '##### ' + text;
            case 'heading6': return '###### ' + text;
            case 'heading7': case 'heading8': case 'heading9':
                return text;  // 7-9 级标题当普通段落

            case 'text':
                return text;

            case 'divider':
                return '---';

            case 'code': {
                const lang = (block.snapshot?.language || block.language || '').toLowerCase();
                let code = block.zoneState?.allText?.replace(/\n$/, '') || '';
                // fallback: 如果 allText 为空，尝试从 ops 提取纯文本
                if (!code && block.zoneState?.content?.ops) {
                    code = block.zoneState.content.ops
                        .map(op => op.insert || '')
                        .join('')
                        .replace(/\n$/, '');
                }
                // fallback: 尝试从子 block 提取
                if (!code && block.children && block.children.length > 0) {
                    code = block.children.map(child => {
                        return child.zoneState?.allText?.replace(/\n$/, '') ||
                               (child.zoneState?.content?.ops || []).map(op => op.insert || '').join('');
                    }).join('\n').replace(/\n$/, '');
                }
                return '```' + lang + '\n' + code + '\n```';
            }

            case 'quote_container':
            case 'callout': {
                const inner = flatChildren(block.children || [], block)
                    .map(b => blockToMd(b, depth))
                    .join('\n');
                return inner.split('\n').map(l => '> ' + l).join('\n');
            }

            case 'bullet': {
                const prefix = '  '.repeat(depth) + '- ';
                let result = prefix + text;
                if (block.children && block.children.length > 0) {
                    const sub = flatChildren(block.children, block)
                        .map(b => blockToMd(b, depth + 1))
                        .filter(s => s);
                    if (sub.length) result += '\n' + sub.join('\n');
                }
                return result;
            }

            case 'ordered': {
                let seq = block.snapshot?.seq;
                // 如果 seq 是 'auto' 或缺失，计算实际序号
                if (!seq || seq === 'auto' || seq === 'undefined') {
                    seq = 1;
                    // 在父 block 的 children 中找到当前 block 的位置
                    // 连续的 ordered block 构成一个序号组，遇到非 ordered 则重置
                    const parent = block._parent || block.parent;
                    if (parent && parent.children) {
                        let count = 0;
                        for (const sib of parent.children) {
                            if (sib.type === 'ordered') {
                                count++;
                            } else {
                                count = 0; // 非 ordered 打断序号
                            }
                            if (sib === block || sib.id === block.id) { seq = count; break; }
                        }
                    }
                    if (seq < 1) seq = 1;
                }
                const prefix = '  '.repeat(depth) + seq + '. ';
                let result = prefix + text;
                if (block.children && block.children.length > 0) {
                    const sub = flatChildren(block.children, block)
                        .map(b => blockToMd(b, depth + 1))
                        .filter(s => s);
                    if (sub.length) result += '\n' + sub.join('\n');
                }
                return result;
            }

            case 'todo': {
                const done = block.snapshot?.done ? 'x' : ' ';
                return '- [' + done + '] ' + text;
            }

            case 'table':
                return tableToMd(block);

            case 'sheet':
                return sheetToMd(block);

            case 'image':
                return imageToMd(block);

            case 'grid': {
                // grid 是多列布局，展平其内容
                const cols = block.children || [];
                return cols.map(col => {
                    return (col.children || []).map(b => blockToMd(b, depth)).join('\n\n');
                }).join('\n\n');
            }

            case 'iframe': {
                const url = block.snapshot?.iframe?.component?.url;
                if (url) return '[iframe](' + url + ')';
                return '';
            }

            case 'isv': {
                // ISV block (text drawing = mermaid, etc.)
                if (block.snapshot?.data?.data) {
                    return '```mermaid\n' + block.snapshot.data.data + '\n```';
                }
                return '';
            }

            default:
                // 未知类型，尝试提取文本
                if (text) return text;
                return '';
        }
    }

    const markdown = blockToMd(root, 0);

    return JSON.stringify({
        success: true,
        markdown: markdown,
        images: images,
        title: root.zoneState?.allText?.replace(/\n$/, '') || '',
        blockCount: root.children?.length || 0,
    });
})()
"""


# ============================================================
# 登录辅助
# ============================================================

_login_server = None
_login_server_thread = None
_login_status_flag = "waiting"  # waiting / logged_in / timeout
_login_ws_ref = None  # websocket 引用，供提醒页面实时截图
_login_ws_lock = threading.Lock()  # CDP websocket 不是线程安全的


def _make_login_html(screenshot_b64=None):
    """生成登录提醒页面 HTML，包含截图和自动刷新"""
    img_tag = '<p style="color:#aaa">（截图加载失败，请直接切到 Chrome 窗口扫码）</p>'
    if screenshot_b64:
        img_tag = f'<img src="data:image/png;base64,{screenshot_b64}" style="max-width:360px;border-radius:8px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,.15)">'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>飞书登录</title>
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
<h2>🔐 飞书登录</h2>
<p>请在飞书登录页面扫码或输入账号密码</p>
{img_tag}
<p class="status"><span class="dot"></span>等待登录中... 每 3 秒自动刷新截图</p>
<p style="color:#bbb;font-size:12px">登录成功后此页面会自动关闭</p>
</div>
<script>setTimeout(()=>location.reload(), 3000);</script>
</body></html>"""


def _make_login_success_html():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>登录成功</title>
<style>
body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4}
.card{background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.1);
text-align:center;max-width:400px}
</style></head><body><div class="card">
<h2>✅ 登录成功</h2>
<p style="color:#16a34a">Session 已保存，此页面将自动关闭</p>
</div>
<script>setTimeout(()=>window.close(), 2000);</script>
</body></html>"""


def _live_screenshot():
    """实时截图飞书登录页，返回 base64（线程安全）"""
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
    """启动登录提醒页面的本地 HTTP 服务，每次刷新实时截图"""
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
                # 每次请求时实时截图
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


def check_login(ws):
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
    global _login_status_flag, _login_ws_ref
    print("[Login/登录] Checking login status / 检查登录状态...")
    status = check_login(ws)
    if status == 'logged_in':
        print("[Login/登录] ✅ Already logged in / 已登录")
        save_cookies(ws)
        return True

    print("[Login/登录] Feishu login required / 需要登录飞书...")

    # 保存 ws 引用，供提醒页面实时截图
    _login_ws_ref = ws

    # 先启动 helper HTTP server（毫秒级，不阻塞）
    helper_port = _start_login_helper()

    # 检查当前页面是否已经在飞书登录页
    current_url = js(ws, "location.href") or ""
    already_on_login = "passport.feishu.cn" in current_url or "accounts/page/login" in current_url

    if not already_on_login:
        js(ws, f'window.location.href = "https://passport.feishu.cn/accounts/page/login?redirect_uri={feishu_url}";')
        # 立即打开提醒页面，不等登录页完全加载
        helper_ws = None
        try:
            helper_ws = open_tab(f"http://127.0.0.1:{helper_port}")
        except Exception:
            pass
        # 等登录页加载（缩短到 3 秒，提醒页已经打开了）
        time.sleep(3)
    else:
        # 已经在登录页，直接打开提醒页
        helper_ws = None
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

    # 轮询等待登录完成
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        elapsed = int(time.time() - start)
        try:
            with _login_ws_lock:
                current_url = js(ws, "location.href") or ""
            if any(x in current_url for x in ["feishu.cn/docx/", "feishu.cn/wiki/", "feishu.cn/hc/",
                                                "feishu.cn/sheets/", "feishu.cn/base/"]):
                print("[Login/登录] ✅ Login successful / 登录成功！")
                _login_status_flag = "logged_in"
                with _login_ws_lock:
                    save_cookies(ws)
                time.sleep(2)
                if helper_ws:
                    close_tab_by_ws(helper_ws)
                _stop_login_helper()
                return True
            with _login_ws_lock:
                login_st = check_login(ws)
            if login_st == 'logged_in':
                print("[Login/登录] ✅ Login successful / 登录成功！")
                _login_status_flag = "logged_in"
                with _login_ws_lock:
                    save_cookies(ws)
                time.sleep(2)
                if helper_ws:
                    close_tab_by_ws(helper_ws)
                _stop_login_helper()
                return True
        except Exception:
            pass

        if elapsed > 0 and elapsed % 30 == 0:
            remaining = timeout - elapsed
            print(f"[Login/登录] ⏳ Waited {elapsed}s, {remaining}s remaining / 已等待 {elapsed}s，剩余 {remaining}s...")

    print("[Login/登录] ⏰ Login timeout (5 min), please retry / 登录超时（5 分钟），请重新运行")
    _login_status_flag = "timeout"
    if helper_ws:
        close_tab_by_ws(helper_ws)
    _stop_login_helper()
    return False

def dismiss_popups(ws):
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
    print("[等待] 文档加载中...")
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
            print(f"[等待] ✅ 文档就绪 (类型: {ready})")
            return ready
        time.sleep(1)
        dismiss_popups(ws)
    print("[等待] ⏰ 文档加载超时")
    return None


# ============================================================
# 滚动加载 sheet blocks (仅对 sheet 类型需要)
# ============================================================
def scroll_to_load_sheets(ws, timeout=60):
    """
    sheet block 用 canvas 渲染，需要滚动到可视区域才会加载。
    快速滚动一遍页面，让所有 sheet 渲染出来。
    """
    has_sheets = js(ws, """
    (() => {
        const root = window.PageMain?.blockManager?.rootBlockModel;
        if (!root) return false;
        return root.children.some(b => b.type === 'sheet');
    })()
    """)
    if not has_sheets:
        return

    print("[滚动] 检测到 sheet blocks，滚动加载...")
    # 激活滚动容器
    js(ws, """
    (() => {
        const c = document.querySelector('#docx > div') || document.querySelector('.bear-web-x-container');
        if (!c) return;
        c.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:300, clientY:300}));
        c.scrollTop = 1; c.scrollTop = 0;
    })()
    """)
    time.sleep(0.3)

    # 快速滚到底再回来
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
                // 回扫
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
    print("[滚动] sheet 加载完成")
    time.sleep(1)


# ============================================================
# 核心提取: PageMain → Markdown
# ============================================================
def extract_via_pagemain(ws):
    """
    通过 window.PageMain 提取文档，返回 (markdown, title, images_info)。
    """
    print("[提取] 通过 PageMain 数据模型提取...")

    # 先检查 PageMain 是否就绪（所有 block 加载完成）
    ready = js(ws, """
    (() => {
        const root = window.PageMain?.blockManager?.rootBlockModel;
        if (!root) return false;
        return root.children.every(b => b.snapshot && b.snapshot.type !== 'pending');
    })()
    """)
    if not ready:
        print("[提取] 等待 block 加载完成...")
        time.sleep(3)

    # 滚动加载 sheet blocks
    scroll_to_load_sheets(ws)

    # 执行提取脚本
    result_str = js(ws, PAGEMAIN_EXTRACT_JS)
    if not result_str:
        print("[提取] ❌ 脚本返回空")
        return None, None, None

    try:
        result = json.loads(result_str)
    except json.JSONDecodeError as e:
        print(f"[提取] ❌ JSON 解析失败: {e}")
        return None, None, None

    if result.get("error"):
        print(f"[提取] ❌ {result['error']}")
        return None, None, None

    md = result.get("markdown", "")
    title = result.get("title", "")
    images = result.get("images", [])
    block_count = result.get("blockCount", 0)

    # 统计质量指标
    table_pipes = md.count("|")
    checkmarks = md.count("✅")
    strikethroughs = md.count("~~")
    font_tags = md.count("<font")
    mark_tags = md.count("<mark")

    print(f"[提取] ✅ PageMain 提取成功: {len(md)} chars, {block_count} blocks")
    print(f"[提取]   表格管道符: {table_pipes}, ✅: {checkmarks}, "
          f"删除线: {strikethroughs}, 颜色: {font_tags}, 背景: {mark_tags}")

    return md, title, images


# ============================================================
# 图片处理: 通过 imageManager.fetch 获取图片 URL 并下载
# ============================================================
def resolve_and_download_images(ws, md_text, imgs_dir):
    """
    解析 __IMAGE_TOKEN__ 占位符，通过飞书 imageManager 获取真实 URL 并下载。
    """
    tokens = re.findall(r'__IMAGE_TOKEN__(\w+)', md_text)
    if not tokens:
        return md_text, 0

    os.makedirs(imgs_dir, exist_ok=True)
    imgs_folder = os.path.basename(imgs_dir)
    count = 0

    for token in tokens:
        try:
            # 通过 imageManager 获取图片 URL
            url = js(ws, f"""
            (async () => {{
                const PM = window.PageMain;
                if (!PM) return null;
                const root = PM.blockManager.rootBlockModel;
                // 找到对应的 image block
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

            # 下载图片
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
                print(f"[图片] ✅ {fname}")
        except Exception as e:
            print(f"[图片] 下载失败 ({token}): {e}")

    if count:
        print(f"[图片] 共下载 {count}/{len(tokens)} 张")
    return md_text, count


# ============================================================
# 帮助中心提取 (非 docx 页面)
# ============================================================
def extract_hc_page(ws):
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
# 主入口
# ============================================================
def extract_via_cdp(feishu_url, output_path=None, wait=10):
    """
    通过 CDP + PageMain 提取飞书文档。
    返回 {"success": bool, "md_path": str, "title": str, ...}
    """
    import websocket

    # 1. 确保 Chrome 运行
    if not is_cdp_alive():
        if not launch_chrome():
            return {"success": False, "error": "Chrome 启动失败"}

    # 2. 打开或复用标签页
    ws_url = find_tab(feishu_url)
    if ws_url:
        print("[CDP] 复用已有标签页")
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

    # 3. 等待页面加载
    time.sleep(max(wait, 5))
    dismiss_popups(ws)

    # 4. 检查登录
    login_status = check_login(ws)
    if login_status != 'logged_in':
        print("[CDP] 需要登录...")
        if not wait_for_login(ws, feishu_url):
            ws.close()
            return {"success": False, "error": "登录失败或超时"}
        js(ws, f'window.location.href = "{feishu_url}";')
        time.sleep(max(wait, 5))
        dismiss_popups(ws)

    # 5. 等待文档就绪
    doc_type = wait_for_doc_ready(ws)
    if not doc_type:
        ws.close()
        return {"success": False, "error": "文档加载超时"}

    save_cookies(ws)

    # 6. 提取
    md_text = None
    img_count = 0

    if doc_type in ('pagemain', 'docx'):
        md_text, title_from_pm, images_info = extract_via_pagemain(ws)
    elif doc_type == 'hc':
        hc_result = extract_hc_page(ws)
        if hc_result:
            md_text = f"# {hc_result['title']}\n\n{hc_result['content']}"

    if not md_text or len(md_text.strip()) < 10:
        ws.close()
        return {"success": False, "error": "提取内容为空"}

    # 7. 获取标题
    title = get_doc_title(ws)
    safe_title = safe_filename(title)

    # 8. 输出路径
    if not output_path:
        output_path = os.path.join(get_output_dir(), f"{safe_title}.md")
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # 9. 下载图片
    imgs_dir = os.path.join(
        os.path.dirname(output_path),
        os.path.splitext(os.path.basename(output_path))[0] + "_imgs"
    )
    md_text, img_count = resolve_and_download_images(ws, md_text, imgs_dir)

    ws.close()

    # 10. 清理 & 保存
    md_text = cleanup_markdown(md_text, title)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"[CDP] ✅ 输出: {output_path}")
    return {
        "success": True,
        "md_path": os.path.abspath(output_path),
        "title": title,
        "method": "cdp_pagemain",
        "image_count": img_count,
    }


def cleanup_markdown(md_text, title=""):
    md_text = re.sub(r'\n{4,}', '\n\n\n', md_text)
    md_text = re.sub(r' +\n', '\n', md_text)
    if title and not md_text.strip().startswith('#'):
        md_text = f"# {title}\n\n{md_text}"
    return md_text.strip() + "\n"


def login_only():
    import websocket
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
        except: pass
    ws.close()
    return False
