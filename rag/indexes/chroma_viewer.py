from __future__ import annotations

import html
import os
import webbrowser
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import chromadb


BASE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = BASE_DIR / "chroma_db"
DEFAULT_COLLECTION = "document_indexing"
DEFAULT_LIMIT = 20
DEFAULT_PORT = 8765


def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _truncate(text: object, limit: int = 320) -> str:
    content = _to_text(text)
    if len(content) <= limit:
        return content
    return content[: limit - 1] + "…"


def _format_metadata(metadata: object) -> str:
    if metadata is None:
        return "{}"
    if isinstance(metadata, dict):
        parts = [f"{html.escape(str(key))}: {html.escape(_truncate(value, 120))}" for key, value in metadata.items()]
        return "<br>".join(parts) if parts else "{}"
    return html.escape(_truncate(metadata, 200))


def _format_chunk_info(metadata: object) -> str:
  if not isinstance(metadata, dict):
    return "<span class='muted'>无</span>"

  parts: list[str] = []

  chunk_id = metadata.get("chunk_id")
  if chunk_id is not None:
    parts.append(f"<span class='pill'>chunk_id: {html.escape(_truncate(chunk_id, 32))}</span>")

  merged_chunk_count = metadata.get("merged_chunk_count")
  if merged_chunk_count is not None:
    parts.append(f"<span class='pill'>merged: {html.escape(_truncate(merged_chunk_count, 32))}</span>")

  content_type = metadata.get("content_type")
  if content_type:
    parts.append(f"<span class='pill'>type: {html.escape(_truncate(content_type, 32))}</span>")

  title_path = metadata.get("title_path")
  if title_path:
    parts.append(f"<div class='chunk-detail'>title_path: {html.escape(_truncate(title_path, 140))}</div>")

  source = metadata.get("source")
  if source:
    parts.append(f"<div class='chunk-detail'>source: {html.escape(_truncate(source, 180))}</div>")

  return "<div class='chunk-info'>" + "".join(parts) + "</div>" if parts else "<span class='muted'>无</span>"


def _safe_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
        return max(1, min(parsed, 500))
    except ValueError:
        return default


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def _list_collection_names(client: chromadb.PersistentClient) -> list[str]:
    try:
        return [collection.name for collection in client.list_collections()]
    except Exception:
        return []


def _get_collection(client: chromadb.PersistentClient, collection_name: str):
    return client.get_collection(name=collection_name)


def _load_rows(collection, limit: int, keyword: str) -> list[dict[str, object]]:
    data = collection.get(include=["documents", "metadatas"], limit=limit)
    ids = data.get("ids") or []
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    rows: list[dict[str, object]] = []
    keyword_lower = keyword.strip().lower()

    for index, item_id in enumerate(ids):
        document = documents[index] if index < len(documents) else ""
        metadata = metadatas[index] if index < len(metadatas) else {}
        searchable = f"{item_id}\n{_to_text(document)}\n{metadata}".lower()
        if keyword_lower and keyword_lower not in searchable:
            continue

        rows.append(
            {
                "id": item_id,
                "document": _to_text(document),
                "metadata": metadata,
            }
        )

    return rows


def _escape_attr(value: str) -> str:
    return html.escape(value, quote=True)


