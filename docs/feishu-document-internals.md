# 飞书云文档内部数据模型 — 完整技术解析

> 基于对飞书 docx 页面的 Chrome DevTools Protocol (CDP) 逆向探测，
> 记录飞书云文档的内部数据结构、渲染机制和数据提取方法。
> 所有结论均经过实际测试验证（2026-02-07）。

---

## 一、飞书文档的整体架构

### 1.1 页面结构

飞书云文档（`feishu.cn/docx/xxx`）是一个 SPA 应用，核心编辑器基于自研的 Block Editor。
页面加载后，全局对象 `window.PageMain` 暴露了完整的文档数据模型：

```
window.PageMain
  ├── blockManager
  │   ├── rootBlockModel          ← 文档根节点（type: "page"）
  │   ├── blockMap                ← 所有 block 的 id→block 映射
  │   └── ...
  ├── imageManager                ← 图片资源管理
  └── ...
```

### 1.2 Block 树模型

飞书文档的内容以 Block 树组织，类似于 Notion 的 Block 概念。
每个 Block 有以下核心属性：

```javascript
block = {
    type: "text" | "heading1" | "table" | "sheet" | "image" | "code" | ...,
    id: "唯一标识",
    children: [],              // 子 block 数组
    zoneState: {
        content: {
            ops: [...]         // 富文本操作序列（类 Quill Delta 格式）
        },
        allText: "纯文本内容"
    },
    snapshot: {
        type: "block类型",
        columns_id: [...],     // table 专用：列 ID 数组
        token: "xxx_sheetId",  // sheet 专用：包含 sheetId
        image: { token, name },// image 专用
        language: "Java",      // code 专用
        seq: "auto" | "1",     // ordered list 专用
        done: true/false,      // todo 专用
        ...
    },
    record: { id: "..." },
    bridge: { bridge: {...} }, // sheet 专用：通往电子表格引擎的桥接
    imageManager: { fetch },   // image 专用：图片获取器
}
```

---

## 二、Block 类型完整清单

以下是通过实际文档验证的所有 block 类型：

| Block Type | 说明 | 数据来源 | 特殊处理 |
|-----------|------|---------|---------|
| `page` | 文档根节点 | children 包含所有顶层 block | 递归遍历入口 |
| `text` | 普通段落 | zoneState.content.ops | 可有子 block |
| `heading1`~`heading9` | 标题 | zoneState.content.ops | 可有子 block（折叠内容） |
| `bullet` | 无序列表项 | zoneState.content.ops + children | 支持嵌套 |
| `ordered` | 有序列表项 | zoneState.content.ops + children | snapshot.seq 常为 "auto"，需自行计算 |
| `todo` | 待办事项 | zoneState.content.ops | snapshot.done 标记完成状态 |
| `code` | 代码块 | zoneState.allText 或 ops | snapshot.language 指定语言 |
| `table` | 原生表格 | children 是所有 cell block | snapshot.columns_id 定义列数 |
| `sheet` | 嵌入电子表格 | bridge.bridge.sheetManager | canvas 渲染，数据不在 DOM |
| `image` | 图片 | snapshot.image.token | 需通过 imageManager.fetch 获取 URL |
| `divider` | 分割线 | 无内容 | 输出 `---` |
| `quote_container` | 引用块 | children | 子 block 加 `>` 前缀 |
| `callout` | 高亮提示块 | children | 类似引用块 |
| `grid` | 多列布局 | children（每列一个 grid_column） | 展平为顺序内容 |
| `iframe` | 嵌入网页 | snapshot.iframe.component.url | 输出链接 |
| `isv` | 第三方插件 | snapshot.data.data | 如 mermaid 图 |
| `synced_source` | 同步块引用 | children（引用的实际内容） | 需要递归展开 |
| `toggle_heading` | 折叠标题 | children（折叠内容） | 需要展开子节点 |

---

## 三、富文本样式系统（ops）

### 3.1 ops 结构

