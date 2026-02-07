"""
飞书文档提取 Skill — 标准化接口

接口:
  1. extract(url)           → 提取单个飞书文档为 Markdown
  2. batch_extract(urls)    → 批量提取多个文档
  3. read_doc(path)         → 读取已提取的 Markdown 文件
  4. list_docs(dir?)        → 列出已提取的文档
  5. search_docs(keyword)   → 搜索文档内容
  6. status()               → 环境状态检查
  7. ensure_ready()         → 确保环境就绪（安装依赖、启动Chrome、登录）

可作为: Python 模块 / CLI / HTTP API / MCP Server
"""
import json
import os
import sys
import glob
import re
import argparse
import subprocess
import platform
import shutil


def _project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _output_dir():
    out = os.path.join(_project_dir(), "output")
    os.makedirs(out, exist_ok=True)
    return out


def _venv_python():
    """获取虚拟环境的 python 路径"""
    venv = os.path.join(_project_dir(), ".venv")
    if platform.system() == "Windows":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python3")


# ============================================================
# 环境自检与自动修复
# ============================================================

def _check_dependencies():
    """检查 Python 依赖是否已安装"""
    missing = []
    try:
        import websocket  # noqa: F401
    except ImportError:
        missing.append("websocket-client")
    return missing


def _install_dependencies(packages):
    """安装缺失的依赖，支持镜像降级"""
    mirrors = [
        None,  # 官方源
        ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
        ("https://mirrors.aliyun.com/pypi/simple", "mirrors.aliyun.com"),
    ]
    python = sys.executable
    for pkg in packages:
        installed = False
        for mirror in mirrors:
            try:
                cmd = [python, "-m", "pip", "install", pkg, "-q", "--timeout", "15"]
                if mirror:
                    cmd.extend(["-i", mirror[0], "--trusted-host", mirror[1]])
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
                installed = True
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        if not installed:
            return False, f"安装 {pkg} 失败（所有源均不可用）"
    return True, "依赖安装成功"


def _check_chrome():
    """检查 Chrome 是否可用"""
    from feishu_common import find_chrome, is_cdp_alive
    chrome = find_chrome()
    if not chrome:
        return {"found": False, "running": False, "path": None}
    return {
        "found": True,
        "running": is_cdp_alive(),
        "path": chrome,
    }


def _ensure_chrome_running():
    """确保 Chrome CDP 正在运行"""
    from feishu_common import is_cdp_alive, launch_chrome
    if is_cdp_alive():
        return True, "Chrome CDP 已在运行"
    if launch_chrome():
        return True, "Chrome 已启动"
    return False, "Chrome 启动失败，请手动启动或运行 setup.sh"


def ensure_ready():
    """
    确保环境完全就绪：依赖 → Chrome → Session。
    返回 {"ready": bool, "steps": [...], "error": str?}
    """
    steps = []

    # 1. 检查依赖
    missing = _check_dependencies()
    if missing:
        steps.append(f"安装缺失依赖: {', '.join(missing)}")
        ok, msg = _install_dependencies(missing)
        if not ok:
            return {"ready": False, "steps": steps, "error": msg}
        steps.append("✅ 依赖安装完成")
    else:
        steps.append("✅ 依赖已就绪")

    # 2. 检查 Chrome
    chrome_info = _check_chrome()
    if not chrome_info["found"]:
        steps.append("❌ 未找到 Chrome，请安装 Google Chrome")
        return {"ready": False, "steps": steps, "error": "Chrome 未安装"}

    if not chrome_info["running"]:
        steps.append("启动 Chrome CDP...")
        ok, msg = _ensure_chrome_running()
        if not ok:
            return {"ready": False, "steps": steps, "error": msg}
        steps.append("✅ Chrome CDP 已启动")
    else:
        steps.append("✅ Chrome CDP 已在运行")

    # 3. 检查 Session
    from feishu_common import COOKIE_FILE
    has_session = os.path.exists(COOKIE_FILE)
    if has_session:
        steps.append("✅ 已有登录 Session 缓存")
    else:
        steps.append("⚠️ 无登录 Session，首次提取时会引导登录")

    return {"ready": True, "steps": steps}


# ============================================================
# Skill 接口
# ============================================================