def _render_page(
    collection_names: Iterable[str],
    selected_collection: str,
    collection_count: int,
    limit: int,
    keyword: str,
    rows: list[dict[str, object]],
    error_message: str | None = None,
) -> str:
    collection_options = []
    seen_selected = False
    for name in collection_names:
        escaped = html.escape(name)
        selected = name == selected_collection
        if selected:
            seen_selected = True
        collection_options.append(
            f'<option value="{_escape_attr(name)}"{" selected" if selected else ""}>{escaped}</option>'
        )

    if not seen_selected and selected_collection:
        collection_options.insert(
            0,
            f'<option value="{_escape_attr(selected_collection)}" selected>{html.escape(selected_collection)} (当前)</option>',
        )

    rows_html = []
    for row in rows:
        rows_html.append(
            "<tr>"
            f"<td class='mono'>{html.escape(_truncate(row['id'], 100))}</td>"
        f"<td class='chunk'>{_format_chunk_info(row['metadata'])}</td>"
            f"<td class='doc'>{html.escape(_truncate(row['document'], 900)).replace(chr(10), '<br>')}</td>"
            f"<td class='meta'>{_format_metadata(row['metadata'])}</td>"
            "</tr>"
        )

    if not rows_html:
        rows_html.append(
        "<tr><td colspan='4' class='empty'>没有匹配到记录，或者集合为空。</td></tr>"
        )

    notice_html = ""
    if error_message:
        notice_html = f"<div class='notice error'>{html.escape(error_message)}</div>"

    query_string = urlencode({"collection": selected_collection, "limit": limit, "q": keyword})

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Chroma 数据库查看器</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --panel: rgba(255, 255, 255, 0.92);
      --text: #132238;
      --muted: #667085;
      --line: #d8e1ee;
      --accent: #0f6fff;
      --accent-soft: rgba(15, 111, 255, 0.12);
      --shadow: 0 24px 60px rgba(19, 34, 56, 0.12);
      --error: #b42318;
      --error-bg: #fff1f0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(15, 111, 255, 0.16), transparent 28%),
        radial-gradient(circle at 90% 10%, rgba(54, 179, 126, 0.16), transparent 22%),
        linear-gradient(180deg, #f9fbff 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 18px 40px; }}
    .hero {{
      display: grid;
      gap: 14px;
      grid-template-columns: 1.8fr 1fr;
      align-items: end;
      margin-bottom: 18px;
    }}
    .title {{ font-size: 32px; margin: 0; letter-spacing: -0.03em; }}
    .subtitle {{ margin: 6px 0 0; color: var(--muted); line-height: 1.6; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid rgba(216, 225, 238, 0.85);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .stat {{ padding: 16px 18px; }}
    .stat .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; }}
    .stat .value {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
    .panel {{ padding: 18px; margin-bottom: 16px; }}
    form {{ display: grid; grid-template-columns: 1.4fr 0.7fr 0.9fr auto; gap: 12px; align-items: end; }}
    label {{ display: grid; gap: 7px; font-size: 13px; color: var(--muted); }}
    input, select, button {{
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      padding: 12px 14px;
      font-size: 14px;
      color: var(--text);
    }}
    input:focus, select:focus {{ outline: 2px solid var(--accent-soft); border-color: var(--accent); }}
    button {{
      cursor: pointer;
      border-color: var(--accent);
      background: linear-gradient(180deg, #2d82ff 0%, #0f6fff 100%);
      color: #fff;
      font-weight: 600;
      padding-inline: 18px;
      box-shadow: 0 12px 24px rgba(15, 111, 255, 0.22);
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill {{
      background: var(--accent-soft);
      color: #0b57d0;
      border-radius: 999px;
      padding: 6px 10px;
    }}
    .notice {{ margin-top: 14px; padding: 12px 14px; border-radius: 12px; }}
    .notice.error {{ background: var(--error-bg); color: var(--error); border: 1px solid rgba(180, 35, 24, 0.18); }}
    .table-wrap {{ overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
    thead th {{
      text-align: left;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(244, 247, 251, 0.92);
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tbody td {{
      vertical-align: top;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      line-height: 1.6;
      font-size: 14px;
    }}
    tbody tr:hover {{ background: rgba(15, 111, 255, 0.03); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 12px; }}
    .doc {{ white-space: pre-wrap; word-break: break-word; width: 36%; }}
    .chunk {{ white-space: normal; color: #344054; width: 22%; }}
    .meta {{ white-space: normal; color: #344054; width: 22%; }}
    .chunk-info {{ display: grid; gap: 8px; }}
    .chunk-detail {{ font-size: 12px; color: #475467; line-height: 1.5; word-break: break-word; }}
    .empty {{ text-align: center; color: var(--muted); padding: 34px 16px; }}
    .muted {{ color: var(--muted); }}
    .footer {{ color: var(--muted); font-size: 12px; margin-top: 14px; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }}
    .link {{
      color: var(--accent);
      text-decoration: none;
      border: 1px solid rgba(15, 111, 255, 0.18);
      background: rgba(15, 111, 255, 0.07);
      border-radius: 999px;
      padding: 7px 12px;
      display: inline-flex;
      align-items: center;
    }}
    @media (max-width: 980px) {{
      .hero, form {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div>
        <h1 class="title">Chroma 数据库查看器</h1>
        <p class="subtitle">快速查看当前项目下的 Chroma 持久化库。支持切换集合、调整预览数量，并按关键词过滤记录。</p>
        <div class="toolbar">
          <a class="link" href="/">刷新首页</a>
          <a class="link" href="/?{query_string}">保持当前条件刷新</a>
        </div>
      </div>
      <div class="stats">
        <div class="card stat">
          <div class="label">集合数量</div>
          <div class="value">{len(list(collection_names))}</div>
        </div>
        <div class="card stat">
          <div class="label">当前集合条数</div>
          <div class="value">{collection_count}</div>
        </div>
      </div>
    </section>

    <section class="card panel">
      <form method="get">
        <label>
          集合名称
          <select name="collection">{''.join(collection_options)}</select>
        </label>
        <label>
          预览条数
          <input name="limit" type="number" min="1" max="500" value="{limit}" />
        </label>
        <label>
          关键词过滤
          <input name="q" type="text" placeholder="输入文档片段、id 或元数据关键词" value="{html.escape(keyword)}" />
        </label>
        <button type="submit">查看</button>
      </form>
      <div class="meta-row">
        <span class="pill">数据库路径: {html.escape(str(CHROMA_DIR))}</span>
        <span class="pill">当前集合: {html.escape(selected_collection)}</span>
        <span class="pill">预览上限: {limit}</span>
      </div>
      {notice_html}
    </section>

    <section class="card table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width: 20%;">ID</th>
            <th style="width: 22%;">Chunk Info</th>
            <th style="width: 36%;">Document</th>
            <th style="width: 22%;">Metadata</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </section>

    <div class="footer">提示：这个页面是只读查看器，不会修改 Chroma 数据库。</div>
  </div>
</body>
</html>"""


class ChromaViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/", ""}:
            self.send_error(404, "Not Found")
            return

        params = parse_qs(parsed.query)
        requested_collection = params.get("collection", [DEFAULT_COLLECTION])[0]
        keyword = params.get("q", [""])[0]
        limit = _safe_int(params.get("limit", [str(DEFAULT_LIMIT)])[0], DEFAULT_LIMIT)

        try:
            client = _get_client()
            collection_names = _list_collection_names(client)
            if requested_collection not in collection_names and collection_names:
                requested_collection = collection_names[0]

            collection = _get_collection(client, requested_collection)
            collection_count = collection.count()
            rows = _load_rows(collection, limit, keyword)
            page = _render_page(
                collection_names=collection_names,
                selected_collection=requested_collection,
                collection_count=collection_count,
                limit=limit,
                keyword=keyword,
                rows=rows,
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
        except Exception as exc:
            page = _render_page(
                collection_names=[],
                selected_collection=requested_collection,
                collection_count=0,
                limit=limit,
                keyword=keyword,
                rows=[],
                error_message=str(exc),
            )
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    if not CHROMA_DIR.exists():
        raise FileNotFoundError(f"未找到 Chroma 目录: {CHROMA_DIR}")

    port = int(os.getenv("CHROMA_VIEWER_PORT", str(DEFAULT_PORT)))
    address = ("127.0.0.1", port)
    url = f"http://{address[0]}:{address[1]}/"
    print(f"Chroma viewer running at {url}")
    webbrowser.open(url)

    server = ThreadingHTTPServer(address, ChromaViewerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()