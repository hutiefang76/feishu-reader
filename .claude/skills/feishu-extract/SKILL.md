---
name: feishu-extract
description: Extract Feishu (Lark) cloud documents to Markdown via Chrome CDP. Use when the user wants to read, extract, or convert a Feishu document URL to Markdown.
argument-hint: "[url] [--output path] [--wait seconds]"
allowed-tools: Bash, Read, Glob, Grep
---

# Feishu Document Extraction

Extract Feishu cloud documents to high-quality Markdown preserving tables, colors, images, and styles.
Uses Chrome DevTools Protocol — no API keys required.

## Environment

!`.venv/bin/python3 feishu_skill.py status 2>/dev/null || echo '{"error":"not set up, run: bash setup.sh"}'`

## Commands

### Extract document
```bash
.venv/bin/python3 feishu_skill.py extract "$ARGUMENTS" --output "$1"
```

### Batch extract
```bash
.venv/bin/python3 feishu_skill.py batch "<url1>" "<url2>"
```

### List / Search / Read extracted documents
```bash
.venv/bin/python3 feishu_skill.py list
.venv/bin/python3 feishu_skill.py search "<keyword>"
.venv/bin/python3 feishu_skill.py read "<path>"
```

### Login only (save session for later)
```bash
.venv/bin/python3 extract_feishu.py login
```

## Workflow

1. Run `status` — if environment not ready, run `bash setup.sh`
2. Run `extract "<url>"` — Chrome opens, user scans QR if not logged in
3. Tool auto-detects login, error pages, URL redirects, and content stability
4. Output: `output/<title>.md` + `output/<title>/` (images)
5. All commands return JSON with `success` field

## Notes

- URLs must be quoted in zsh (prevents glob expansion)
- Supported types: `docx`, `wiki`, `doc`, `sheets`, `hc`
- First run requires QR code login; session auto-persists via cookies
- Chrome CDP port: 9222
- Use `.venv/bin/python3`, not system python
