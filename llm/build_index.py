"""data/chunks.jsonl -> index/chunks.jsonl + index/embeddings.npy (L2-normalised), the format
web/api_ask.py loads, embedded with the same model and passage prefix it queries with.
  python llm/build_index.py [embed_model_path]"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from web.api_ask import EMBED_MODEL, PASSAGE_PREFIX  # noqa: E402


def main(model=EMBED_MODEL):
    from sentence_transformers import SentenceTransformer
    rows = [json.loads(x) for x in open(HERE / "data" / "chunks.jsonl", encoding="utf-8")]
    m = SentenceTransformer(model)
    emb = m.encode([PASSAGE_PREFIX + r["text"] for r in rows], batch_size=128, normalize_embeddings=True, show_progress_bar=True)
    out = HERE / "index"
    out.mkdir(exist_ok=True)
    np.save(out / "embeddings.npy", emb.astype(np.float32))
    shutil.copy2(HERE / "data" / "chunks.jsonl", out / "chunks.jsonl")
    print(len(rows), "chunks,", len({r["paper_id"] for r in rows}), "papers, dim", emb.shape[1])


if __name__ == "__main__":
    main(*sys.argv[1:])
