"""
Markdown cleanup utilities.
Markdown 清理工具。
"""
import re


def cleanup_markdown(md_text, title=""):
    """Clean up extracted Markdown: normalize whitespace, add title if missing."""
    md_text = re.sub(r'\n{4,}', '\n\n\n', md_text)
    md_text = re.sub(r' +\n', '\n', md_text)
    if title and not md_text.strip().startswith('#'):
        md_text = f"# {title}\n\n{md_text}"
    return md_text.strip() + "\n"
