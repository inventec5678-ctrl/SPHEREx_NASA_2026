"""The paper as an astronomy-journal PDF: the rendered paper HTML -> AASTeX 6.31 two-column LaTeX -> PDF (tectonic).

  python scripts/paper_tex.py            # both languages -> paper_tex/<lang>/paper.tex and
                                         # web/app/public/paper/static/pdfs/spherex_movers_aas_{zh,en}.pdf

Reads web/app/public/paper/paper.html and paper-en.html (run render_paper.py first). Inline SVG figures are
rasterised with headless Chromium (same drawing as the web page); WebP screenshots are converted to PNG.
The output keeps AASTeX's "Draft version" header: this is a hackathon technical report, not a journal paper.
"""
import os
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PAPER_TEX as OUT, PUBLIC, read_text, run, tectonic, write_text  # noqa: E402

PUB = PUBLIC / "paper"
TECTONIC = tectonic()
SVG_SCALE = 4                  # device pixels per CSS pixel when rasterising inline SVG figures
SVG_SETTLE_MS = 300            # let the page's fonts settle before the screenshot
LONG_CELL = 28                 # table columns with text longer than this wrap (tabularx X column)
LOG_TAIL = 3000                # characters of tectonic output shown on failure
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "line", "circle", "rect", "path", "polyline", "stop", "use"}


# ---- a tiny DOM -------------------------------------------------------------
class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    def cls(self):
        return self.attrs.get("class", "").split()

    def text(self):
        return "".join(k if isinstance(k, str) else k.text() for k in self.kids)

    def find_all(self, tag):
        for k in self.kids:
            if isinstance(k, Node):
                if k.tag == tag:
                    yield k
                yield from k.find_all(tag)


class Tree(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.root = Node("root", {}); self.cur = self.root
        self.feed(raw)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur); self.cur.kids.append(n)
        if tag == "svg":       # keep inline figures as raw markup
            n.start = self.getpos()
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


# ---- text -------------------------------------------------------------------
SYM = {"″": r"$''$", "′": r"$'$", "°": r"$^\circ$", "≥": r"$\ge$", "≤": r"$\le$", "σ": r"$\sigma$", "×": r"$\times$",
       "µ": r"$\mu$", "μ": r"$\mu$", "≈": r"$\approx$", "−": r"$-$", "α": r"$\alpha$", "ε": r"$\varepsilon$", "λ": r"$\lambda$",
       "β": r"$\beta$", "√": r"$\surd$", "±": r"$\pm$", "²": r"$^2$", "π": r"$\pi$", "δ": r"$\delta$", "⊕": r"$_\oplus$",
       "→": r"$\rightarrow$", "←": r"$\leftarrow$", "∼": r"$\sim$", "…": r"\ldots{}", "·": r"$\cdot$", "–": "--", "—": "---"}


# the live site (a Cloudflare quick tunnel changes address when restarted): SX_PUBLIC_URL overrides it
PUBLIC_URL = os.environ.get("SX_PUBLIC_URL", "https://leather-brief-determines-captured.trycloudflare.com")

def esc(s):
    s = s.replace("\\", "\x00")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    s = s.replace("\x00", r"\textbackslash{}")
    return "".join(SYM.get(ch, ch) for ch in s)


def inline(n):
    """Inline HTML -> LaTeX."""
    if isinstance(n, str):
        return esc(re.sub(r"\s+", " ", n))
    body = "".join(inline(k) for k in n.kids)
    t = n.tag
    if t == "em" or t == "i":
        return r"\emph{" + body + "}"
    if t in ("strong", "b"):
        return r"\textbf{" + body + "}"
    if t == "code":
        return r"\texttt{" + body + "}"
    if t == "sub":
        return r"\textsubscript{" + body + "}"
    if t == "sup":
        return r"\textsuperscript{" + body + "}"
    if t == "a":
        href = n.attrs.get("href", "")
        if href.startswith("http") and n.text().strip().startswith("http"):
            return r"\url{" + href.replace("%", r"\%").replace("#", r"\#") + "}"
        return body
    if t == "br":
        return r"\\"
    return body


