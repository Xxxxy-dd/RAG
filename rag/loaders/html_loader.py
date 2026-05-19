"""HTML loader to Markdown format.

HTML 的核心目标是做专属格式深度解析，然后统一输出为 Markdown 文档，方便后续做统一切分。

改进点与设计决策：
- 优先识别标题层级，把 H1-H6 转成 Markdown 标题。
- 保留正文段落、项目符号和编号列表的语义，输出为 Markdown 列表或普通段落。
- 单独抽取表格并保留单元格语义，转成 Markdown 表格，避免重要信息丢失。
- 保留链接、加粗、斜体、代码块和引用等常见语义，尽量减少信息损失。
- 跳过 script/style/nav 等非正文内容，减少模板噪声。

使用说明：优先使用 `load_html(path)` 作为统一入口，它会返回已经 Markdown 化的 `Document` 列表；
后续统一切分工作应交给上层的 Markdown splitter。
"""

import re
from pathlib import Path
from typing import List

from bs4 import BeautifulSoup, NavigableString, Tag
from langchain_core.documents import Document


BLOCK_CONTAINER_TAGS = {
	"article",
	"aside",
	"body",
	"div",
	"figure",
	"footer",
	"header",
	"main",
	"nav",
	"section",
}

SKIP_TAGS = {"script", "style", "noscript", "template"}


def _normalize_text(text: str) -> str:
	"""把 HTML 里乱掉的空格和换行整理干净，方便后面统一转 Markdown。"""
	if not text:
		return ""

	text = text.replace("\r\n", "\n").replace("\r", "\n")
	text = re.sub(r"[ \t\f\v]+", " ", text)
	text = re.sub(r"\n{3,}", "\n\n", text)
	return text.strip()


def _safe_select_one_text(soup: BeautifulSoup, selector: str) -> str:
	"""从页面里安全地提取一个元素的纯文本。"""
	node = soup.select_one(selector)
	if not node:
		return ""
	return _normalize_text(node.get_text(" ", strip=True))


def _extract_document_title(soup: BeautifulSoup) -> str:
	"""优先从 <title>、H1 或首个明显标题里提取文档标题。"""
	title = _safe_select_one_text(soup, "title")
	if title:
		return title

	h1 = _safe_select_one_text(soup, "h1")
	if h1:
		return h1

	for selector in ["h2", "h3", "h4"]:
		heading = _safe_select_one_text(soup, selector)
		if heading:
			return heading

	return ""


def _render_inline(node) -> str:
	"""把行内节点渲染成 Markdown 文本。"""
	if node is None:
		return ""

	if isinstance(node, NavigableString):
		return str(node)

	if not isinstance(node, Tag):
		return ""

	name = node.name.lower()
	if name in SKIP_TAGS:
		return ""

	if name == "br":
		return "\n"

	if name in {"strong", "b"}:
		text = _render_children_inline(node)
		return f"**{text}**" if text else ""

	if name in {"em", "i"}:
		text = _render_children_inline(node)
		return f"*{text}*" if text else ""

	if name == "code":
		text = _normalize_text(node.get_text(" ", strip=True))
		return f"`{text}`" if text else ""

	if name == "a":
		text = _render_children_inline(node) or _normalize_text(node.get_text(" ", strip=True))
		href = (node.get("href") or "").strip()
		if href and text:
			return f"[{text}]({href})"
		return text

	if name == "img":
		alt = _normalize_text(node.get("alt", ""))
		src = (node.get("src") or "").strip()
		if src:
			return f"![{alt}]({src})"
		return alt

	if name in {"sup", "sub"}:
		return _render_children_inline(node)

	return _render_children_inline(node)


def _render_children_inline(node) -> str:
	"""渲染一个节点的所有行内子节点。"""
	parts = []
	for child in node.children:
		rendered = _render_inline(child)
		if rendered:
			parts.append(rendered)
	return _normalize_text("".join(parts))


def _is_list_tag(tag: Tag) -> bool:
	return isinstance(tag, Tag) and tag.name.lower() in {"ul", "ol"}


def _list_to_markdown(tag: Tag, indent: int = 0) -> List[str]:
	"""把 ul/ol 转成 Markdown 列表。"""
	lines: List[str] = []
	ordered = tag.name.lower() == "ol"
	counter = 1

	for li in tag.find_all("li", recursive=False):
		item_inline_parts = []
		nested_lists = []

		for child in li.children:
			if isinstance(child, Tag) and _is_list_tag(child):
				nested_lists.append(child)
				continue
			rendered = _render_inline(child)
			if rendered:
				item_inline_parts.append(rendered)

		item_text = _normalize_text("".join(item_inline_parts))
		prefix = f"{counter}." if ordered else "-"
		indent_str = "  " * indent
		if item_text:
			lines.append(f"{indent_str}{prefix} {item_text}")
		else:
			lines.append(f"{indent_str}{prefix}")

		for nested in nested_lists:
			lines.extend(_list_to_markdown(nested, indent=indent + 1))

		counter += 1

	return lines