def extract(url, output=None, wait=10):
    """
    提取单个飞书文档为 Markdown。

    参数:
      url: 飞书文档 URL (feishu.cn/docx/xxx 或 feishu.cn/wiki/xxx)
      output: 输出文件路径（可选，默认 output/<标题>.md）
      wait: 页面加载等待秒数

    返回:
      {
        "success": bool,
        "title": "文档标题",
        "md_path": "输出文件绝对路径",
        "char_count": 12345,
        "image_count": 3,
        "method": "cdp_pagemain",
        "error": "错误信息（失败时）"
      }
    """
    if not url or not isinstance(url, str):
        return {"success": False, "error": "请提供有效的飞书文档 URL"}

    # URL 格式校验
    if not re.search(r'feishu\.cn/(docx|wiki|doc|sheets|hc)/', url):
        return {"success": False, "error": f"不是有效的飞书文档 URL: {url}"}

    # 确保环境就绪
    ready = ensure_ready()
    if not ready["ready"]:
        return {"success": False, "error": ready.get("error", "环境未就绪")}

    try:
        from feishu_cdp import extract_via_cdp
        result = extract_via_cdp(url, output, wait)

        # 补充字符数统计
        if result.get("success") and result.get("md_path"):
            md_path = result["md_path"]
            if os.path.exists(md_path):
                with open(md_path, "r", encoding="utf-8") as f:
                    content = f.read()
                result["char_count"] = len(content)
                result["table_pipes"] = content.count("|")
                result["has_tables"] = content.count("|") > 10

        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def batch_extract(urls, wait=12):
    """
    批量提取多个飞书文档。

    参数:
      urls: 飞书文档 URL 列表
      wait: 每个文档的页面加载等待秒数

    返回:
      {
        "success": bool,
        "total": 5,
        "succeeded": 4,
        "failed": 1,
        "results": [
          {"url": "...", "success": true, "title": "...", "md_path": "..."},
          {"url": "...", "success": false, "error": "..."},
        ]
      }
    """
    if not urls or not isinstance(urls, list):
        return {"success": False, "error": "请提供 URL 列表"}

    # 确保环境就绪（只检查一次）
    ready = ensure_ready()
    if not ready["ready"]:
        return {"success": False, "error": ready.get("error", "环境未就绪")}

    results = []
    for url in urls:
        try:
            r = extract(url, wait=wait)
            r["url"] = url
            results.append(r)
        except Exception as e:
            results.append({"url": url, "success": False, "error": str(e)})

    succeeded = sum(1 for r in results if r.get("success"))
    return {
        "success": succeeded > 0,
        "total": len(urls),
        "succeeded": succeeded,
        "failed": len(urls) - succeeded,
        "results": results,
    }