飞书的富文本采用类似 Quill Delta 的 ops 数组格式：

```javascript
block.zoneState.content.ops = [
    {
        insert: "文本内容",
        attributes: {
            bold: true,
            italic: true,
            strikethrough: true,
            inlineCode: true,
            link: "https://...",                    // URL 编码
            textHighlight: "#ff0000",               // 字体颜色
            textHighlightBackground: "rgb(247,105,100)", // 背景色
            equation: "E=mc^2",                     // 行内公式
            "inline-component": '{"type":"mention_doc","data":{...}}',
            fixEnter: true,                         // 段落结尾标记，应跳过
        }
    },
    ...
]
```

### 3.2 样式属性完整列表

| 属性名 | 类型 | 说明 | Markdown 输出 |
|--------|------|------|--------------|
| `bold` | boolean | 粗体 | `**text**` |
| `italic` | boolean | 斜体 | `*text*` |
| `strikethrough` | boolean | 删除线 | `~~text~~` |
| `inlineCode` | boolean | 行内代码 | `` `text` `` |
| `link` | string | 超链接（URL 编码） | `[text](url)` |
| `textHighlight` | string | 字体颜色（CSS 颜色值） | `<font color="...">` |
| `textHighlightBackground` | string | 背景高亮色 | `<mark style="background:...">` |
| `equation` | string | LaTeX 公式 | `$formula$` |
| `inline-component` | JSON string | 内联组件（mention_doc 等） | 解析后输出链接 |
| `fixEnter` | boolean | 段落结尾换行标记 | 跳过不输出 |

### 3.3 颜色值格式

飞书使用多种颜色格式，需要统一处理：
- HEX: `#ff0000`, `#1f2329`
- RGB: `rgb(247,105,100)`, `rgb(31, 35, 41)`
- RGBA: `rgba(183,237,177,0.8)`, `rgba(186,206,253,0.7)`
- 关键字: `inherit`

飞书默认文字颜色为 `#1f2329` / `rgb(31, 35, 41)`，提取时应过滤掉。

---

## 四、原生表格（Table Block）

### 4.1 结构

原生表格是飞书 docx 编辑器内置的表格，数据直接在 block 树中：

```javascript
tableBlock = {
    type: "table",
    snapshot: {
        columns_id: ["col1", "col2", "col3", ...]  // 列 ID 数组，决定列数
    },
    children: [
        // 所有 cell 按行优先顺序排列
        // cell 数量 = 行数 × 列数
        cellBlock1, cellBlock2, cellBlock3,  // 第1行
        cellBlock4, cellBlock5, cellBlock6,  // 第2行
        ...
    ]
}
```

### 4.2 Cell Block

每个 cell 本身也是一个 block，其 children 包含段落 block：

```javascript
cellBlock = {
    type: "table_cell",  // 或其他类型
    children: [
        { type: "text", zoneState: { content: { ops: [...] } } },
        // 一个 cell 可以有多个段落
    ]
}
```

### 4.3 提取方法

```javascript
const colCount = block.snapshot.columns_id.length;
const cells = block.children;
// 按 colCount 分行
for (let i = 0; i < cells.length; i += colCount) {
    const row = cells.slice(i, i + colCount);
    // 每个 cell 的文本 = cell.children.map(blockText).join(' ')
}
```

---

## 五、嵌入电子表格（Sheet Block）— 核心难点

### 5.1 为什么 Sheet 是难点

飞书 docx 中嵌入的电子表格（sheet block）与原生表格完全不同：
- 用 **canvas** 渲染，DOM 中没有表格数据
- 数据存储在独立的电子表格引擎中（collaSpread）
- 开源项目 cloud-document-converter 也标记为 `NotSupportedBlock`
- 需要滚动到可视区域才会加载数据

### 5.2 数据访问路径（已验证可用）

