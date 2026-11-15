"""Merge dialogue shards, drop bad turns, write train/eval sets in TRL's prompt-completion format.

Drops a turn when: the answer cites [n] beyond the passages it was given (or cites with none given); it has no
"no source" note although nothing was retrieved; it is in the wrong language; it is empty, very long or a refusal.
Duplicated questions are kept once. 3% of dialogues are held out for evaluation.

  python llm/filter_merge.py
"""
import json
import random
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CJK = re.compile(r"[一-鿿]")
SIMPLIFIED = set("这们说时从来对为没关发开问还应进经过现实动长与东风书")   # common simplified-only characters
NO_SOURCE = re.compile(r"no source|not (?:covered|in the) (?:by )?(?:the )?(?:sources|passages)|general knowledge|"
                       r"沒有來源|無來源|沒有出處|一般知識|並非來自|未提供來源|沒有相關", re.I)
BAD = re.compile(r"as an ai language model|i cannot browse|作為一個AI語言模型", re.I)
EVAL_FRAC = 0.03


def lang_ok(text, lang):
    cjk = len(CJK.findall(text)) / max(len(text), 1)
    if lang == "en":
        return cjk < 0.02
    return cjk > 0.25 and sum(ch in SIMPLIFIED for ch in text) <= 2


def turn_ok(t, lang):
    ans = t["answer"]
    if not (20 <= len(ans) <= 2500) or BAD.search(ans) or not lang_ok(ans, lang):
        return "length/lang/refusal"
    cites = [int(x) for x in re.findall(r"\[(\d+)\]", ans)]
    if any(c < 1 or c > t["n_sources"] for c in cites):
        return "bad citation"
    if t["n_sources"] == 0 and not NO_SOURCE.search(ans):
        return "missing no-source note"
    return None


def main():
    rows = []
    for p in sorted(DATA.glob("dialogues_*.jsonl")):
        rows += [json.loads(x) for x in open(p, encoding="utf-8")]
    why = Counter()
    seen, dialogues = set(), []
    for r in rows:
        key = re.sub(r"\W+", " ", r["question"].lower()).strip()
        if key in seen:
            why["duplicate"] += 1
            continue
        seen.add(key)
        good = []
        for t in r["turns"]:
            bad = turn_ok(t, r["lang"])
            if bad:
                why[bad] += 1
                break                      # a follow-up only makes sense after a good first answer
            good.append(t)
        if good:
            dialogues.append({**r, "turns": good})
    random.Random(7).shuffle(dialogues)
    n_eval = max(50, int(len(dialogues) * EVAL_FRAC))
    sets = {"eval": dialogues[:n_eval], "train": dialogues[n_eval:]}
    for name, ds in sets.items():
        with open(DATA / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for d in ds:
                for t in d["turns"]:
                    f.write(json.dumps({"prompt": t["messages"], "completion": [{"role": "assistant", "content": t["answer"]}],
                                        "lang": d["lang"], "seed_kind": d["seed_kind"], "n_sources": t["n_sources"]},
                                       ensure_ascii=False) + "\n")
    n_utter = sum(2 * len(d["turns"]) for d in dialogues)
    stats = {"dialogues_in": len(rows), "dialogues_kept": len(dialogues), "turns_kept": sum(len(d["turns"]) for d in dialogues),
             "utterances_kept": n_utter, "train_dialogues": len(sets["train"]), "eval_dialogues": n_eval,
             "dropped": dict(why), "by_lang": Counter(d["lang"] for d in dialogues),
             "by_kind": Counter(d["seed_kind"] for d in dialogues),
             "grounded_first_turn": sum(1 for d in dialogues if d["turns"][0]["n_sources"] > 0)}
    (DATA / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
