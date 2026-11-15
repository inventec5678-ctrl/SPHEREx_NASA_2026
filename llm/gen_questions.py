"""Seed questions for the assistant's training dialogues, one shard per GPU node.

Each seed is (context, language, persona, material) and the teacher model writes several questions a visitor
could ask. Seeds: paper passages (most), the site's fields and targets, Solar System bodies and the spacecraft
(the 3D home), the control room, Gaia stars in the fields (the lab), and general astronomy with no paper behind it.

  python llm/gen_questions.py --shard 0 --nshards 8 --model <teacher path> --root <repo root>
"""
import argparse
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGS = ("en", "zh-Hant")
PERSONAS = ["a curious high-school student", "an amateur astronomer", "a science teacher preparing a class",
            "a citizen scientist who joined Backyard Worlds", "a professional astronomer checking the tool",
            "a journalist writing about SPHEREx", "a hackathon judge with no astronomy background",
            "a university physics student", "a retired engineer who likes space", "a parent exploring with a child"]
BODIES = ["the Sun", "Mercury", "Venus", "Earth", "the Moon", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune",
          "the Milky Way", "the SPHEREx spacecraft", "the asteroid belt", "the Kuiper belt", "a hypothetical Planet Nine"]
GENERAL = ["what a light-year is", "why stars twinkle", "how telescopes see infrared light", "what a galaxy is",
           "how far the nearest stars are", "what dark matter is", "how planets form", "what a supernova is",
           "how astronomers measure distances with parallax", "what proper motion means", "the life of a star",
           "what an exoplanet is", "how big the universe is", "what a black hole is", "why Pluto is a dwarf planet",
           "what comets are made of", "the difference between asteroids and comets", "how NASA names missions",
           "what spectra tell us", "what infrared astronomy can see that visible light cannot"]
N_PER_SEED = {"chunk": 3, "field": 6, "body": 6, "room": 6, "star": 3, "general": 5}
SEEDS_PER_KIND = {"field": 12, "body": 8, "room": 40, "star": 160, "general": 100}   # chunk seeds: 2 per chunk


def _lang_name(lang):
    return "English" if lang == "en" else "Traditional Chinese as written in Taiwan (繁體中文)"