```
sheet block
  → bridge.bridge.sheetManager
    → sheetComponents: Map (所有 sheet 实例)
      → .get(sheetId)
        → .props.collaSpread._spread
          → sheetIdToIndexMap: Map (sheetId → 数组索引)
          → sheets[idx]: sheet 实例
            → _dataModel
              → rowCount, colCount
              → contentModel
              → composedStyleCache
              → styleDropdownModel
```

### 5.3 SheetId 映射

sheet block 的 `snapshot.token` 包含 sheetId：

```
token = "B8rFsF217htvXktCIYwcxIXPnDA_0YvteY"
                                   ^^^^^^^^
                                   sheetId（下划线后缀）
```

`sheetManager.sheetComponents` 是一个 Map，key 就是这个 sheetId。

### 5.4 单元格数据读取

经过大量方法探测，以下是可用的 API：

| 方法 | 返回值 | 状态 |
|------|--------|------|
| `sh.getValue(row, col)` | 单元格原始值（字符串/数字） | ✅ 可用 |
| `sh.getText(row, col)` | 单元格文本 | ✅ 可用 |
| `sh.getStyle(row, col)` | 单元格样式对象 | ✅ 可用 |
| `sh.getCellStyle(row, col)` | 同 getStyle | ✅ 可用 |
| `sh.getActualStyle(row, col)` | 计算后的样式 | ✅ 可用 |
| `contentModel.get(row, col)` | `{_variant:{value}, _segmentArray, _multipleValues}` | ✅ 可用 |
| `sh.getCell(row, col)` | — | ❌ 不存在 |
| `sh.getRange(row, col, ...)` | — | ❌ 不存在 |
| `sh.getDisplayText(row, col)` | — | ❌ 不存在 |
| `sh.getCellText(row, col)` | — | ❌ 不存在 |
| `sh.getCellValue(row, col)` | — | ❌ 不存在 |
| `sh.getFormattedValue(row, col)` | — | ❌ 不存在 |

### 5.5 单元格样式结构

`sh.getStyle(row, col)` 返回的样式对象：

```javascript
{
    _vAlign: 1,                    // 垂直对齐 (0=top, 1=middle, 2=bottom)
    _hAlign: 0,                    // 水平对齐 (0=left, 3=center, ...)
    _font: {                       // 字体信息
        fontSize: 14,
        fontWeight: 700,           // 700 = bold
        fontStyle: "italic",       // 斜体
        textDecoration: "line-through", // 删除线
    },
    _wordWrap: 1,                  // 自动换行
    _foreColor: "#1f2329",         // 字体颜色
    _backColor: "#f5f5f5",         // 背景色（如果有）
    _borderTop: { color: "rgba(255,255,255,0.18)", width: 1 },
    _borderBottom: { color: "rgba(255,255,255,0.69)", width: 1 },
    _default: { ... },             // 默认样式引用
}
```

关键属性名（带下划线前缀）：
- `_foreColor` — 字体颜色
- `_backColor` / `_backgroundColor` — 背景色
- `_font` — 字体对象（可能是对象或 CSS font 字符串）
- `_borderTop/Bottom/Left/Right` — 边框

飞书默认文字色：`#1f2329` / `rgb(31, 35, 41)`，提取时应过滤。

### 5.6 样式引用系统

Sheet 使用引用 ID 系统管理样式，避免重复存储：

```
composedStyleCache.model.get(0, 0)
  → { table: [[1,1,1,1,1], [2,2,2,2,2], [3,3,3,3,3], ...] }
  // 二维数组，每个值是样式引用 ID

composedStyleCache.refs.idToRef._map
  → Map {
      1 → { _font: {fontSize:14, fontWeight:700}, _foreColor: "#1f2329", ... },  // 表头样式
      2 → { _font: {fontSize:14}, _foreColor: "#1f2329", _hAlign: 3, ... },      // 居中样式
      3 → { _font: {fontSize:14}, _foreColor: "#1f2329", _borderTop: {...}, ... },// 带边框
      4 → { _font: {fontSize:14}, _foreColor: "rgb(31, 35, 41)", _wordWrap: 0 }, // 不换行
    }
```