# ---- figures ----------------------------------------------------------------
def raster_svgs(svgs, outdir):
    """Rasterise inline SVG figures with headless Chromium (the page's own drawing, with its fonts)."""
    from playwright.sync_api import sync_playwright
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(device_scale_factor=SVG_SCALE)
        pg.emulate_media(media="print")         # the paper's print theme: light background, dark ink
        css = (PUB / "paper.css").as_uri()
        for k, svg in enumerate(svgs):
            html = (f'<html><head><link rel="stylesheet" href="{css}"><style>body{{margin:0;background:#fff}}'
                    'figure{margin:0} svg{display:block;width:900px;height:auto}</style></head>'
                    f'<body class="project"><main><figure>{svg}</figure></main></body></html>')
            tmp = write_text(outdir / "_fig.html", html)
            pg.goto(tmp.as_uri()); pg.wait_for_timeout(SVG_SETTLE_MS)
            f = outdir / f"svgfig{k + 1}.png"
            pg.locator("svg").first.screenshot(path=str(f))
            paths.append(f.name)
        b.close()
        (outdir / "_fig.html").unlink(missing_ok=True)
    return paths


# ---- conversion -------------------------------------------------------------
class Conv:
    def __init__(self, tree, lang, outdir):
        self.t, self.lang, self.out = tree, lang, outdir
        self.svgs, self.body, self.sec, self.sub, self.appendix = [], [], 0, 0, False

    def svg_markup(self, node):
        """The raw <svg>...</svg> text of this node, from the source (inline figures appear in document order)."""
        return self.t.raw_svgs.pop(0)

    def figure(self, n):
        cap = next((k for k in n.find_all("figcaption")), None)
        caption = re.sub(r"^\s*(圖|Figure)\s*\d+[.．。:：]\s*", "", inline(cap)) if cap else ""
        img = next(n.find_all("img"), None)
        svg = next(n.find_all("svg"), None)
        if img is not None:
            src = PUB / img.attrs["src"]
            name = f"img_{src.stem}.png"
            Image.open(src).convert("RGB").save(self.out / name)
            env, width = "figure*", r"0.95\textwidth"
        elif svg is not None:
            self.svgs.append(self.svg_markup(svg))
            name = f"svgfig{len(self.svgs)}.png"
            env, width = "figure", r"\columnwidth"
        else:
            return ""
        return (f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width={width}]{{{name}}}\n"
                f"\\caption{{{caption}}}\n\\end{{{env}}}\n")

    def table(self, n, note):
        rows = []
        for tr in n.find_all("tr"):
            cells = [k for k in tr.kids if isinstance(k, Node) and k.tag in ("td", "th")]
            rows.append(([inline(c).strip() for c in cells], any(c.tag == "th" for c in cells)))
        if not rows:
            return ""
        ncol = max(len(r) for r, _ in rows)
        wide = ncol > 4 or sum(len(x) for r, _ in rows for x in r) / max(len(rows), 1) > 90
        env = "table*" if wide else "table"
        caption = re.sub(r"^\s*(表|Table)\s*\d+[.．。:：]\s*", "", note) if note else ""
        # columns with long text wrap (X), short ones stay natural width (l)
        longest = [max((len(r[k]) if k < len(r) else 0) for r, _ in rows) for k in range(ncol)]
        if max(longest) > LONG_CELL:
            spec = "".join("X" if L > LONG_CELL else "l" for L in longest)
            tab_open, tab_close = r"\begin{tabularx}{" + (r"\textwidth" if wide else r"\columnwidth") + "}{" + spec + "}", r"\end{tabularx}"
        else:
            tab_open, tab_close = r"\begin{tabular}{" + "l" * ncol + "}", r"\end{tabular}"
        lines = [f"\\begin{{{env}}}[t]", r"\centering", r"\footnotesize", f"\\caption{{{caption}}}" if caption else "",
                 tab_open, r"\hline\hline"]
        head_done = False
        for cells, is_head in rows:
            cells = cells + [""] * (ncol - len(cells))
            lines.append(" & ".join(cells) + r" \\")
            if is_head and not head_done:
                lines.append(r"\hline"); head_done = True
        lines += [r"\hline", tab_close, f"\\end{{{env}}}", ""]
        return "\n".join(lines)

    def heading_num(self, txt, level):
        m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s+(.*)$", txt)
        return (m.group(1), m.group(2)) if m else (None, txt)

    def block(self, n, nxt=None):
        if isinstance(n, str):
            return ""
        t, c = n.tag, n.cls()
        if t == "h2":
            hid = n.attrs.get("id", "")
            num, title = self.heading_num(n.text(), 2)
            if hid in ("abstract",):
                return ""
            if hid == "refs":
                return "%%REFS%%"
            if hid.startswith("app"):
                title = re.sub(r"^(附錄|Appendix)\s*[A-Z][.．]?\s*", "", title)
                letter = re.match(r"^\s*(?:附錄|Appendix)\s*([A-Z])", n.text())
                pre = "" if self.appendix else ("\\section*{" + ("附錄" if self.lang == "zh" else "Appendix") + "}\n")
                self.appendix = True
                return pre + f"\\subsection*{{{letter.group(1) + '. ' if letter else ''}{esc(title)}}}\n"
            if num is None:
                return f"\\section*{{{esc(title)}}}\n"
            self.sec += 1; self.sub = 0
            assert int(num) == self.sec, f"section numbering: HTML {num} vs LaTeX {self.sec}"
            return f"\\section{{{esc(title)}}}\n\\label{{sec:{hid}}}\n"
        if t == "h3":
            num, title = self.heading_num(n.text(), 3)
            if num:
                self.sub += 1
                assert num == f"{self.sec}.{self.sub}", f"subsection numbering: HTML {num} vs LaTeX {self.sec}.{self.sub}"
                return f"\\subsection{{{esc(title)}}}\n"
            return f"\\subsection*{{{esc(title)}}}\n"
        if t == "p":
            if "table-note" in c:
                return ""          # used as the caption of the table before it
            if "abstract" in c or "authors" in c:
                return ""
            return inline(n).strip() + "\n\n"
        if t == "ol" and "refs" in c:
            return ""              # becomes the bibliography
        if t in ("ul", "ol"):
            env = "itemize" if t == "ul" else "enumerate"
            items = [r"\item " + inline(li).strip() for li in n.kids if isinstance(li, Node) and li.tag == "li"]
            return f"\\begin{{{env}}}\n" + "\n".join(items) + f"\n\\end{{{env}}}\n\n"
        if t == "figure":
            return self.figure(n)
        if t == "table":
            note = inline(nxt).strip() if isinstance(nxt, Node) and "table-note" in nxt.cls() else ""
            return self.table(n, note)
        if t == "div" and "key-points" in c:
            return ""
        if t in ("div", "section", "main"):
            return self.blocks(n.kids)
        return ""

    def blocks(self, kids):
        els = [k for k in kids if isinstance(k, Node)]
        return "".join(self.block(k, els[i + 1] if i + 1 < len(els) else None) for i, k in enumerate(els))


