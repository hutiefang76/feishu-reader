"""
Feishu Reader — Compatibility shim / 兼容层
Imports from core/ modules for backward compatibility.
所有功能已迁移到 core/ 模块，此文件仅做导入转发。
"""
# Re-export everything that feishu_cdp.py and feishu_skill.py import from here
from core.config import (
    CACHE_DIR, COOKIE_FILE, CHROME_PROFILE, CDP_PORT,
    get_cache_dir, get_output_dir, safe_filename,
    parse_doc_type,
)
from core.chrome import find_chrome, is_cdp_alive, launch_chrome
from core.cdp import cdp, js, get_tabs, find_tab, get_any_tab, open_tab, close_tab_by_ws
from core.session import save_cookies, load_cookies


def parse_doc_token(url):
    """Extract document token from Feishu URL."""
    import re
    m = re.search(r'/(docx|doc|wiki|sheets|base|mindnotes|bitable)/([A-Za-z0-9]+)', url)
    if m:
        return m.group(2), m.group(1)
    return None, None
