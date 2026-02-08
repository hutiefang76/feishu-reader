---
name: feishu-extract
description: "Extract Feishu (Lark) cloud documents to high-quality Markdown via Chrome CDP, preserving tables, colors, strikethrough, images, code blocks, and all inline styles. Use when the user wants to read, extract, download, save, or convert a Feishu/Lark document URL to Markdown. Triggers on URLs matching feishu.cn/docx, feishu.cn/wiki, feishu.cn/doc, feishu.cn/sheets, feishu.cn/hc, or larksuite.com equivalents. Also use for listing, searching, or reading previously extracted documents. Supports batch extraction of multiple URLs. Keywords: 飞书, Lark, feishu, 飞书文档, cloud document, markdown conversion, 文档提取."
allowed-tools: Bash, Read, Glob, Grep
---

# Feishu Document Extraction

**Skill root**: Find the `feishu-reader` directory containing `feishu_skill.py`. All commands below must run from that directory.

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

Run all commands from the `feishu-reader` directory using `.venv/bin/python3`. All return JSON with `success` field.

```bash
# Environment check (run first)
cd feishu-reader && .venv/bin/python3 feishu_skill.py status

# Extract single document
cd feishu-reader && .venv/bin/python3 feishu_skill.py extract "<feishu-url>"

# Batch extract
cd feishu-reader && .venv/bin/python3 feishu_skill.py batch "<url1>" "<url2>"

# List / Search / Read
cd feishu-reader && .venv/bin/python3 feishu_skill.py list
cd feishu-reader && .venv/bin/python3 feishu_skill.py search "<keyword>"
cd feishu-reader && .venv/bin/python3 feishu_skill.py read "<path>"
```

If environment not ready, run `cd feishu-reader && bash setup.sh`.

## Workflow

1. Run `status` — verify dependencies, Chrome, and session
2. Run `extract "<url>"` — Chrome opens, navigates to document
3. If first run or session expired, user scans QR code in the opened Chrome window
4. Tool auto-detects: login state, URL redirects, error pages (with interactive recovery), and content stability (block count polling)
5. Output: `output/<title>.md` + `output/<title>/` (images)

## Examples

**Successful extraction:**
```
$ cd feishu-reader && .venv/bin/python3 feishu_skill.py extract "https://xxx.feishu.cn/docx/abc123"
{"success": true, "title": "文档标题", "md_path": "/path/output/文档标题.md",
 "char_count": 12345, "image_count": 3, "method": "cdp_pagemain"}
```

**Login required:**
```
[Login/登录] Please scan QR code or enter credentials in Chrome
```
→ User scans QR in opened Chrome → extraction continues automatically.

**Invalid URL:**
```
{"success": false, "error": "不是有效的飞书文档 URL: https://bad-url.com"}
```

## Edge Cases

- URLs must be quoted in zsh (`"https://..."`) to prevent glob expansion
- Truncated URLs: tool captures browser's actual URL after redirect, auto-corrects
- Error pages (4401, 404): tool detects and prompts user to fix in Chrome
- Sheet spreadsheets: requires scroll-loading, slightly longer extraction
- Large documents: progressive outline output during content stability check

## Failed Approaches (do not retry)

1. **Feishu API** — requires app credentials, not universal for arbitrary accounts
2. **CDP DOM parsing** — Feishu uses virtual rendering; tables are canvas, styles lost
3. **Tampermonkey injection** — gets text structure but loses tables/colors/strikethrough
4. **CDP clipboard (Ctrl+A/C)** — `isTrusted=false`, Feishu editor ignores synthetic events
5. **System keyboard simulation** — needs accessibility permissions, not cross-platform
6. **`type === 'heading'` check** — Feishu uses `heading1`..`heading9`, not `heading`
7. **Hardcoded Chinese error text matching** — breaks on locale changes; use structural exclusion instead

## Reference Files

- **Technical internals**: See [docs/feishu-document-internals.md](../../docs/feishu-document-internals.md) for PageMain block types, data model, and Sheet cell style details
