"""
Convert BridgeEDI architecture proposal Markdown → PDF (no Pandoc required).
Uses: markdown + xhtml2pdf
  pip install markdown xhtml2pdf
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT_MD = ROOT / "zodiac" / "BridgeEDI_Integration_Architecture_Proposal.md"
OUTPUT_PDF = ROOT / "zodiac" / "BridgeEDI_Integration_Architecture_Proposal.pdf"

CSS = """
@page { size: A4; margin: 1.8cm; }
body {
  font-family: Helvetica, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
  color: #1a1a1a;
}
h1 { font-size: 18pt; color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }
h2 { font-size: 14pt; color: #1e3a8a; margin-top: 22px; }
h3 { font-size: 12pt; color: #1e40af; }
table { border-collapse: collapse; width: 100%; margin: 10px 0 16px; font-size: 9.5pt; }
th, td { border: 1px solid #cbd5e1; padding: 6px 8px; vertical-align: top; }
th { background: #eff6ff; text-align: left; }
code, pre {
  font-family: Consolas, monospace;
  font-size: 8.5pt;
  background: #f8fafc;
}
pre {
  border: 1px solid #e2e8f0;
  padding: 10px;
  white-space: pre-wrap;
  word-wrap: break-word;
}
hr { border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }
a { color: #2563eb; }
blockquote {
  border-left: 3px solid #2563eb;
  margin-left: 0;
  padding-left: 12px;
  color: #334155;
}
"""


def ensure_deps():
    missing = []
    try:
        import markdown  # noqa: F401
    except ImportError:
        missing.append("markdown")
    try:
        from xhtml2pdf import pisa  # noqa: F401
    except ImportError:
        missing.append("xhtml2pdf")
    if missing:
        print("Missing packages:", ", ".join(missing))
        print("Install with:")
        print(f"  {sys.executable} -m pip install markdown xhtml2pdf")
        sys.exit(1)


def md_to_html(md_text: str) -> str:
    import markdown

    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>BridgeEDI Integration Architecture Proposal</title>
  <style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


def html_to_pdf(html: str, out_path: Path) -> None:
    from xhtml2pdf import pisa

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as pdf_file:
        result = pisa.CreatePDF(html, dest=pdf_file, encoding="utf-8")
    if result.err:
        raise RuntimeError("PDF generation reported errors")


def main() -> None:
    ensure_deps()
    if not INPUT_MD.exists():
        print(f"Markdown file not found: {INPUT_MD}")
        sys.exit(1)

    md_text = INPUT_MD.read_text(encoding="utf-8")
    html = md_to_html(md_text)
    html_to_pdf(html, OUTPUT_PDF)
    print(f"PDF created successfully:\n{OUTPUT_PDF}")


if __name__ == "__main__":
    main()
