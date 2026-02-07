"""
Feishu Document Extractor — Main Entry
飞书文档提取工具 — 主入口

Extracts Feishu cloud documents to Markdown via Chrome DevTools Protocol (CDP).
通过 CDP 访问飞书内部数据模型，提取文档为 Markdown。

Usage / 用法:
    python extract_feishu.py <feishu_url>              # Extract document / 提取文档
    python extract_feishu.py <feishu_url> -o doc.md    # Specify output / 指定输出
    python extract_feishu.py login                     # Login only / 仅登录
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Feishu Document Extractor / 飞书文档提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples / 示例:
  python extract_feishu.py login                            # Login only / 仅登录
  python extract_feishu.py https://xxx.feishu.cn/docx/xxx   # Extract / 提取
  python extract_feishu.py https://xxx.feishu.cn/docx/xxx -o doc.md
        """,
    )
    parser.add_argument("url", help="Feishu document URL or 'login'")
    parser.add_argument("--wait", type=int, default=10, help="Page load wait seconds (default 10)")
    parser.add_argument("--output", "-o", help="Output Markdown file path")
    args = parser.parse_args()

    if args.url.lower() == "login":
        from feishu_cdp import login_only
        if login_only():
            print("[Done/完成] Login successful, session saved / 登录成功，Session 已保存")
        else:
            print("[Failed/失败] Login not completed / 登录未完成")
        return

    from feishu_cdp import extract_via_cdp
    result = extract_via_cdp(args.url, args.output, args.wait)

    if result.get("success"):
        print(f"\n{'='*50}")
        print(f"  Doc / 文档: {result.get('title', '?')}")
        print(f"  Output / 输出: {result.get('md_path', '?')}")
        print(f"  Method / 方式: {result.get('method', '?').upper()}")
        if result.get("image_count"):
            print(f"  Images / 图片: {result['image_count']}")
        print(f"{'='*50}")
    else:
        print(f"[Error/错误] {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