def read_doc(path):
    """
    读取已提取的 Markdown 文件。

    参数:
      path: Markdown 文件路径（绝对路径或相对于 output/ 的路径）

    返回:
      {
        "success": bool,
        "content": "Markdown 全文",
        "title": "文档标题",
        "char_count": 12345,
        "sections": ["# 标题", "## 章节1", ...],
        "has_images": bool,
        "error": "错误信息（失败时）"
      }
    """
    if not path:
        return {"success": False, "error": "请提供文件路径"}

    # 支持相对路径（相对于 output/）
    if not os.path.isabs(path) and not os.path.exists(path):
        alt = os.path.join(_output_dir(), path)
        if os.path.exists(alt):
            path = alt

    if not os.path.exists(path):
        return {"success": False, "error": f"文件不存在: {path}"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        sections = re.findall(r'^(#{1,6}\s+.+)', content, re.MULTILINE)
        title_match = re.match(r'^#\s+(.+)', content)
        imgs_dir = os.path.splitext(path)[0] + "_imgs"
        return {
            "success": True,
            "content": content,
            "title": title_match.group(1) if title_match else os.path.basename(path),
            "char_count": len(content),
            "sections": sections,
            "has_images": os.path.isdir(imgs_dir),
        }
    except UnicodeDecodeError:
        return {"success": False, "error": f"文件编码错误（非 UTF-8）: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_docs(directory=None):
    """
    列出已提取的飞书文档。

    参数:
      directory: 搜索目录（默认 output/）

    返回:
      {
        "success": bool,
        "docs": [
          {"path": "绝对路径", "title": "标题", "size_kb": 12.3, "has_images": bool},
        ]
      }
    """
    if directory is None:
        directory = _output_dir()

    if not os.path.isdir(directory):
        return {"success": True, "docs": []}

    try:
        docs = []
        for md_path in sorted(glob.glob(os.path.join(directory, "**", "*.md"), recursive=True)):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                title = first_line.lstrip("#").strip() if first_line.startswith("#") else os.path.basename(md_path)
            except (UnicodeDecodeError, IOError):
                title = os.path.basename(md_path)
            imgs_dir = os.path.splitext(md_path)[0] + "_imgs"
            docs.append({
                "path": os.path.abspath(md_path),
                "title": title,
                "size_kb": round(os.path.getsize(md_path) / 1024, 1),
                "has_images": os.path.isdir(imgs_dir),
            })
        return {"success": True, "docs": docs}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_docs(keyword, directory=None):
    """
    在已提取文档中搜索关键词。

    参数:
      keyword: 搜索关键词
      directory: 搜索目录（默认 output/）

    返回:
      {
        "success": bool,
        "keyword": "搜索词",
        "results": [
          {"path": "...", "title": "...", "matches": [{"line": 5, "text": "..."}]}
        ]
      }
    """
    if not keyword:
        return {"success": False, "error": "请提供搜索关键词"}

    if directory is None:
        directory = _output_dir()

    if not os.path.isdir(directory):
        return {"success": True, "keyword": keyword, "results": []}

    try:
        results = []
        for md_path in glob.glob(os.path.join(directory, "**", "*.md"), recursive=True):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except (UnicodeDecodeError, IOError):
                continue

            matches = []
            title = ""
            for i, line in enumerate(lines, 1):
                if i == 1 and line.startswith("#"):
                    title = line.lstrip("#").strip()
                if keyword.lower() in line.lower():
                    matches.append({"line": i, "text": line.strip()[:200]})

            if matches:
                results.append({
                    "path": os.path.abspath(md_path),
                    "title": title or os.path.basename(md_path),
                    "match_count": len(matches),
                    "matches": matches[:20],  # 最多返回20条
                })
        return {"success": True, "keyword": keyword, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


def status():
    """
    检查环境状态。

    返回:
      {
        "chrome_found": bool,
        "chrome_running": bool,
        "session_cached": bool,
        "dependencies_ok": bool,
        "missing_deps": [],
        "python_version": "3.11.5",
        "platform": "Darwin",
        "output_dir": "/path/to/output",
        "doc_count": 5
      }
    """
    missing = _check_dependencies()

    result = {
        "dependencies_ok": len(missing) == 0,
        "missing_deps": missing,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system(),
        "output_dir": _output_dir(),
    }

    # Chrome 检查（需要依赖已安装）
    if not missing:
        try:
            chrome_info = _check_chrome()
            result["chrome_found"] = chrome_info["found"]
            result["chrome_running"] = chrome_info["running"]
            result["chrome_path"] = chrome_info.get("path")
        except Exception:
            result["chrome_found"] = False
            result["chrome_running"] = False

        try:
            from feishu_common import COOKIE_FILE
            result["session_cached"] = os.path.exists(COOKIE_FILE)
        except Exception:
            result["session_cached"] = False
    else:
        result["chrome_found"] = False
        result["chrome_running"] = False
        result["session_cached"] = False

    # 文档统计
    out_dir = _output_dir()
    if os.path.isdir(out_dir):
        result["doc_count"] = len(glob.glob(os.path.join(out_dir, "*.md")))
    else:
        result["doc_count"] = 0

    return result


# ============================================================
# MCP Server (Model Context Protocol)
# ============================================================

def _run_mcp_server():
    """
    启动 MCP Server（stdio 模式）。
    遵循 MCP 协议，通过 stdin/stdout 与 AI Agent 通信。
    """
    import io
    # 使用原始 stdin/stdout buffer，避免与 feishu_common.py 的 TextIOWrapper 冲突
    raw_in = sys.__stdin__.buffer if hasattr(sys.__stdin__, 'buffer') else sys.stdin.buffer
    raw_out = sys.__stdout__.buffer if hasattr(sys.__stdout__, 'buffer') else sys.stdout.buffer
    mcp_stdin = io.TextIOWrapper(raw_in, encoding='utf-8', errors='replace')
    mcp_stdout = io.TextIOWrapper(raw_out, encoding='utf-8', errors='replace', line_buffering=True)

    TOOLS = {
        "feishu_extract": {
            "description": "提取飞书云文档为 Markdown。输入飞书文档 URL，返回提取结果和文件路径。支持 docx、wiki、sheet 等类型。自动处理登录、Cookie 持久化。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "飞书文档 URL，如 https://xxx.feishu.cn/docx/xxx"},
                    "wait": {"type": "integer", "description": "页面加载等待秒数（默认10）", "default": 10},
                },
                "required": ["url"],
            },
        },
        "feishu_batch_extract": {
            "description": "批量提取多个飞书文档。输入 URL 列表，逐个提取并返回汇总结果。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}, "description": "飞书文档 URL 列表"},
                    "wait": {"type": "integer", "description": "每个文档的等待秒数（默认12）", "default": 12},
                },
                "required": ["urls"],
            },
        },
        "feishu_read_doc": {
            "description": "读取已提取的飞书文档 Markdown 内容。可用文件名或完整路径。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Markdown 文件路径（文件名或绝对路径）"},
                },
                "required": ["path"],
            },
        },
        "feishu_list_docs": {
            "description": "列出所有已提取的飞书文档，返回标题、路径、大小等信息。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "搜索目录（默认 output/）"},
                },
            },
        },
        "feishu_search_docs": {
            "description": "在已提取的飞书文档中搜索关键词，返回匹配的文档和行。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "directory": {"type": "string", "description": "搜索目录（默认 output/）"},
                },
                "required": ["keyword"],
            },
        },
        "feishu_status": {
            "description": "检查飞书提取工具的环境状态：Chrome、依赖、登录Session等。",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    }

    def handle_request(req):
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "feishu-extractor",
                        "version": "1.0.0",
                    },
                },
            }

        elif method == "notifications/initialized":
            return None  # 通知，不需要响应

        elif method == "tools/list":
            tools_list = []
            for name, info in TOOLS.items():
                tools_list.append({
                    "name": name,
                    "description": info["description"],
                    "inputSchema": info["inputSchema"],
                })
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": tools_list},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = _call_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                        "isError": not result.get("success", True),
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}],
                        "isError": True,
                    },
                }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        else:
            # 未知方法
            if req_id is not None:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return None

    def _call_tool(name, args):
        if name == "feishu_extract":
            return extract(args.get("url", ""), wait=args.get("wait", 10))
        elif name == "feishu_batch_extract":
            return batch_extract(args.get("urls", []), wait=args.get("wait", 12))
        elif name == "feishu_read_doc":
            return read_doc(args.get("path", ""))
        elif name == "feishu_list_docs":
            return list_docs(args.get("directory"))
        elif name == "feishu_search_docs":
            return search_docs(args.get("keyword", ""), args.get("directory"))
        elif name == "feishu_status":
            return status()
        else:
            return {"success": False, "error": f"未知工具: {name}"}

    # MCP stdio 主循环
    _log_to_stderr("[MCP] 飞书文档提取 MCP Server 启动 (stdio)")
    while True:
        try:
            line = mcp_stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                mcp_stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                mcp_stdout.flush()
        except json.JSONDecodeError as e:
            _log_to_stderr(f"[MCP] JSON 解析错误: {e}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            _log_to_stderr(f"[MCP] 错误: {e}")


def _log_to_stderr(msg):
    """MCP 模式下日志输出到 stderr（stdout 留给协议通信）"""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


# ============================================================
# HTTP API 服务
# ============================================================

def _run_http_server(port=8900):
    """启动 HTTP API 服务"""
    import http.server
    import urllib.parse

    class SkillHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            params = dict(urllib.parse.parse_qsl(parsed.query))

            if path == "/status":
                self._ok(status())
            elif path == "/list":
                self._ok(list_docs(params.get("dir")))
            elif path == "/read":
                p = params.get("path", "")
                self._ok(read_doc(p) if p else {"success": False, "error": "缺少 path 参数"})
            elif path == "/search":
                kw = params.get("keyword", "")
                self._ok(search_docs(kw, params.get("dir")) if kw else {"success": False, "error": "缺少 keyword 参数"})
            else:
                self._ok({
                    "service": "feishu-extractor",
                    "version": "1.0.0",
                    "endpoints": [
                        "GET  /status",
                        "GET  /list?dir=.",
                        "GET  /read?path=x.md",
                        "GET  /search?keyword=x",
                        "POST /extract  {url, wait?}",
                        "POST /batch    {urls, wait?}",
                    ],
                })

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}

            if parsed.path == "/extract":
                url = body.get("url", "")
                if not url:
                    self._ok({"success": False, "error": "缺少 url 参数"})
                else:
                    self._ok(extract(url, body.get("output"), body.get("wait", 10)))
            elif parsed.path == "/batch":
                urls = body.get("urls", [])
                if not urls:
                    self._ok({"success": False, "error": "缺少 urls 参数"})
                else:
                    self._ok(batch_extract(urls, body.get("wait", 12)))
            else:
                self._ok({"error": f"未知接口: {parsed.path}"})

        def do_OPTIONS(self):
            self.send_response(200)
            self._cors_headers()
            self.end_headers()

        def _ok(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

        def _cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def log_message(self, fmt, *args):
            sys.stderr.write(f"[HTTP] {args[0] if args else ''}\n")

    server = http.server.HTTPServer(("0.0.0.0", port), SkillHandler)
    print(f"[HTTP] 飞书文档提取 API: http://0.0.0.0:{port}")
    print(f"[HTTP] 接口文档: http://localhost:{port}/")
    server.serve_forever()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="飞书文档提取工具 — Skill / MCP / HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 提取单个文档
  python feishu_skill.py extract https://xxx.feishu.cn/docx/xxx

  # 批量提取
  python feishu_skill.py batch url1 url2 url3

  # 查看已提取文档
  python feishu_skill.py list
  python feishu_skill.py search "关键词"
  python feishu_skill.py read output/文档.md

  # 环境检查
  python feishu_skill.py status

  # 启动 MCP Server（供 AI Agent 调用）
  python feishu_skill.py mcp

  # 启动 HTTP API
  python feishu_skill.py serve --port 8900
        """,
    )
    sub = parser.add_subparsers(dest="action")

    # extract
    p = sub.add_parser("extract", help="提取飞书文档")
    p.add_argument("url", help="飞书文档 URL")
    p.add_argument("--output", "-o", help="输出文件路径")
    p.add_argument("--wait", type=int, default=10, help="页面加载等待秒数")

    # batch
    p = sub.add_parser("batch", help="批量提取")
    p.add_argument("urls", nargs="+", help="飞书文档 URL 列表")
    p.add_argument("--wait", type=int, default=12, help="每个文档等待秒数")

    # read
    p = sub.add_parser("read", help="读取 Markdown 文件")
    p.add_argument("path", help="文件路径")

    # list
    p = sub.add_parser("list", help="列出已提取文档")
    p.add_argument("--dir", help="搜索目录")

    # search
    p = sub.add_parser("search", help="搜索文档内容")
    p.add_argument("keyword", help="搜索关键词")
    p.add_argument("--dir", help="搜索目录")

    # status
    sub.add_parser("status", help="环境状态检查")

    # mcp
    sub.add_parser("mcp", help="启动 MCP Server (stdio)")

    # serve
    p = sub.add_parser("serve", help="启动 HTTP API 服务")
    p.add_argument("--port", type=int, default=8900, help="端口号")

    args = parser.parse_args()

    if args.action == "extract":
        result = extract(args.url, args.output, args.wait)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "batch":
        result = batch_extract(args.urls, args.wait)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "read":
        r = read_doc(args.path)
        if r["success"]:
            print(r["content"])
        else:
            print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.action == "list":
        print(json.dumps(list_docs(args.dir), ensure_ascii=False, indent=2))
    elif args.action == "search":
        print(json.dumps(search_docs(args.keyword, args.dir), ensure_ascii=False, indent=2))
    elif args.action == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.action == "mcp":
        _run_mcp_server()
    elif args.action == "serve":
        _run_http_server(args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
