"""
Build a properly structured PDF from IMPLEMENTATION_PLAN.md.

Uses Chromium print-to-PDF (via Playwright) so tables, headings, and
ASCII diagrams keep real page layout — unlike xhtml2pdf.

  pip install markdown playwright
  playwright install chromium
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT_MD = HERE / "IMPLEMENTATION_PLAN.md"
OUTPUT_PDF = HERE / "IMPLEMENTATION_PLAN.pdf"
OUTPUT_HTML = HERE / "IMPLEMENTATION_PLAN.html"

CSS = """
:root {
  --ink: #1a1a1a;
  --muted: #555;
  --blue: #1e40af;
  --blue-mid: #2563eb;
  --line: #e5e7eb;
  --soft: #f8fafc;
}

* { box-sizing: border-box; }

@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
}

body {
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: var(--ink);
  margin: 0;
  padding: 0;
  max-width: 100%;
}

/* Cover / title block */
.doc-header {
  border-bottom: 3px solid var(--blue-mid);
  padding-bottom: 14px;
  margin-bottom: 22px;
}
.doc-header h1 {
  font-size: 20pt;
  line-height: 1.25;
  color: #0f172a;
  margin: 0 0 4px 0;
  border: none;
  padding: 0;
}
.doc-header .subtitle {
  font-size: 14pt;
  color: var(--blue);
  font-weight: 600;
  margin: 0 0 12px 0;
}
.meta {
  font-size: 9pt;
  color: var(--muted);
  line-height: 1.5;
}
.meta p { margin: 2px 0; }

h1 {
  font-size: 16pt;
  color: #0f172a;
  border-bottom: 2px solid var(--blue-mid);
  padding-bottom: 6px;
  margin: 28px 0 12px;
  page-break-after: avoid;
}
h2 {
  font-size: 13pt;
  color: var(--blue);
  margin: 26px 0 10px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
  page-break-after: avoid;
}
h3 {
  font-size: 11.5pt;
  color: #1d4ed8;
  margin: 18px 0 8px;
  page-break-after: avoid;
}
h4 {
  font-size: 10.5pt;
  color: #334155;
  margin: 14px 0 6px;
  page-break-after: avoid;
}

p { margin: 0 0 10px; }

ul, ol {
  margin: 0 0 12px;
  padding-left: 22px;
}
li { margin-bottom: 4px; }
li > ul, li > ol { margin-top: 4px; margin-bottom: 4px; }

strong { color: #0f172a; }

a { color: var(--blue-mid); text-decoration: none; }

hr {
  border: none;
  border-top: 1px solid var(--line);
  margin: 20px 0;
}

blockquote {
  margin: 12px 0;
  padding: 10px 14px;
  border-left: 4px solid var(--blue-mid);
  background: var(--soft);
  color: #334155;
  font-style: italic;
}

/* Tables — keep readable structure */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0 16px;
  font-size: 9pt;
  line-height: 1.4;
  page-break-inside: auto;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; page-break-after: auto; }
th {
  background: var(--blue);
  color: #fff;
  text-align: left;
  padding: 7px 8px;
  font-weight: 600;
  vertical-align: top;
}
td {
  border: 1px solid #d1d5db;
  padding: 6px 8px;
  vertical-align: top;
}
tbody tr:nth-child(even) td { background: #f9fafb; }

/* Code / ASCII diagrams */
pre {
  background: #0f172a;
  color: #e2e8f0;
  padding: 12px 14px;
  border-radius: 6px;
  font-family: Consolas, "Courier New", monospace;
  font-size: 7.5pt;
  line-height: 1.35;
  white-space: pre;
  overflow-x: auto;
  margin: 10px 0 16px;
  page-break-inside: avoid;
}
code {
  font-family: Consolas, "Courier New", monospace;
  font-size: 9pt;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
  color: #0f172a;
}
pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: inherit;
}

/* Phase cards (definition-style tables from markdown) */
.phase {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 10px 0 16px;
  background: var(--soft);
  page-break-inside: avoid;
}