`styleDropdownModel` 结构类似，也有 `model`（引用 ID 表）和 `styleRefMgr`（ID→样式映射）。

### 5.7 contentModel 结构

`contentModel.get(row, col)` 返回：

```javascript
{
    _segmentArray: null | [...],   // 富文本段数组（多样式单元格）
    _variant: { value: "cell text" }, // 单元格值
    _multipleValues: null          // 多值（下拉选择等）
}
```

当 `_segmentArray` 非空时，表示单元格包含富文本（不同部分有不同样式）。

### 5.8 滚动加载

Sheet block 使用 canvas 渲染，必须滚动到可视区域才会初始化数据。
提取前需要执行滚动操作：

```javascript
// 快速滚到底再回扫，确保所有 sheet 加载
const container = document.querySelector('#docx > div');
// 分段滚动，每段等待 60-200ms
```

---

## 六、有序列表的序号问题

### 6.1 问题

飞书的 ordered list block 的 `snapshot.seq` 字段经常返回 `"auto"` 而非实际数字。
这是因为飞书编辑器在渲染时动态计算序号，数据模型中不存储。

### 6.2 解决方案

在提取时自行计算序号：
1. 遍历父 block 的 children 数组
2. 统计连续的 `ordered` 类型 block
3. 遇到非 `ordered` 类型则重置计数器

```javascript
// 在 flatChildren 中注入 _parent 引用
child._parent = parent;

// 在 blockToMd 的 ordered case 中
let count = 0;
for (const sib of parent.children) {
    if (sib.type === 'ordered') count++;
    else count = 0;  // 非 ordered 打断序号
    if (sib.id === block.id) { seq = count; break; }
}
```

### 6.3 验证结果

18、云对云文档有 9 个有序列表项（3 个独立列表），修复后输出：
`[1, 2, 3, 1, 2, 1, 2, 3, 4]` — 每个列表独立编号，完全正确。

---

## 七、代码块提取

### 7.1 问题

代码块的语言信息存储在 `block.snapshot.language`（不是 `block.language`）。
代码内容优先从 `zoneState.allText` 获取，但某些情况下可能为空。

### 7.2 数据来源优先级

1. `block.zoneState.allText` — 主要来源
2. `block.zoneState.content.ops` — ops 中的 insert 拼接
3. `block.children` — 子 block 的文本拼接

### 7.3 验证结果

18、云对云文档的 Java 代码块：
- `snapshot.language` = "Java"
- `allText` = 3588 字符（完整的 SignatureUtil 类）
- 修复前输出为空，修复后完整提取

---

## 八、图片处理

### 8.1 图片 Token

图片 block 的 `snapshot.image.token` 是飞书内部的资源标识符，不是 URL。

### 8.2 获取真实 URL

通过 `imageManager.fetch` 异步获取：

```javascript
imgBlock.imageManager.fetch(
    { token: 'xxx', isHD: true, fuzzy: false },
    {},
    (sources) => {
        const url = sources?.src || sources?.originSrc;
        // url 是可直接访问的图片 URL
    }
);
```

### 8.3 下载方式

获取 URL 后，通过 `fetch()` + `FileReader.readAsDataURL()` 转为 base64，
再在 Python 端 `base64.b64decode()` 保存为文件。

---

## 九、登录与 Session

### 9.1 登录检测

```javascript
// 判断是否在登录页
location.href.includes('/accounts/page/login')
location.href.includes('passport.feishu.cn')

// 判断文档是否加载
document.querySelector('#docx > div div[data-block-id]')  // docx
window.PageMain?.blockManager?.rootBlockModel              // PageMain 就绪
```

### 9.2 Cookie 持久化

通过 CDP `Network.getAllCookies` 获取所有 feishu 域的 cookie，
保存到本地文件，下次启动时通过 `Network.setCookie` 恢复。

---

## 十、提取质量验证（2026-02-07 最终结果）

### 10.1 测试文档集

