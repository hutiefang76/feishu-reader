---
inclusion: manual
---

# Feishu Document Extraction Skill

Extract Feishu (Lark) cloud documents to high-quality Markdown, preserving tables, colors, strikethrough, code blocks, images, and more.
Uses Chrome DevTools Protocol to access Feishu's internal data model — no API keys required.

## Prerequisites

- Project directory: This skill depends on Python scripts in the project root
- Python 3.8+ in virtual environment: `.venv/bin/python3` (macOS/Linux) or `.venv\Scripts\python.exe` (Windows)
- Google Chrome (any recent version)
- Only dependency: `websocket-client` (auto-installed by setup)
- If not set up yet, run `bash setup.sh` (macOS/Linux) or `setup.bat` (Windows) — it auto-detects and installs Python, Chrome, and deps

## Available Commands

### 1. Check Environment Status
```bash
.venv/bin/python3 feishu_skill.py status
```
Returns JSON: dependency status, Chrome running state, cached session info, extracted document count.

### 2. Extract a Single Feishu Document
```bash
.venv/bin/python3 feishu_skill.py extract "<feishu_document_url>"
```
Optional args: `--output <path>` to specify output file, `--wait <seconds>` for page load wait (default 10s).
Output saved to `output/<document_title>.md`.

### 3. Batch Extract Multiple Documents
```bash
.venv/bin/python3 feishu_skill.py batch "<url1>" "<url2>" "<url3>"
```
Optional args: `--wait <seconds>` wait time per document (default 12s).

### 4. List Extracted Documents
```bash
.venv/bin/python3 feishu_skill.py list
```
Returns JSON: paths, titles, and sizes of all extracted documents.

### 5. Search Document Content
```bash
.venv/bin/python3 feishu_skill.py search "<keyword>"
```
Searches extracted documents for keyword matches, returns matching documents and lines.

### 6. Read an Extracted Document
```bash
.venv/bin/python3 feishu_skill.py read "<file_path>"
```
Path can be absolute or relative to the `output/` directory.

### 7. Login Only
```bash
.venv/bin/python3 extract_feishu.py login
```
Opens browser to guide Feishu login. Session is saved automatically.

## Workflow

1. Run `status` to check the environment
2. If Chrome is not running, prompt the user to start Chrome with CDP debugging port:
   ```bash
   # macOS
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --remote-debugging-port=9222 \
     '--remote-allow-origins=*' \
     --user-data-dir="$HOME/Library/Caches/feishu-reader/chrome-profile" \
     --no-first-run
   ```
3. If not logged in, run `extract_feishu.py login`
4. Use `extract` or `batch` to extract documents
5. Use `list`, `search`, `read` to browse extracted content

## Notes

- URLs must be quoted (prevents glob expansion in zsh)
- Supported document types: docx, wiki, sheet, hc (help center)
- Extraction preserves: tables (native + Sheet spreadsheets), colors, strikethrough, bold, italic, code blocks, images, links
- Sheet spreadsheets require scroll-loading and take slightly longer to extract
- All commands return JSON results with a `success` field indicating outcome