def seeds(root, rng):
    chunks = [json.loads(x) for x in open(HERE / "index" / "chunks.jsonl", encoding="utf-8")]
    out = []
    for c in chunks:
        for lang in LANGS:
            out.append({"kind": "chunk", "lang": lang, "material": f"Passage from \"{c['title']}\" ({c['authors']}, "
                        f"{c['year']}):\n{c['text']}", "context": None})
    fields = []
    for p in sorted((root / "web" / "data" / "fields").glob("*/field.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("quick") or p.parent.name.endswith((".new", ".old")):
            continue
        fields.append((p.parent.name, d))
    for fid, d in fields:
        kind = "target" if d.get("target") else "field"
        for _ in range(SEEDS_PER_KIND["field"]):
            out.append({"kind": "field", "lang": rng.choice(LANGS), "context": {"kind": kind, "id": fid,
                        "name": d.get("name"), "ra": d.get("ra"), "dec": d.get("dec")},
                        "material": f"{d.get('name')}: {d.get('description', '')}"})
        ov = root / "web" / "data" / "fields" / fid / "overlays.json"
        if ov.exists():
            gaia = json.loads(ov.read_text(encoding="utf-8")).get("gaia") or []
            for s in rng.sample(gaia, min(len(gaia), SEEDS_PER_KIND["star"] // max(len(fields), 1))):
                pm = (s.get("pmx", 0) ** 2 + s.get("pmy", 0) ** 2) ** 0.5
                facts = {"Gaia G": round(s.get("m", 0), 2), "proper motion arcsec/yr": round(pm, 3), "field": d.get("name")}
                out.append({"kind": "star", "lang": rng.choice(LANGS), "context": {"kind": "star",
                            "name": f"Gaia star in {d.get('name')}", "facts": facts},
                            "material": f"A star the user clicked in the field lab: {facts}"})
    for b in BODIES:
        for _ in range(SEEDS_PER_KIND["body"]):
            out.append({"kind": "body", "lang": rng.choice(LANGS), "context": {"kind": "body", "name": b},
                        "material": f"The user selected {b} in the site's 3D zoom from the Milky Way to SPHEREx."})
    for _ in range(SEEDS_PER_KIND["room"]):
        fid, d = rng.choice(fields)
        band = rng.choice(["D1 0.75-1.09 um", "D3 1.63-2.41 um", "D6 4.42-5.00 um", "D1+D3+D6 colour"])
        out.append({"kind": "room", "lang": rng.choice(LANGS), "context": {"kind": "room", "id": fid, "name": d.get("name"),
                    "facts": {"band": band, "pass": rng.randint(1, 3)}},
                    "material": f"The user is in the site's stylised SPHEREx control room looking at {d.get('name')} "
                                f"through the window, band {band}, and talks to the robot guide."})
    for _ in range(SEEDS_PER_KIND["general"]):
        out.append({"kind": "general", "lang": rng.choice(LANGS), "context": None,
                    "material": f"General astronomy topic: {rng.choice(GENERAL)}."})
    return out


PROMPT = """You write realistic questions that a visitor types into the chat assistant of "SPHEREx Sky Change", a \
public website that plays NASA SPHEREx infrared sky images of any position as a time sequence so moving and variable \
objects stand out (asteroids, nearby stars, brown dwarfs, variable stars, a Planet X search).

The visitor is {persona}. {where}
Material the questions should be answerable from:
{material}

Write {n} different questions in {language}. Mix short and longer ones, factual and "why/how" ones, and at most one \
that compares with something else. The visitor has NOT seen the material, so never refer to "the passage" or "the \
text". Return only a JSON list of strings."""


def where(seed):
    c = seed["context"]
    if not c:
        return "The visitor is not looking at any particular object."
    return f"The visitor is currently looking at: {c.get('name')} ({c['kind']})."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--nshards", type=int, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--root", default=str(HERE.parent))
    a = ap.parse_args()
    rng = random.Random(1234)
    all_seeds = seeds(Path(a.root), rng)
    mine = [s for i, s in enumerate(all_seeds) if i % a.nshards == a.shard]
    rng = random.Random(a.shard)
    from vllm import LLM, SamplingParams
    llm = LLM(a.model, max_model_len=4096, gpu_memory_utilization=0.92)
    convs = []
    for s in mine:
        s["persona"] = rng.choice(PERSONAS)
        convs.append([{"role": "user", "content": PROMPT.format(persona=s["persona"], where=where(s), material=s["material"],
                                                                n=N_PER_SEED[s["kind"]], language=_lang_name(s["lang"]))}])
    outs = llm.chat(convs, SamplingParams(temperature=0.9, top_p=0.95, max_tokens=600))
    n = 0
    with open(HERE / "data" / f"questions_{a.shard}.jsonl", "w", encoding="utf-8") as f:
        for s, o in zip(mine, outs):
            m = re.search(r"\[.*\]", o.outputs[0].text, re.S)
            try:
                qs = [q.strip() for q in json.loads(m.group(0)) if isinstance(q, str) and 3 < len(q.strip()) < 400]
            except Exception:  # noqa: BLE001
                continue
            for q in qs[:N_PER_SEED[s["kind"]]]:
                f.write(json.dumps({"seed_kind": s["kind"], "lang": s["lang"], "persona": s["persona"],
                                    "context": s["context"], "question": q}, ensure_ascii=False) + "\n")
                n += 1
    print(f"shard {a.shard}: {len(mine)} seeds -> {n} questions")


if __name__ == "__main__":
    main()