| 文档 | 字符 | 管道符 | ✅ | 删除线 | 字体色 | 背景色 | 代码 | 图片 |
|------|------|--------|-----|--------|--------|--------|------|------|
| 26、数仓建模方案 | 88,931 | 5,388 | 641 | 54 | 60 | 50 | 0 | 4 |
| 9、三端埋点方案 | 11,910 | 683 | 0 | 60 | 0 | 33 | 2 | 1 |
| 18、云对云 API 签名 | 8,895 | 124 | 0 | 0 | 0 | 8 | 2 | 0 |
| Smart Fob Protocol | 6,680 | 323 | 0 | 0 | 0 | 0 | 0 | 0 |
| CI/CD 规范 | 5,397 | 102 | 0 | 0 | 0 | 10 | 0 | 1 |
| 汽车数字钥匙方案 | 3,188 | 210 | 0 | 0 | 0 | 7 | 0 | 4 |

### 10.2 与手动复制对比（数仓建模方案）

| 指标 | 手动复制参考 | PageMain 提取 | 匹配度 |
|------|-------------|--------------|--------|
| ✅ 符号 | 641 | 641 | 100% |
| 删除线 | 54 | 54 | 100% |
| 管道符 | 5,698 | 5,388 | 95% |
| 字体颜色 | >0 | 60 | ✅ 已提取 |
| 背景色 | >0 | 50 | ✅ 已提取 |
| Sheet 失败 | — | 0/51 | 100% |

管道符差距（~310）来自手动复制时每个 sheet 表格多出的空表头行，非内容遗漏。

### 10.3 跨文档对比

- 18、云对云：提取结果优于手动复制（手动复制丢失了表格格式）
- 9、三端埋点：表格、删除线、背景色全部正确保留
- CI/CD 规范：表格、背景高亮、链接全部正确

---

## 十一、已验证放弃的提取方案

| 方案 | 尝试过程 | 放弃原因 |
|------|---------|---------|
| 飞书开放 API | 实现了完整的 API 客户端 | 需要应用凭证（app_id/app_secret），不通用 |
| CDP DOM 解析 | 解析 `#docx` 下的 DOM 元素 | 虚拟渲染（只渲染可视区域）、表格是 canvas、丢失颜色样式 |
| 油猴脚本注入 | 注入 JS 读取 DOM | 能获取文本结构，但表格/颜色/删除线丢失 |
| CDP 剪贴板模拟 | 发送 Ctrl+A → Ctrl+C 事件 | CDP/JS 事件的 `isTrusted=false`，飞书编辑器不响应 |
| 系统级键盘模拟 | 通过 OS 级别发送按键 | macOS 需要辅助功能权限，不通用 |

---

## 十二、飞书文档的特殊行为

### 12.1 虚拟渲染
飞书编辑器只渲染可视区域的 DOM，滚动时动态创建/销毁 DOM 节点。
但 `PageMain.blockManager.rootBlockModel` 包含完整数据，不受虚拟渲染影响。

### 12.2 Sheet Canvas 渲染
嵌入的电子表格用 canvas 绘制，DOM 中没有 `<table>` 元素。
必须通过 `collaSpread._spread.sheets` 内部 API 读取数据。

### 12.3 isTrusted 安全限制
飞书编辑器检查事件的 `isTrusted` 属性，通过 JS/CDP 触发的事件（`isTrusted=false`）
会被忽略。这导致无法通过模拟键盘事件来复制内容。

### 12.4 登录重定向
访问需要登录的文档时，飞书会重定向到 `passport.feishu.cn`。
登录成功后自动跳回原文档 URL。帮助中心页面（`feishu.cn/hc/`）的重定向行为不同，
可能需要特殊处理。

### 12.5 弹窗干扰
飞书页面经常弹出各种提示（"知道了"、"确定"等），需要在提取前自动关闭。

### 12.6 synced_source 块
飞书支持"同步块"功能，多个文档可以引用同一个内容块。
在 block 树中表现为 `synced_source` 类型，其 children 是实际内容，需要递归展开。
