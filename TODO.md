# Feishu Reader — TODO

## Testing / 测试
- [ ] Windows 11 ARM (UTM) end-to-end test: install Claude Code + CC Switch + configure provider + clone repo + setup.bat + extract
- [ ] Linux (Ubuntu/Debian) test
- [ ] Fresh macOS test (no Python, no Chrome pre-installed)

## Features / 功能
- [ ] Incremental extraction: skip already-extracted docs (compare by URL hash or doc token)
- [ ] Export format options: Markdown / JSON / HTML
- [ ] Feishu Bitable (多维表格) support
- [ ] Feishu Mindnote (思维笔记) support
- [ ] Feishu Slides (演示文稿) support
- [ ] Auto-detect Chrome running without CDP and prompt user to restart
- [ ] Session expiry detection and auto-refresh
- [ ] Proxy support for corporate networks
- [ ] Progress callback for batch extraction (percentage, ETA)

## Quality / 质量
- [ ] Unit tests for Markdown conversion (block → md)
- [ ] Integration test with sample Feishu page
- [ ] CI/CD pipeline (GitHub Actions)

## Documentation / 文档
- [ ] English README (full translation, not just bilingual)
- [ ] Architecture diagram
- [ ] Contributing guide
- [ ] Changelog