.footer-note {
  margin-top: 28px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  font-size: 9pt;
  color: var(--muted);
  font-style: italic;
}

@media print {
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  a { color: inherit; text-decoration: none; }
  h2, h3 { break-after: avoid; }
  table, pre, blockquote { break-inside: avoid; }
}
"""


def build_html(md_text: str) -> str:
import markdown

    body = markdown.markdown(
        md_text,
    extensions=[
        "tables",
        "fenced_code",
            "sane_lists",
            "smarty",
        "toc",
        ],
        extension_configs={
            "toc": {"permalink": False},
        },
    )

    # Split first two H1s into a cover header for cleaner structure
    # markdown produces: <h1>BridgeEDI...</h1>\n<h1>Implementation Plan</h1>...
    cover = ""
    rest = body
    import re

    h1s = list(re.finditer(r"<h1>(.*?)</h1>", body, flags=re.DOTALL))
    if len(h1s) >= 2:
        title = h1s[0].group(1).strip()
        subtitle = h1s[1].group(1).strip()
        # Remove the first two h1 tags from body
        rest = body
        for m in reversed(h1s[:2]):
            rest = rest[: m.start()] + rest[m.end() :]
        rest = rest.lstrip()

        # Pull leading meta paragraph block (bold lines) into cover if present
        meta_match = re.match(
            r"((?:<p><strong>.*?</strong>.*?</p>\s*)+)",
            rest,
            flags=re.DOTALL,
        )
        meta_html = ""
        if meta_match:
            meta_html = f'<div class="meta">{meta_match.group(1)}</div>'
            rest = rest[meta_match.end() :]
            # drop following <hr> if present
            rest = re.sub(r"^\s*<hr\s*/?>\s*", "", rest, count=1)

        cover = f"""
        <header class="doc-header">
          <h1>{title}</h1>
          <p class="subtitle">{subtitle}</p>
          {meta_html}
        </header>
        """
    else:
        cover = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BridgeEDI — Implementation Plan</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{rest}
<div class="footer-note">
Document: IMPLEMENTATION_PLAN.md · Platform: BridgeEDI / Zodiac · Planning only — no code changes
</div>
</body>
</html>"""


def write_pdf_with_playwright(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    file_url = html_path.resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(file_url, wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={
                "top": "16mm",
                "bottom": "18mm",
                "left": "14mm",
                "right": "14mm",
            },
            display_header_footer=True,
            header_template=(
                '<div style="font-size:8px; width:100%; padding:0 14mm; '
                'color:#64748b; font-family:Segoe UI,sans-serif;">'
                '<span>BridgeEDI — Multi-Country Adapter &amp; Customer Workspace</span>'
                "</div>"
            ),
            footer_template=(
                '<div style="font-size:8px; width:100%; padding:0 14mm; '
                'color:#64748b; font-family:Segoe UI,sans-serif; '
                'display:flex; justify-content:space-between;">'
                "<span>Implementation Plan (pre-development)</span>"
                '<span>Page <span class="pageNumber"></span> / '
                '<span class="totalPages"></span></span>'
                "</div>"
            ),
        )
        browser.close()


def main() -> None:
    if not INPUT_MD.exists():
        print(f"Not found: {INPUT_MD}")
        sys.exit(1)

    try:
        import markdown  # noqa: F401
    except ImportError:
        print(f"Install: {sys.executable} -m pip install markdown")
        sys.exit(1)

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print(f"Install: {sys.executable} -m pip install playwright")
        print("Then:     playwright install chromium")
        sys.exit(1)

    md_text = INPUT_MD.read_text(encoding="utf-8")
    html = build_html(md_text)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    write_pdf_with_playwright(OUTPUT_HTML, OUTPUT_PDF)

    # Keep HTML for inspection; optional to delete — leave it for regenerations
print("=" * 50)
    print("PDF built with Chromium (structured layout)")
print(f"Input : {INPUT_MD}")
    print(f"HTML  : {OUTPUT_HTML}")
print(f"Output: {OUTPUT_PDF}")
print("=" * 50)


if __name__ == "__main__":
    main()
