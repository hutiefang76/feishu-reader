---
name: feishu-extract
description: Extract Feishu (Lark) cloud documents to high-quality Markdown via Chrome CDP, preserving tables, colors, strikethrough, images, code blocks, and all inline styles. Use when the user wants to read, extract, download, save, or convert a Feishu/Lark document URL to Markdown. Triggers on URLs matching feishu.cn/docx, feishu.cn/wiki, feishu.cn/doc, feishu.cn/sheets, feishu.cn/hc, or larksuite.com equivalents. Also use for listing, searching, or reading previously extracted documents. Supports batch extraction of multiple URLs. Keywords: 飞书, Lark, feishu, 飞书文档, cloud document, markdown conversion, 文档提取.
allowed-tools: Bash, Read, Glob, Grep
---

# Feishu Document Extraction

## Decision Tree

```
User request → Contains feishu.cn or larksuite.com URL?
    ├─ Yes, single URL → extract
    ├─ Yes, multiple URLs → batch
    └─ No URL provided
        ├─ Wants to find/browse docs → list or search
        ├─ Wants to read a doc → read <path>
        └─ Wants to check setup → status
```

## Commands

All commands use `.venv/bin/python3 feishu_skill.py` as entry point. All return JSON with `success` field.

**Extract single document:**
```bash
.venv/bin/python3 feishu_skill.py extract "$ARGUMENTS"
```

**Batch extract:**
```bash
.venv/bin/python3 feishu_skill.py batch "url1" "url2" "url3"
```

**List / Search / Read:**
```bash
.venv/bin/python3 feishu_skill.py list
.venv/bin/python3 feishu_skill.py search "keyword"
.venv/bin/python3 feishu_skill.py read "output/doc.md"
```

**Environment check:**
```bash
.venv/bin/python3 feishu_skill.py status
```

## Workflow

1. Run `status` — if not ready, run `bash setup.sh`
2. Run `extract "<url>"` — Chrome opens automatically
3. If first run or session expired, user scans QR code to login in the opened Chrome window
4. Tool auto-detects: login state, URL redirects, error pages (with interactive recovery), and content stability (block count polling)
5. Output: `output/<title>.md` + `output/<title>/` (images)

## Examples

**Single extraction:**
```
$ .venv/bin/python3 feishu_skill.py extract "https://xxx.feishu.cn/docx/abc123"
{"success": true, "title": "文档标题", "md_path": "/path/output/文档标题.md",
 "char_count": 12345, "image_count": 3, "method": "cdp_pagemain"}
```

**Failed extraction (not logged in):**
```
[Login/登录] Please scan QR code or enter credentials in Chrome
```
→ User scans QR in opened Chrome → extraction continues automatically.

## Edge Cases

- URLs must be quoted in zsh (`"https://..."`) to prevent glob expansion
- Truncated URLs: tool captures browser's actual URL after redirect, auto-corrects
- Error pages (4401, 404): tool detects and prompts user to fix in Chrome
- Sheet spreadsheets: requires scroll-loading, slightly longer extraction
- Large documents: progressive outline output during content stability check

## Reference Files

- **Technical internals**: See [docs/feishu-document-internals.md](../../docs/feishu-document-internals.md) for PageMain block types, data model, and Sheet cell style details