def build(lang):
    src = PUB / ("paper.html" if lang == "zh" else "paper-en.html")
    raw = read_text(src)
    tree = Tree(raw)
    tree.raw_svgs = re.findall(r"<svg\b.*?</svg>", raw, flags=re.S)
    out = OUT / lang
    out.mkdir(parents=True, exist_ok=True)
    main = next(tree.root.find_all("main"))
    title = next(main.find_all("h1")).text().strip()
    abstract = next((p for p in main.find_all("p") if "abstract" in p.cls()), None)
    kp = next((d for d in main.find_all("div") if "key-points" in d.cls()), None)
    kp_items = [inline(li).strip() for li in kp.find_all("li")] if kp else []
    conv = Conv(tree, lang, out)
    body = conv.blocks(main.kids)
    # references: the last ordered list after the refs heading
    refs_ol = next((o for o in main.find_all("ol") if "refs" in o.cls()), None)
    refs = [inline(li).strip() for li in refs_ol.find_all("li")] if refs_ol else []
    # AAS-style reference list (unnumbered, hanging indent); the text cites by name and year, not by \cite
    bib = ("\\section*{" + ("參考文獻" if lang == "zh" else "References") + "}\n\\begin{list}{}{\\leftmargin=1.5em\\itemindent=-1.5em\\itemsep=2pt\\small}\n"
           + "\n".join("\\item " + r for r in refs) + "\n\\end{list}\n") if refs else ""
    body = body.replace("%%REFS%%", bib)
    figs = raster_svgs(conv.svgs, out) if conv.svgs else []
    zh = lang == "zh"
    cjk = (r"\usepackage{xeCJK}" "\n" r"\setCJKmainfont{Noto Serif CJK TC}[BoldFont={Noto Serif CJK TC Bold}]" "\n"
           r"\setCJKsansfont{Noto Sans CJK TC}" "\n" r"\setCJKmonofont{Noto Sans Mono CJK TC}" "\n"
           r"\xeCJKsetup{CJKspace=true}" "\n")         # loaded for both languages
    names = (r"\renewcommand{\figurename}{圖}\renewcommand{\tablename}{表}\renewcommand{\abstractname}{摘要}"
             r"\renewcommand{\refname}{參考文獻}\renewcommand{\appendixname}{附錄}" if zh else "")
    kp_head = "重點" if zh else "Key points"
    report = ("黑客松技術報告，未經同儕審查。網站與資料：" if zh else "Hackathon technical report, not peer reviewed. Website and data: ")
    affil = "NASA Space Apps Challenge 2026 · Planet X and SPHEREx"
    tex = rf"""% Generated by scripts/paper_tex.py from {src.name}; edit the HTML source (web/app/paper_src), not this file.
\documentclass[twocolumn]{{aastex631}}
{cjk}\usepackage{{graphicx}}
\usepackage{{tabularx}}
{names}
\shorttitle{{{"SPHEREx 影像中的移動天體" if zh else "Moving objects in SPHEREx images"}}}
\shortauthors{{SPHEREx Sky Change}}
\begin{{document}}
\title{{{esc(title)}}}
\author{{SPHEREx Sky Change {"團隊" if zh else "Team"}}}
\affiliation{{{affil}}}
\begin{{abstract}}
{inline(abstract).strip() if abstract else ""}

\medskip\noindent\textbf{{{kp_head}}}
\begin{{itemize}}\setlength{{\itemsep}}{{1pt}}
{chr(10).join(r"\item " + x for x in kp_items)}
\end{{itemize}}
\noindent{{\footnotesize {report}\url{{{PUBLIC_URL}}}}}
\end{{abstract}}
\keywords{{{"小行星 --- 海王星外天體 --- 天文影像處理 --- 卷積神經網路 --- 視差" if zh else "Asteroids --- Trans-Neptunian objects --- Astronomy image processing --- Convolutional neural networks --- Parallax"}}}


{body}
\end{{document}}
"""
    write_text(out / "paper.tex", tex)
    r = run([TECTONIC, "-X", "compile", "paper.tex"], cwd=out, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False)
    if r.returncode:
        print(r.stdout[-LOG_TAIL:], r.stderr[-LOG_TAIL:]); raise SystemExit(f"tectonic failed for {lang}")
    dst = PUB / "static/pdfs" / f"spherex_movers_aas_{lang}.pdf"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "paper.pdf", dst)
    print(lang, dst, f"{dst.stat().st_size // 1024} KB", f"{len(figs)} svg figures")


if __name__ == "__main__":
    for lang in (sys.argv[1:] or ["zh", "en"]):
        build(lang)
