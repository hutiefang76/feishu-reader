# Feishu Reader — Project Knowledge Base
# 飞书文档提取工具 — 项目知识库

## Overview / 概述
Universal Feishu document extraction tool. Uses Chrome DevTools Protocol (CDP) to access
`window.PageMain.blockManager.rootBlockModel` and convert Feishu cloud docs to Markdown.
Preserves tables, colors, strikethrough, images. Output optimized for AI consumption.

## Runtime / 运行环境
- Python venv: `.venv/bin/python3` (not system python)
- Chrome CDP port: 9222
- Output: `output/`
- Cross-platform: macOS + Windows + Linux
- zsh: quote URLs to prevent glob expansion
- Kill Chrome remnants: `pkill -9 -f "Google Chrome"`

## File Structure / 文件结构
```
feishu_skill.py     — Skill layer (CLI + HTTP API + MCP Server)
feishu_cdp.py       — CDP core: PageMain block tree → Markdown + Sheet extraction
feishu_common.py    — Shared: cdp()/js(), Chrome management, Cookie/Tab management
extract_feishu.py   — Main entry script
feishu_ocr.py       — [DEPRECATED] OCR fallback (not used)
feishu_api.py       — [DEPRECATED] API approach (not used)
setup.sh / setup.bat — Environment setup (auto-install Python/Chrome/deps)
requirements.txt    — Python dependency: websocket-client only
output/             — Extracted documents
.kiro/skills/       — Kiro AI Skill definition
```

## Architecture / 技术架构

### Core: PageMain Data Model ✅
See `docs/feishu-document-internals.md` for full technical docs.

### Abandoned Approaches (do not retry) / 已放弃方案
1. API — requires app credentials, not universal
2. CDP DOM parsing — virtual rendering, tables are canvas, loses styles
3. Tampermonkey injection — gets text but loses tables/colors/strikethrough
4. CDP clipboard Ctrl+A/C — isTrusted=false, Feishu editor ignores
5. System keyboard simulation — needs accessibility permissions, not universal

### Verified Capabilities (2026-02-07) / 已验证能力
- ✅ Text, headings(1-9), dividers, code blocks, quotes, callouts
- ✅ Lists (ordered with auto-numbering, unordered, todo, nested)
- ✅ Native tables + Sheet spreadsheet embeds (51 sheet blocks all succeeded)
- ✅ Image download, multi-column layout, iframe, mermaid
- ✅ Inline styles: bold, italic, strikethrough, color, background, links, inline code, formulas
- ✅ Sheet cell styles: foreColor, backColor, font (bold/italic/strikethrough)
- ✅ synced_source / mention_doc / toggle_heading expansion
- ✅ Login detection + Cookie persistence + auto re-login

## User Preferences / 用户偏好
- Communicate in Chinese / 用中文沟通
- Tool must be universal, no per-document patches
- Tables are critical (field names and colors matter for AI)
- pip install needs mirror fallback (China network)
- Can use any free third-party code/libraries