def _table_to_markdown(table: Tag) -> str:
	"""把 HTML table 转成 Markdown 表格。"""
	rows: List[List[str]] = []

	for tr in table.find_all("tr", recursive=False):
		cells = []
		for cell in tr.find_all(["th", "td"], recursive=False):
			cell_text = _normalize_text(cell.get_text(" ", strip=True)).replace("\n", " ")
			cells.append(cell_text)
		if any(cells):
			rows.append(cells)

	if not rows:
		return ""

	header = rows[0]
	body_rows = rows[1:]
	header_line = "| " + " | ".join(header) + " |"
	separator_line = "|" + "|".join(["---"] * len(header)) + "|"
	body_lines = ["| " + " | ".join(row) + " |" for row in body_rows]
	return "\n".join([header_line, separator_line, *body_lines])


def _blockquote_to_markdown(tag: Tag) -> List[str]:
	"""把 blockquote 转成 Markdown 引用。"""
	content = _normalize_text(tag.get_text("\n", strip=True))
	if not content:
		return []

	return [f"> {line}" if line else ">" for line in content.splitlines()]


def _pre_to_markdown(tag: Tag) -> List[str]:
	"""把 pre/code block 转成 Markdown 代码块。"""
	code = tag.get_text("\n", strip=False)
	code = code.strip("\n")
	if not code:
		return []

	return ["```", *code.splitlines(), "```"]


def _heading_to_markdown(tag: Tag) -> str:
	"""把 h1-h6 转成 Markdown 标题。"""
	level = int(tag.name[1])
	text = _normalize_text(tag.get_text(" ", strip=True))
	if not text:
		return ""
	return f"{'#' * min(max(level, 1), 6)} {text}"


def _element_to_markdown_lines(node) -> List[str]:
	"""把一个 HTML 节点递归转成 Markdown 行。"""
	lines: List[str] = []

	if isinstance(node, NavigableString):
		text = _normalize_text(str(node))
		if text:
			lines.append(text)
		return lines

	if not isinstance(node, Tag):
		return lines

	name = node.name.lower()
	if name in SKIP_TAGS:
		return lines

	if node.get("hidden") is not None or node.get("aria-hidden") == "true":
		return lines

	if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
		heading = _heading_to_markdown(node)
		if heading:
			lines.append(heading)
		return lines

	if name == "p":
		text = _render_children_inline(node)
		if text:
			lines.append(text)
		return lines

	if _is_list_tag(node):
		lines.extend(_list_to_markdown(node))
		return lines

	if name == "table":
		table_md = _table_to_markdown(node)
		if table_md:
			lines.extend(table_md.splitlines())
		return lines

	if name == "blockquote":
		lines.extend(_blockquote_to_markdown(node))
		return lines

	if name == "pre":
		lines.extend(_pre_to_markdown(node))
		return lines

	if name == "hr":
		lines.append("---")
		return lines

	if name == "img":
		image_md = _render_inline(node)
		if image_md:
			lines.append(image_md)
		return lines

	if name in BLOCK_CONTAINER_TAGS:
		for child in node.children:
			child_lines = _element_to_markdown_lines(child)
			if child_lines:
				lines.extend(child_lines)
		return lines

	for child in node.children:
		child_lines = _element_to_markdown_lines(child)
		if child_lines:
			lines.extend(child_lines)

	return lines


def _split_html_into_markdown_documents(path: str) -> List[Document]:
	"""按 HTML 的真实结构顺序，把 HTML 转成 Markdown 文档。"""
	with open(path, "r", encoding="utf-8", errors="ignore") as f:
		html = f.read()

	soup = BeautifulSoup(html, "html.parser")
	doc_title = _extract_document_title(soup)

	root = soup.body or soup
	markdown_lines: List[str] = []

	for child in root.children:
		markdown_lines.extend(_element_to_markdown_lines(child))

	markdown_lines = [_normalize_text(line) for line in markdown_lines if _normalize_text(line)]

	if not markdown_lines and doc_title:
		markdown_lines = [f"# {doc_title}"]
	elif doc_title and not any(line.startswith("#") for line in markdown_lines):
		markdown_lines.insert(0, f"# {doc_title}")

	markdown_content = _normalize_text("\n\n".join(markdown_lines))
	if not markdown_content:
		return []

	metadata = {
		"source": path,
		"content_type": "markdown",
		"title_path": doc_title or "ROOT",
		"document_title": doc_title or "",
		"format": "html",
	}

	return [Document(page_content=markdown_content, metadata=metadata)]


def load_html(path: str):
	"""给外部流程调用的统一入口，直接返回 Markdown 化后的文档。"""
	return _split_html_into_markdown_documents(path)


def structure_html(path: str):
	"""兼容入口：现在也只返回 Markdown 化后的文档。"""
	return load_html(path)


def unstructure_html(path: str):
	"""兼容入口：现在也只返回 Markdown 化后的文档。"""
	return load_html(path)


def auto_split_html(path: str):
	"""兼容入口：不在 loader 内切分，统一交给上层的 Markdown splitter。"""
	return load_html(path)


