# Feishu Reader — 飞书文档提取工具

Extract Feishu (Lark) cloud documents to high-quality Markdown.
将飞书云文档转换为高质量 Markdown，保留表格、颜色、删除线、代码块、图片等完整信息。

Output is optimized for AI consumption — text tables over screenshots.
输出面向 AI 消费优化 — 文本表格优于截图。

## How It Works / 工作原理

Uses Chrome DevTools Protocol (CDP) to access Feishu's internal data model `window.PageMain.blockManager.rootBlockModel`. Extracts directly from the block tree — no API keys, no app credentials needed.

通过 CDP 访问飞书页面内部数据模型，直接从 block 树提取文档内容。

Supported content / 支持的内容:
- Text, headings (1-9), dividers, quotes, callouts
- Ordered/unordered lists (auto-numbered), todo items, nested lists
- Native tables + Sheet spreadsheet embeds (with cell styles)
- Code blocks (with language), inline code, math formulas
- Bold, italic, strikethrough, font color, background color, links
- Image download, multi-column layout, iframe, mermaid diagrams

## Quick Start / 快速开始

### 1. Setup / 环境安装

```bash
# macOS / Linux
git clone https://github.com/hutiefang76/feishu-reader.git ~/feishu-reader
cd ~/feishu-reader && bash setup.sh

# GitHub 不通时使用 CDN 兜底 / China fallback if GitHub is blocked
curl -fSL http://dl.hutiefang.com/feishu-reader-latest.tar.gz | tar xz
cd feishu-reader && bash setup.sh

# Windows
setup.bat
```

Auto-detects and installs: Python 3.8+ → virtual environment → `websocket-client` → Chrome.
Prompts before installing anything. Supports China mirror fallback (Tsinghua, Aliyun, CDN).

自动检测安装：Python → 虚拟环境 → 依赖 → Chrome。安装前会询问确认，支持国内镜像降级（清华、阿里云、CDN 兜底）。

### 2. Login / 登录飞书

```bash
.venv/bin/python3 extract_feishu.py login
```

Scan QR code or enter credentials in the browser. Session auto-saves to local cache.
在浏览器中扫码或输入账号密码，Session 自动保存。

### 3. Extract / 提取文档

```bash
# Single document / 单个文档
.venv/bin/python3 feishu_skill.py extract "https://xxx.feishu.cn/docx/xxx"

# Batch extract / 批量提取
.venv/bin/python3 feishu_skill.py batch "url1" "url2" "url3"

# Specify output / 指定输出路径
.venv/bin/python3 feishu_skill.py extract "https://xxx.feishu.cn/docx/xxx" -o my_doc.md
```

Output saved to `output/` directory by default.

### 4. Browse / 查阅文档

```bash
.venv/bin/python3 feishu_skill.py list              # List extracted docs / 列出文档
.venv/bin/python3 feishu_skill.py search "keyword"   # Search content / 搜索内容
.venv/bin/python3 feishu_skill.py read "file.md"     # Read document / 读取文档
.venv/bin/python3 feishu_skill.py status             # Check environment / 环境检查
```

## AI Integration / AI 集成

### Claude Code

```bash
# 1. Clone & setup / 克隆并安装
git clone https://github.com/hutiefang76/feishu-reader.git ~/feishu-reader
cd ~/feishu-reader && bash setup.sh

# 2. Install skill globally / 全局安装 Skill
mkdir -p ~/.claude/skills/feishu-extract
cp ~/feishu-reader/.claude/skills/feishu-extract/SKILL.md ~/.claude/skills/feishu-extract/
```

After installation, the skill is available in **any project directory**. Ask Claude to extract a Feishu document or use `/feishu-extract <url>`.

安装后在任意项目目录下均可使用，直接让 Claude 提取飞书文档或使用 `/feishu-extract <url>`。

### Kiro

Kiro Skill at `.kiro/skills/feishu-extract.md`. Type `#feishu-extract` in Kiro chat to use.

### Cursor / Windsurf / Other AI IDEs

Add to your AI IDE knowledge base (e.g. `CLAUDE.md`, `.cursorrules`):

```
## Feishu Document Extraction

Commands (run from feishu-reader directory):
- Status:  .venv/bin/python3 feishu_skill.py status
- Extract: .venv/bin/python3 feishu_skill.py extract "<feishu_url>"
- Batch:   .venv/bin/python3 feishu_skill.py batch "<url1>" "<url2>"
- List:    .venv/bin/python3 feishu_skill.py list
- Search:  .venv/bin/python3 feishu_skill.py search "<keyword>"
- Read:    .venv/bin/python3 feishu_skill.py read "<file_path>"

All commands return JSON. Requires Chrome running + Feishu login.
```

### MCP Server (optional / 可选)

```bash
.venv/bin/python3 feishu_skill.py mcp
```

### HTTP API (optional / 可选)

```bash
.venv/bin/python3 feishu_skill.py serve --port 8900
```

## File Structure / 文件结构

```
feishu_skill.py     — Skill layer: CLI + MCP Server + HTTP API
feishu_cdp.py       — CDP core: PageMain block tree → Markdown
feishu_common.py    — Shared: CDP communication, Chrome, Cookie/Session
extract_feishu.py   — Main entry script
setup.sh / setup.bat — Environment setup (auto-install Python/Chrome/deps)
requirements.txt    — Python dependency (websocket-client only)
output/             — Extracted documents
.claude/skills/       — Claude Code Skill definition
.kiro/skills/        — Kiro AI Skill definition
```

## Requirements / 系统要求

- Python 3.8+ (auto-installed by setup)
- Google Chrome (auto-installed by setup)
- macOS / Windows / Linux
- Only pip dependency: `websocket-client`

## Notes / 注意事项

- Chrome runs in CDP debug mode (port 9222), `setup.sh` auto-configures
- First use requires Feishu login, session cached at `~/.cache/feishu-reader/cookies.json`
- URLs must be quoted in zsh to prevent glob expansion
- pip install supports China mirror auto-fallback (Tsinghua, Aliyun)
- setup.sh download chain: Google/PyPI → China mirrors → CDN `dl.hutiefang.com`

## CDN Fallback / 国内下载兜底

All download dependencies have CDN fallback via `dl.hutiefang.com` (Qiniu Cloud):

| Resource | Primary | Fallback |
|----------|---------|----------|
| Source code | GitHub | `http://dl.hutiefang.com/feishu-reader-latest.tar.gz` |
| Chrome (Linux) | dl.google.com | CDN → `apt install chromium-browser` |
| websocket-client | PyPI → Tsinghua → Aliyun | `http://dl.hutiefang.com/websocket_client-1.9.0-py3-none-any.whl` |

CDN maintenance / CDN 维护:
```bash
# Update tarball after release / 发版后更新
git archive --format=tar.gz --prefix=feishu-reader/ -o /tmp/feishu-reader-latest.tar.gz HEAD
qshell fput feishu-reader feishu-reader-latest.tar.gz /tmp/feishu-reader-latest.tar.gz --overwrite
```

## License

MIT
