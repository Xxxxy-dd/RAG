"""PDF loader to Markdown format.

专属格式深度解析，统一输出为 Markdown 文档，方便后续做统一切分。

改进点与设计决策：
- 优先按页与表格抽取文本
- 支持基于字体大小的标题识别、跨页页眉/页脚检测与过滤、多列排版检测与合并。
- 单独抽取表格并保留单元格语义，尽量将其转成 Markdown 表格，避免正文吞表格导致信息丢失。
- 在文本层缺失时，提供可选的 OCR 回退（依赖 `pdf2image` + `pytesseract`）。
- 提供可选更强的表格抽取（`camelot`），在复杂表格场景更可靠。

使用说明：优先使用 `load_pdf(path)` 作为统一入口，它会返回已经 Markdown 化的 `Document` 列表；
后续统一切分工作应交给上层的 Markdown splitter。
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Optional

import pdfplumber
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

try:
    import tiktoken
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None


try:
    import camelot
except Exception:
    camelot = None

try:
    from pdf2image import convert_from_path
    import pytesseract
except Exception:
    convert_from_path = None
    pytesseract = None


_TOKEN_ENCODER = None
_PAGE_NUMBER_RE = re.compile(r"^(第\s*\d+\s*页|\d+\s*/\s*\d+|page\s*\d+|\d+)$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^([\-\*•·]|\d+[\.)]|[一二三四五六七八九十]+[、\.)]|\([一二三四五六七八九十]+\))\s*")


def _normalize_text(text: str) -> str:
    """把空格、换行和多余空白整理干净，方便后面切分。"""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_text(text: str) -> bool:
    """判断一段文字是不是页码、模板词或者明显没意义的噪声。"""
    if not text:
        return True

    cleaned = _normalize_text(text).strip()
    if not cleaned:
        return True

    if _PAGE_NUMBER_RE.match(cleaned):
        return True

    if len(cleaned) <= 3 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned):
        return True

    return False


def _token_length(text: str) -> int:
    """粗略算一下 token 数，优先用 tiktoken，没有就用字符数近似一下。"""
    if not text:
        return 0

    if tiktoken is not None:
        try:
            global _TOKEN_ENCODER
            if _TOKEN_ENCODER is None:
                _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
            return len(_TOKEN_ENCODER.encode(text))
        except Exception:  # pragma: no cover - defensive fallback
            pass

    return max(1, len(text) // 2)


def _build_splitter():
    """创建一个基础切分器，负责把长文本拆成更适合检索的小块。"""
    return RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=150,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],
        length_function=_token_length,
    )


def _detect_content_type(text: str) -> str:
    """简单判断这一段内容更像标题、列表还是普通正文。"""
    cleaned = _normalize_text(text)
    if not cleaned:
        return "paragraph"

    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    bullet_lines = sum(1 for line in lines if _BULLET_RE.match(line))

    if len(cleaned) <= 60 and not cleaned.endswith(("。", "！", "？")):
        return "title"

    if bullet_lines >= max(2, len(lines) // 2):
        return "list"

    return "paragraph"


def _markdown_table_from_rows(rows: List[List[str]]) -> str:
    """把二维表格转成 Markdown 表格。"""
    normalized_rows = []
    for row in rows:
        cells = []
        for cell in row:
            cell_text = _normalize_text(cell or "").replace("\n", " ")
            cells.append(cell_text)
        if any(cells):
            normalized_rows.append(cells)

    if not normalized_rows:
        return ""

    header = normalized_rows[0]
    body_rows = normalized_rows[1:]
    header_line = "| " + " | ".join(header) + " |"
    separator_line = "|" + "|".join(["---"] * len(header)) + "|"
    body_lines = ["| " + " | ".join(row) + " |" for row in body_rows]
    return "\n".join([header_line, separator_line, *body_lines])


def _is_title_line(text: str) -> bool:
    """判断一行文字像不像标题，企业文档里常用来做章节入口。"""
    cleaned = _normalize_text(text)
    if not cleaned:
        return False

    if _is_noise_text(cleaned):
        return False

    if len(cleaned) <= 60 and not cleaned.endswith(("。", "！", "？")):
        return True

    if re.match(r"^[一二三四五六七八九十]+[、\.)]\s*\S+", cleaned):
        return True

    if re.match(r"^\d+(\.\d+)*[\.、]?\s+\S+", cleaned):
        return True

    return False


def _lines_from_text(text: str) -> List[str]:
    """把文本按行整理出来，后面会用来做标题和正文判断。"""
    lines = []
    for line in (text or "").split("\n"):
        cleaned = _normalize_text(line)
        if cleaned:
            lines.append(cleaned)
    return lines


def _extract_page_lines(page) -> List[str]:
    """把一页里的文字按行拿出来，方便后面做标题、正文和列表判断。

    仍然以文本层为主；更复杂的布局（多栏、字体大小）在专用函数里处理。
    """
    return _lines_from_text(page.extract_text() or "")


def _extract_page_lines_with_reader(page) -> List[str]:
    """当 pdfplumber 不可用时，用 pypdf 的页面文本做兜底。"""
    return _lines_from_text(page.extract_text() or "")


def _extract_tables_from_page(page, page_number: int, source: str) -> List[Document]:
    """把 PDF 页面里的表格单独抽出来，避免表格内容被正文吞掉。"""
    documents = []
    tables = page.extract_tables() or []

    for table_index, table in enumerate(tables, start=1):
        table_text = _markdown_table_from_rows(table)
        if not table_text:
            continue

        documents.append(
            Document(
                page_content=table_text,
                metadata={
                    "source": source,
                    "page_number": page_number,
                    "content_type": "table",
                    "table_index": table_index,
                    "title_path": f"Page {page_number}",
                },
            )
        )

    return documents


def _extract_tables_with_camelot(path: str) -> List[Document]:
    """如果安装了 camelot，则用它对整个 PDF 做更强的表格抽取（可选）。"""
    docs = []
    if camelot is None:
        return docs

    try:
        tables = camelot.read_pdf(path, pages="all")
        for ti, table in enumerate(tables):
            try:
                df = table.df
                page_no = int(table.page) if hasattr(table, "page") else None
                text = _markdown_table_from_rows(df.values.tolist())
                if text:
                    docs.append(Document(page_content=text, metadata={"source": path, "page_number": page_no or -1, "content_type": "table", "table_index": ti + 1}))
            except Exception:
                continue
    except Exception:
        return []

    return docs


def _extract_page_title(lines: List[str]) -> str:
    """从页面文本里找一个最像标题的短文本，方便后续检索回溯。

    该函数仅基于纯文本供回退使用；若要使用字体大小判断，请使用
    `_extract_page_title_from_page`（在 pdfplumber 上下文中）。
    """
    for line in lines[:5]:
        if _is_title_line(line):
            return line

    for line in lines[:3]:
        if line and len(line) <= 50 and not _is_noise_text(line):
            return line

    return ""


def _extract_page_title_from_page(page, lines: List[str]) -> str:
    """基于 pdfplumber 的字体大小和位置来识别最可能的标题行。

    优先选字体尺寸显著大于页面平均值的行，其次回退到纯文本策略。
    """
    try:
        chars = getattr(page, "chars", [])
        if chars:
            # 聚合同一 vertical band 的字符为行，统计行的平均字体大小
            line_map = defaultdict(list)
            for ch in chars:
                top_key = round(ch.get("top", 0) / 3) * 3
                line_map[top_key].append(ch)

            line_sizes = []
            line_texts = {}
            for k, chs in line_map.items():
                sizes = [c.get("size", 0) for c in chs if c.get("text", '').strip()]
                if not sizes:
                    continue
                avg_size = sum(sizes) / len(sizes)
                text = _normalize_text("".join([c.get("text", "") for c in sorted(chs, key=lambda x: x.get("x0", 0))]))
                if text:
                    line_sizes.append(avg_size)
                    line_texts[k] = (avg_size, text)

            if line_sizes:
                avg_page_size = sum(line_sizes) / len(line_sizes)
                # 找一个显著大于页面平均字体的候选（比如 > 1.15 倍）
                candidates = [(k, v) for k, v in line_texts.items() if v[0] > avg_page_size * 1.15 and len(v[1]) <= 120]
                if candidates:
                    # 选择最靠前（top 小）的候选
                    best = sorted(candidates, key=lambda x: x[0])[0][1][1]
                    if best and not _is_noise_text(best):
                        return best
    except Exception:
        pass

    # 回退到纯文本策略
    return _extract_page_title(lines)


def _extract_page_body(lines: List[str], title: str) -> str:
    """把一页里的正文、列表和说明文字拼起来，并尽量去掉标题本身。

    这是纯文本回退策略；对于基于布局的更精细分割，请使用
    `_extract_page_body_from_page` 并传入 pdfplumber 的 page 对象。
    """
    blocks = []

    for line in lines:
        if not line:
            continue

        if title and line == title:
            continue

        if _is_noise_text(line):
            continue

        if _BULLET_RE.match(line):
            blocks.append(line)
            continue

        # 同一页里把短行和前一行拼一下，减少碎片化。
        if blocks and _should_merge_small_chunk(line) and _should_merge_small_chunk(blocks[-1]):
            blocks[-1] = _normalize_text(blocks[-1] + "\n" + line)
            continue

        blocks.append(line)

    return _normalize_text("\n".join(blocks))


def _build_metadata(path: str, page_number: int, title: str, content_type: str, chunk_id: Optional[int] = None):
    """给每个块补上来源、页码、标题和内容类型，后面追踪会更清楚。"""
    metadata = {
        "source": path,
        "page_number": page_number,
        "page_title": title or f"Page {page_number}",
        "title_path": title or f"Page {page_number}",
        "content_type": content_type,
    }
    if chunk_id is not None:
        metadata["chunk_id"] = chunk_id
    return metadata


def _should_merge_small_chunk(text: str) -> bool:
    """判断这一小段是不是太短了，太短就尽量合并一下。"""
    token_count = _token_length(text)
    return token_count < 80 or len(text) < 120


def _merge_adjacent_small_chunks(chunks: List[Document]) -> List[Document]:
    """把相邻的、太短的、而且同一页的小块拼起来，减少碎片化。"""
    merged = []

    for chunk in chunks:
        chunk.page_content = _normalize_text(chunk.page_content)
        chunk.metadata = chunk.metadata or {}

        if not merged:
            merged.append(chunk)
            continue

        prev = merged[-1]
        same_page = prev.metadata.get("page_number") == chunk.metadata.get("page_number")
        same_type = prev.metadata.get("content_type") == chunk.metadata.get("content_type")

        if same_page and same_type and _should_merge_small_chunk(chunk.page_content) and _token_length(prev.page_content) < 500:
            prev.page_content = _normalize_text(prev.page_content + "\n" + chunk.page_content)
            prev.metadata["merged_chunk_count"] = prev.metadata.get("merged_chunk_count", 1) + 1
            continue

        merged.append(chunk)

    return merged


def _page_text_is_sparse(lines: List[str]) -> bool:
    """判断这一页是不是文本太少，方便后面给出更保守的切分结果。"""
    content_lines = [line for line in lines if not _is_noise_text(line)]
    total_len = sum(len(line) for line in content_lines)
    return total_len < 80 or len(content_lines) <= 1


def _load_pages_with_plumber(path: str) -> List[Document]:
    """先用 pdfplumber 把每一页、表格和正文尽量都抽出来，并转成 Markdown。"""
    documents = []
    # 先尝试用 camelot 做全文表格提取（如果可用），作为补充
    camelot_tables = _extract_tables_with_camelot(path)

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)

        # 检测跨页重复的页眉/页脚文本，便于过滤
        header_footer_candidates = Counter()
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()][:3]
            footer = [l.strip() for l in text.splitlines() if l.strip()][-3:]
            for l in lines + footer:
                if l:
                    header_footer_candidates[l] += 1

        header_footer_set = set([s for s, c in header_footer_candidates.items() if c >= max(2, int(page_count * 0.6))])

        for page_number, page in enumerate(pdf.pages, start=1):
            # 先尝试用字体大小来识别标题（更稳健）
            lines = _extract_page_lines(page)
            title = _extract_page_title_from_page(page, lines)

            # 使用基于布局的正文抽取（会尝试多列检测与合并）
            body = _extract_page_body_from_page(page, lines, title, header_footer_set)
            page_heading = title or f"Page {page_number}"
            page_parts = [f"## {page_heading}"]
            if body:
                page_parts.append(body)
            page_text = _normalize_text("\n\n".join(page_parts).strip())

            # 如果没有正文但 camelot 在该页识别到表格，则优先保留表格
            page_tables = [t for t in camelot_tables if t.metadata.get("page_number") == page_number] if camelot_tables else []
            if not page_text and (page.extract_tables() or page_tables):
                documents.extend(_extract_tables_from_page(page, page_number, path))
                if page_tables:
                    documents.extend(page_tables)
                continue

            if not page_text:
                # 如果文本层为空且可用 OCR，则尝试 OCR
                if convert_from_path is not None and pytesseract is not None:
                    try:
                        pil_pages = convert_from_path(path, first_page=page_number, last_page=page_number, dpi=150)
                        if pil_pages:
                            ocr_text = pytesseract.image_to_string(pil_pages[0], lang="chi_sim+eng")
                            ocr_body = _normalize_text(ocr_text)
                            if ocr_body:
                                page_text = _normalize_text("\n\n".join([f"## {page_heading}", ocr_body]).strip())
                    except Exception:
                        pass

            if page_text:
                metadata = _build_metadata(path, page_number, title, "page_md")
                metadata["page_is_sparse"] = _page_text_is_sparse(lines)
                documents.append(Document(page_content=page_text, metadata=metadata))

            # 额外尝试把 pdfplumber 提取的表格也加入
            documents.extend(_extract_tables_from_page(page, page_number, path))

    # 把 camelot 的表格（若有）也加入（避免重复按需去重）
    for tdoc in camelot_tables:
        documents.append(tdoc)

    return documents

def _extract_page_body_from_page(page, lines: List[str], title: str, header_footer_set: set) -> str:
    """基于 layout 的正文抽取：支持页眉页脚过滤、多列检测与合并。"""
    # 先过滤跨页重复的页眉页脚
    filtered_lines = [l for l in lines if l not in header_footer_set]

    # 如果 page supports words with bbox，则做简单的多列检测
    try:
        words = page.extract_words(use_text_flow=True) or []
        if words:
            page_width = getattr(page, "width", None)
            # 计算每个单词中心点 x
            centers = [((float(w.get("x0", 0)) + float(w.get("x1", 0))) / 2.0) for w in words]
            # 若页面宽度可用，寻找显著的横向空隙，作为列分割
            if page_width and centers:
                sorted_centers = sorted(centers)
                gaps = [(sorted_centers[i+1] - sorted_centers[i]) for i in range(len(sorted_centers)-1)]
                if gaps:
                    max_gap = max(gaps)
                    if max_gap > (page_width * 0.25):
                        # 找到间隙位置，按 x 将 words 分成两列
                        gap_index = gaps.index(max_gap)
                        split_x = (sorted_centers[gap_index] + sorted_centers[gap_index+1]) / 2.0
                        left_words = [w for w in words if ((float(w.get("x0",0))+float(w.get("x1",0)))/2.0) <= split_x]
                        right_words = [w for w in words if ((float(w.get("x0",0))+float(w.get("x1",0)))/2.0) > split_x]

                        def words_to_text(ws):
                            # 按 top、x0 排序
                            ws_sorted = sorted(ws, key=lambda x: (float(x.get("top",0)), float(x.get("x0",0))))
                            lines_local = []
                            cur_top = None
                            cur_words = []
                            for w in ws_sorted:
                                t = round(float(w.get("top",0))/3)*3
                                if cur_top is None or abs(t-cur_top) <= 3:
                                    cur_top = t
                                    cur_words.append(w.get("text", ""))
                                else:
                                    lines_local.append(_normalize_text(" ".join(cur_words)))
                                    cur_top = t
                                    cur_words = [w.get("text", "")]
                            if cur_words:
                                lines_local.append(_normalize_text(" ".join(cur_words)))
                            return lines_local

                        left_text = "\n".join(words_to_text(left_words))
                        right_text = "\n".join(words_to_text(right_words))
                        # 按列顺序合并（左列先）
                        combined = _normalize_text("\n".join([left_text, right_text]))
                        # 去掉标题重复
                        if title and combined.startswith(title):
                            combined = combined[len(title):].strip()
                        return combined
    except Exception:
        pass

    # 若未触发多列拆分，回退到简单合并逻辑并过滤页眉页脚
    blocks = []
    for line in filtered_lines:
        if not line:
            continue
        if title and line == title:
            continue
        if _is_noise_text(line):
            continue
        if _BULLET_RE.match(line):
            blocks.append(line)
            continue
        if blocks and _should_merge_small_chunk(line) and _should_merge_small_chunk(blocks[-1]):
            blocks[-1] = _normalize_text(blocks[-1] + "\n" + line)
            continue
        blocks.append(line)

    return _normalize_text("\n".join(blocks))


def _load_pages_with_reader(path: str) -> List[Document]:
    """当 pdfplumber 不稳定时，用 pypdf 至少把页面文字保住，并转成 Markdown。"""
    documents = []
    reader = PdfReader(path)

    for page_number, page in enumerate(reader.pages, start=1):
        lines = _extract_page_lines_with_reader(page)
        title = _extract_page_title(lines)
        body = _extract_page_body(lines, title)
        page_heading = title or f"Page {page_number}"
        page_parts = [f"## {page_heading}"]
        if body:
            page_parts.append(body)
        page_text = _normalize_text("\n\n".join(page_parts).strip())
        if not page_text:
            continue

        metadata = _build_metadata(path, page_number, title, "page_md")
        metadata["page_is_sparse"] = _page_text_is_sparse(lines)
        documents.append(Document(page_content=page_text, metadata=metadata))

    return documents


def is_structured_pdf(path: str) -> bool:
    """看看这个 PDF 有没有比较完整的标题页/正文页结构。"""
    try:
        with pdfplumber.open(path) as pdf:
            structured_page_count = 0

            for page in pdf.pages:
                lines = _extract_page_lines(page)
                title = _extract_page_title(lines)
                body = _extract_page_body(lines, title)

                if title and body:
                    structured_page_count += 1

                if structured_page_count >= 2:
                    return True
    except Exception:
        reader = PdfReader(path)
        structured_page_count = 0

        for page in reader.pages:
            lines = _extract_page_lines_with_reader(page)
            title = _extract_page_title(lines)
            body = _extract_page_body(lines, title)

            if title and body:
                structured_page_count += 1

            if structured_page_count >= 2:
                return True

    return False


def _load_pages(path: str) -> List[Document]:
    """把 PDF 每一页都变成一个基础文档对象，后面再做二次切分。"""
    try:
        return _load_pages_with_plumber(path)
    except Exception:
        # 如果 pdfplumber 解析失败，就用 pypdf 做一个文字兜底。
        return _load_pages_with_reader(path)


def unstructure_pdf(path: str):
    """没有明显结构时，直接返回每一页已经 Markdown 化的内容。"""
    return _load_pages(path)


def structure_pdf(path: str):
    """兼容入口：现在也只返回 Markdown 化后的页面文档。"""
    return load_pdf(path)


def auto_split_pdf(path: str):
    """兼容入口：不在 loader 内切分，统一交给上层的 Markdown splitter。"""
    return load_pdf(path)


def load_pdf(path: str):
    """给外部流程调用的统一入口，直接返回 Markdown 化后的页面文档。"""
    return _load_pages(path)


