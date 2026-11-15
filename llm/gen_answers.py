"""Answers (and some follow-ups) for one shard of questions, in exactly the prompt format web/api_ask.py sends at
run time: same system prompt, same retrieval constants, same "Source passages / The user is viewing / Site facts /
Question" layout (build_messages is imported, not copied).

  python llm/gen_answers.py --shard 0 --model <teacher path> --embed <bge path> [--followup 0.4]
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--embed", required=True)
    ap.add_argument("--followup", type=float, default=0.4)
    a = ap.parse_args()
    os.environ["SX_EMBED_MODEL"] = a.embed
    from web import api_ask as A
    from sentence_transformers import SentenceTransformer
    from vllm import LLM, SamplingParams

    chunks = [json.loads(x) for x in open(HERE / "index" / "chunks.jsonl", encoding="utf-8")]
    emb = np.load(HERE / "index" / "embeddings.npy")
    enc = SentenceTransformer(a.embed, device="cuda")

    def retrieve_many(queries):
        q = enc.encode([A.QUERY_PREFIX + x for x in queries], batch_size=256, normalize_embeddings=True)
        s = q @ emb.T
        out = []
        for row in s:
            top = np.argsort(-row)[:A.TOP_K]
            out.append([chunks[i] | {"score": float(row[i])} for i in top if row[i] >= A.MIN_SCORE])
        return out

    rows = [json.loads(x) for x in open(HERE / "data" / f"questions_{a.shard}.jsonl", encoding="utf-8")]
    reqs = []
    for r in rows:
        try:
            reqs.append(A.AskReq(question=r["question"], lang=r["lang"], context=r["context"]))
        except Exception:  # noqa: BLE001
            reqs.append(None)
    keep = [(r, q) for r, q in zip(rows, reqs) if q is not None]
    llm = LLM(a.model, max_model_len=6144, gpu_memory_utilization=0.85)
    sp = SamplingParams(temperature=0.4, top_p=0.9, max_tokens=700)
    tok = llm.get_tokenizer()
    room = 6144 - 700 - 16                     # one over-long prompt fails the whole vLLM batch

    def fit(q, s):
        """Messages for q, dropping the weakest sources until the prompt fits the context."""
        s = list(s)
        while True:
            m = A.build_messages(q, s, A.site_facts(q.context))
            text = tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True)   # tokenize=True may give a dict
            if not s or len(tok.encode(text, add_special_tokens=False)) <= room:
                return s, m
            s.pop()

    def answer(batch):
        srcs = retrieve_many([A._query_text(q) for _, q in batch])
        fitted = [fit(q, s) for (_, q), s in zip(batch, srcs)]
        srcs, msgs = [f[0] for f in fitted], [f[1] for f in fitted]
        outs = llm.chat(msgs, sp)
        return srcs, msgs, [o.outputs[0].text.strip() for o in outs]

    srcs1, msgs1, ans1 = answer(keep)
    rng = random.Random(a.shard)
    fol_idx = [i for i in range(len(keep)) if rng.random() < a.followup]
    fol_prompt = []
    for i in fol_idx:
        r, q = keep[i]
        lang = "English" if q.lang == "en" else "Traditional Chinese as written in Taiwan"
        fol_prompt.append([{"role": "user", "content":
                            f"A website visitor ({r['persona']}) asked: {q.question}\nThe assistant answered: {ans1[i]}\n\n"
                            f"Write the visitor's natural follow-up question in {lang}. Output only the question."}])
    fol_q = [o.outputs[0].text.strip().strip('"') for o in llm.chat(fol_prompt, SamplingParams(temperature=0.9, max_tokens=120))]
    second = []
    for i, fq in zip(fol_idx, fol_q):
        r, q = keep[i]
        try:
            second.append((i, A.AskReq(question=fq[:900], lang=q.lang, context=q.context,
                                       history=[{"role": "user", "content": q.question},
                                                {"role": "assistant", "content": ans1[i]}])))
        except Exception:  # noqa: BLE001
            pass
    srcs2, msgs2, ans2 = answer([(None, q) for _, q in second]) if second else ([], [], [])
    by_first = {i: (s, m, t) for (i, _), s, m, t in zip(second, srcs2, msgs2, ans2)}

    with open(HERE / "data" / f"dialogues_{a.shard}.jsonl", "w", encoding="utf-8") as f:
        for i, ((r, q), s, m, t) in enumerate(zip(keep, srcs1, msgs1, ans1)):
            turns = [{"messages": m, "answer": t, "n_sources": len(s)}]
            if i in by_first:
                s2, m2, t2 = by_first[i]
                turns.append({"messages": m2, "answer": t2, "n_sources": len(s2)})
            f.write(json.dumps({"lang": q.lang, "seed_kind": r["seed_kind"], "context": r["context"],
                                "question": q.question, "turns": turns}, ensure_ascii=False) + "\n")
    print(f"shard {a.shard}: {len(keep)} dialogues, {len(by_first)} with a follow-up")


if __name__ == "__main__":
    main()
