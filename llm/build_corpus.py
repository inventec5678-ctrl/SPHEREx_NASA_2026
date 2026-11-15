"""papers.json -> data/chunks.jsonl for the RAG library.

Copyright rule: full text only for Creative Commons papers (license URL contains creativecommons.org); every
other paper contributes its title + abstract only. Each chunk keeps its citation details for the source list.

  python llm/build_corpus.py
"""
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
API = "http://export.arxiv.org/api/query?id_list={ids}&max_results=100"
PDF = "https://arxiv.org/pdf/{id}"
NS = {"a": "http://www.w3.org/2005/Atom"}
CHUNK_WORDS = 220
OVERLAP_WORDS = 40
UA = {"User-Agent": "spherex-sky-change-rag/1.0"}
PAUSE_S = 3.0                       # arXiv asks for a pause between requests


def _fetch(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def abstracts(ids):
    out = {}
    for i in range(0, len(ids), 40):
        root = ET.fromstring(_fetch(API.format(ids=",".join(ids[i:i + 40]))))
        for e in root.findall("a:entry", NS):
            aid = e.find("a:id", NS).text.rsplit("/abs/", 1)[-1]
            aid = re.sub(r"v\d+$", "", aid)
            out[aid] = {"abstract": " ".join(e.find("a:summary", NS).text.split()),
                        "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)]}
        time.sleep(PAUSE_S)
    return out


def pdf_text(aid):
    from pypdf import PdfReader
    r = PdfReader(BytesIO(_fetch(PDF.format(id=aid))))
    txt = "\n".join((p.extract_text() or "") for p in r.pages)
    txt = re.split(r"\n\s*(References|REFERENCES|Bibliography)\s*\n", txt)[0]      # drop the reference list
    txt = re.sub(r"-\n(\w)", r"\1", txt)                                            # re-join hyphenated words
    return " ".join(txt.split())


def chunks(text, n=CHUNK_WORDS, ov=OVERLAP_WORDS):
    w = text.split()
    for s in range(0, max(len(w) - ov, 1), n - ov):
        piece = " ".join(w[s:s + n])
        if len(piece.split()) >= 40:
            yield piece


def authors_short(names):
    if not names:
        return ""
    last = names[0].split()[-1]
    return last if len(names) == 1 else (f"{last} & {names[1].split()[-1]}" if len(names) == 2 else f"{last} et al.")


def main():
    papers = json.loads((HERE / "papers.json").read_text(encoding="utf-8"))
    meta = abstracts([p["arxiv_id"] for p in papers])
    DATA.mkdir(exist_ok=True)
    n_full = 0
    with open(DATA / "chunks.jsonl", "w", encoding="utf-8") as f:
        for p in papers:
            aid = p["arxiv_id"]
            m = meta.get(aid, {})
            base = {"paper_id": aid, "title": p["title"], "authors": authors_short(m.get("authors")) or p["first_author"],
                    "year": p.get("year"), "arxiv": aid, "url": f"https://arxiv.org/abs/{aid}", "topic": p.get("topic"),
                    "license": p.get("license")}
            k = 0
            if m.get("abstract"):
                f.write(json.dumps({**base, "id": f"{aid}#a", "text": f"{p['title']}. {m['abstract']}"}, ensure_ascii=False) + "\n")
                k += 1
            if "creativecommons.org" in str(p.get("license", "")):
                try:
                    for piece in chunks(pdf_text(aid)):
                        f.write(json.dumps({**base, "id": f"{aid}#{k}", "text": piece}, ensure_ascii=False) + "\n")
                        k += 1
                    n_full += 1
                except Exception as e:  # noqa: BLE001
                    print("full text failed", aid, e)
                time.sleep(PAUSE_S)
            print(aid, k, "chunks", flush=True)
    n = sum(1 for _ in open(DATA / "chunks.jsonl", encoding="utf-8"))
    print(f"{len(papers)} papers, {n_full} with full text, {n} chunks")


if __name__ == "__main__":
    main()
