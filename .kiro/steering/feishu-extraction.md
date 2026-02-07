# 飞书文档提取工具 — 项目知识库

## 项目概述
通用飞书文档提取工具，通过 Chrome DevTools Protocol (CDP) 访问飞书页面内部数据模型，
将飞书云文档（docx）转换为高质量 Markdown，保留表格、颜色、删除线、图片等完整信息。
目标输出供 AI 消费，因此文本表格比图片更有价值。

## 技术架构

### 核心方案: PageMain 数据模型 (✅ 当前最佳)
飞书页面暴露 `window.PageMain.blockManager.rootBlockModel`，包含完整 block 树。
通过 CDP `Runtime.evaluate` 注入 JS 直接遍历 block 树转 Markdown。

优势:
- 不需要滚动加载（数据模型包含全部内容）
- 不需要 DOM 解析（直接读内部数据）
- 不需要剪贴板模拟（无 isTrusted 问题）
- 保留样式信息（颜色、删除线、粗体等）

### 已验证放弃的方案
1. **API 方案** — 不具备通用性，需要应用凭证
2. **CDP DOM 解析** — 虚拟渲染问题，表格是 canvas，丢失颜色/样式
3. **油猴脚本注入** — 获取文本结构，但表格/颜色/删除线丢失
4. **CDP 剪贴板 (Ctrl+A/C)** — CDP/JS 事件 `isTrusted=false`，飞书编辑器不响应
5. **系统级键盘模拟** — 需要辅助功能权限，不通用

### Sheet 单元格样式（已验证）
- `sh.getStyle(r,c)` 返回: `{_foreColor, _backColor, _font, _vAlign, _hAlign, _wordWrap, _borderXxx}`
- `_font` 是对象: `{fontSize, fontWeight, fontStyle, textDecoration}`
- 飞书默认文字色: `#1f2329` / `rgb(31, 35, 41)`，需过滤

## 文件结构
```
feishu_skill.py     — Skill 层（CLI + HTTP API + MCP Server）
feishu_cdp.py       — CDP 核心：PageMain 提取 + sheetToMd
feishu_common.py    — 公共模块：CDP通信、Chrome管理、Cookie、Tab管理
extract_feishu.py   — 主入口脚本
feishu_ocr.py       — [已废弃] OCR 辅助
feishu_api.py       — [已废弃] API 方案
setup.sh / setup.bat — 环境安装（自动安装 Python/Chrome/依赖）
requirements.txt    — Python 依赖（仅 websocket-client）
output/             — 输出目录
```

## 运行注意事项
- 使用 `.venv/bin/python3`，不要用系统 python
- Chrome CDP 端口 9222
- zsh 下参数需引号防 glob 展开
- 依赖安装支持镜像降级（中国网络）
- 登录 Cookie 自动持久化到 `~/Library/Caches/feishu-reader/cookies.json`
- Python 唯一依赖: `websocket-client`
