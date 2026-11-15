"""Render the paper / project pages from templates + evidence JSON (numbers are never typed by hand).

Templates: web/app/paper_src/*.html  ->  web/app/public/paper/*.html
  {{path.to.value|fmt}}   value from the evidence bundle (fmt: .3f, pct1, int, ci3, cipct1)
  <!--TABLE:name-->       a generated table (see TABLES)
  <!--FIG:name-->         a generated inline SVG figure (see FIGS)
Every marker must resolve, otherwise the script stops (no silently missing numbers).
Also copies the evidence JSON into public/paper/research/ and records SHA-256 hashes.
"""
import hashlib
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import APP, FIELDS, MODELS, PAPER_AAS, PAPER_EVIDENCE as EVD, PUBLIC, read_json, read_text, run, write_json, write_text  # noqa: E402

SRC = APP / "paper_src"
OUT = PUBLIC / "paper"
PIX_ARCSEC = 6.15              # SPHEREx pixel scale, arcsec
ASTRO_MAX_ARCSEC = 5.0         # JPL residuals beyond this are mismatches, not astrometric error
DEMO_FIELDS = ("cybele", "planetx", "taurus")
ZH_PAGES = ("zh.html", "paper-zh.html")
RESEARCH_EVIDENCE = ("evidence.json", "planetx_grid.json", "manifest.json", "discovery.json", "stack_grid.json", "stack_null.json")
RESEARCH_MODELS = ("metrics.json", "recovery.json")


def _median_low(values):
    """The lower median (sorted(v)[n // 2]), as the published tables use."""
    v = sorted(values)
    return v[len(v) // 2]


def load_bundle():
    ev = read_json(EVD / "evidence.json")
    grid = read_json(EVD / "planetx_grid.json")
    metrics = read_json(MODELS / "metrics.json")
    recovery = read_json(MODELS / "recovery.json")
    fields, raw = {}, {}
    for f in DEMO_FIELDS:
        p = FIELDS / f / "field.json"
        if p.exists():
            d = raw[f] = read_json(p)
            fields[f] = {"n_exposures": len(d["exposures"]), "n_tracks": len(d["tracks"]),
                         "n_known": sum(1 for t in d["tracks"] if t.get("known")),
                         "n_unknown": sum(1 for t in d["tracks"] if not t.get("known")),
                         "tracks": d["tracks"], "simulated": d.get("simulated", [])}
    # derived values used in the text
    rows = [r for r in ev["completeness_by_mag"] if r["n"] >= 20]
    mag50 = None
    for a, b in zip(rows, rows[1:]):
        if a["pipeline"] >= 0.5 > b["pipeline"]:
            ma, mb = (a["ab_lo"] + a["ab_hi"]) / 2, (b["ab_lo"] + b["ab_hi"]) / 2
            mag50 = ma + (a["pipeline"] - 0.5) / (a["pipeline"] - b["pipeline"]) * (mb - ma)
    g = grid["table"]
    derived = {
        "mag50_pipeline": mag50,
        "grid_recovered": sum(r["recovered"] for r in g), "grid_n": sum(r["n"] for r in g),
        "grid_median_err_pct": float(_median_low(r["median_d_err_pct"] for r in g if r["median_d_err_pct"] is not None)),
        "grid_max_err_pct": max(r["max_d_err_pct"] for r in g if r["max_d_err_pct"] is not None),
        "grid_false_total": grid["false_distant_tracks_total"],
        "grid_fields_n": len(grid["fields"]),
        "grid_false_fields": sum(1 for f in grid["per_field"] if f["n_false_distant"] > 0),
        "fpr_min_det": min(r["fpr"] for r in ev["by_detector"]), "fpr_max_det": max(r["fpr"] for r in ev["by_detector"]),
        "fpr_min_det_name": "D%d" % min(ev["by_detector"], key=lambda r: r["fpr"])["detector"],
        "fpr_max_det_name": "D%d" % max(ev["by_detector"], key=lambda r: r["fpr"])["detector"],
        "train_cands": ev["dataset_totals"]["train"]["candidates"], "train_inj": ev["dataset_totals"]["train"]["injected"],
        "train_bogus_capped": "50000 per field",
    }
    pl = fields.get("planetx", {})
    dist = [t for t in pl.get("tracks", []) if t["kind"] == "distant"]
    if dist and pl.get("simulated"):
        derived["demo_px_d_fit"] = dist[0]["d_au"]; derived["demo_px_members"] = len(dist[0]["members"])
        derived["demo_px_d_true"] = pl["simulated"][0]["d_au"]; derived["demo_px_passes"] = dist[0]["n_passes"]
    # honesty numbers from the fields: blind linking and JPL astrometry (seen from SPHEREx)
    res, objs, bad = [], set(), 0
    for doc in raw.values():
        for t in doc["tracks"]:
            j = t.get("jpl")
            if not j:
                continue
            if not j["consistent"]:
                bad += 1
                continue
            objs.add(t["known"])
            res += [h for h in (float(np.hypot(dx, dy)) for _, dx, dy in j["resid"]) if h <= ASTRO_MAX_ARCSEC]
    if res:
        derived["astro_median"] = round(float(np.median(res)), 2); derived["astro_n"] = len(res)
        derived["astro_objects"] = len(objs); derived["astro_px"] = round(float(np.median(res)) / PIX_ARCSEC, 2)
        derived["astro_p90"] = round(float(np.percentile(res, 90)), 2); derived["astro_bad_tracks"] = bad
    cyd = raw.get("cybele")
    if cyd and cyd.get("blind_link"):
        derived["cy_tracks"] = len(cyd["tracks"]); derived["cy_blind_tracks"] = cyd["blind_link"]["n_tracks"]
        derived["cy_blind_known"] = cyd["blind_link"]["n_known"]
        derived["cy_assisted"] = sum(1 for t in cyd["tracks"] if t.get("blind") is False)
        derived["cy_jpl_ok"] = sum(1 for t in cyd["tracks"] if (t.get("jpl") or {}).get("consistent"))
        derived["cy_jpl_bad"] = sum(1 for t in cyd["tracks"] if t.get("jpl") and not t["jpl"]["consistent"])
    pmerr = [np.hypot(b["pm_fit"][0] - b["pm_true"][0], b["pm_fit"][1] - b["pm_true"][1])
             for f in grid.get("per_field", []) for b in f.get("bodies", []) if b.get("pm_fit") and b.get("pm_true")]
    if pmerr:
        derived["grid_pm_err_median"] = round(float(np.median(pmerr)), 1)
    fp = grid.get("field_passes") or {f["field"]: f["n_passes"] for f in grid.get("per_field", []) if f.get("n_passes")}
    if fp:
        three = [f for f in grid["per_field"] if fp.get(f["field"], 0) >= 3]
        two = [f for f in grid["per_field"] if fp.get(f["field"], 0) < 3]
        derived["grid_3p_fields"] = len(three)
        derived["grid_3p_recovered"] = sum(b["recovered"] for f in three for b in f["bodies"])
        derived["grid_3p_n"] = sum(len(f["bodies"]) for f in three)
        derived["grid_2p_fields"] = len(two); derived["grid_2p_n"] = sum(len(f["bodies"]) for f in two)
        derived["grid_2p_recovered"] = sum(b["recovered"] for f in two for b in f["bodies"])
        errs = sorted(abs(b["d_fit"] - b["d_au"]) / b["d_au"] * 100 for f in three for b in f["bodies"] if b["recovered"])
        derived["grid_bad_fits"] = sum(1 for e in errs if e > 1.0)
    cy = fields.get("cybele", {})
    ct = next((t for t in cy.get("tracks", []) if (t.get("known") or "").startswith("65 Cybele")), None)
    if ct:
        derived["cybele_rate"] = ct["rate_arcsec_h"]; derived["cybele_n"] = len(ct["members"])
    # the discovery search (scripts/vet_candidates.py): real dwarf planets, the survey, the null test, the limit
    disc = read_json(EVD / "discovery.json") if (EVD / "discovery.json").exists() else None
    if disc:
        for dw in disc["dwarfs"]:
            r = dw.get("single") or {}
            b = r.get("blind")
            key = dw["name"].lower()[:2]
            derived[f"dw_{key}_jpl"] = r.get("r_jpl_au")
            derived[f"dw_{key}_n"] = r.get("detections_on_body")
            if b:
                derived[f"dw_{key}_d"] = b["d_au"]; derived[f"dw_{key}_err"] = b["d_err_pct"]
                derived[f"dw_{key}_members"] = b["members"]; derived[f"dw_{key}_rms"] = b["rms_arcsec"]
        sv = disc["survey"]
        derived.update({"sv_fields": sv["n_fields"], "sv_area": sv["area_deg2"], "sv_A": sv["by_region"]["A"], "sv_B": sv["by_region"]["B"],
                        "sv_D": sv["by_region"]["D"], "sv_raw": disc["n_raw"], "sv_pass7": disc["n_pass_checks"],
                        "sv_flux_rej": disc["rejected_by"]["flux"], "sv_known_rej": disc["rejected_by"]["not_known"],
                        "sv_single": sum(1 for c in disc["candidates"] if c["method"] == "single")})
        if disc.get("null"):
            n = disc["null"]
            derived.update({"null_true": n["total_true"], "null_a": n["total_null"][0], "null_b": n["total_null"][1], "null_mean": n["total_null_mean"]})
        if disc.get("limits"):
            L = disc["limits"]
            derived.update({"stack_m50": L["m50_ab"], "p9_frac_pct": round(100 * L["p9_fraction_brighter"], 1)})
        sg = disc.get("stack_grid")
        if sg:
            t = {r["mag"]: r for r in sg["table"]}
            derived["stack_rec_18_19"] = sum(t[m]["recovered"] for m in (18.0, 18.5, 19.0)); derived["stack_n_18_19"] = sum(t[m]["n"] for m in (18.0, 18.5, 19.0))
            derived["stack_rec_195"] = sum(t[m]["recovered"] for m in (19.5, 20.0, 20.5)); derived["stack_n_195"] = sum(t[m]["n"] for m in (19.5, 20.0, 20.5))
            derived["stack_false"] = sg["false_tracks_total"]
    return {"ev": ev, "grid": grid, "metrics": metrics, "recovery": recovery, "fields": fields, "d": derived, "disc": disc}


def resolve(bundle, path):
    cur = bundle
    for part in path.split("."):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def fmt(v, spec, lang):
    if spec == "int":
        return f"{int(v):,}"
    if spec == "pct1":
        return f"{100 * v:.1f}%"
    if spec == "pct2":
        return f"{100 * v:.2f}%"
    if spec == "ci3":
        return f"{v[0]:.3f}–{v[1]:.3f}"
    if spec == "cipct1":
        return f"{100 * v[0]:.1f}–{100 * v[1]:.1f}%"
    if spec:
        return format(v, spec)
    return str(v)


# ------------------------------------------------------------------ tables
def t_by_detector(b, lang):
    zh = lang == "zh"
    h = ["偵測器", "波長", "已知小行星 n", "召回率（95% CI）", "注入天體召回率", "假訊號 n", "誤報率"] if zh else \
        ["Detector", "Wavelength", "Known n", "Recall (95% CI)", "Injected recall", "Bogus n", "FPR"]
    lam = {1: "0.75–1.11 µm", 2: "1.10–1.64 µm", 3: "1.63–2.42 µm", 4: "2.40–3.82 µm", 5: "3.81–4.42 µm", 6: "4.41–5.00 µm"}
    rows = [[f"D{r['detector']}", lam[r["detector"]], f"{r['known_n']}",
             f"{100 * r['known_recall']:.1f}% ({100 * r['known_recall_ci95'][0]:.1f}–{100 * r['known_recall_ci95'][1]:.1f})",
             f"{100 * r['injected_recall']:.1f}%", f"{r['bogus_n']:,}", f"{100 * r['fpr']:.2f}%"] for r in b["ev"]["by_detector"]]
    return table(h, rows)


def t_known_by_mag(b, lang):
    h = ["V 星等", "n", "召回率", "95% CI"] if lang == "zh" else ["V magnitude", "n", "Recall", "95% CI"]
    rows = [[f"{r['v_lo']:g}–{r['v_hi']:g}" if r["v_lo"] else f"< {r['v_hi']:g}", str(r["n"]), f"{100 * r['recall']:.1f}%",
             f"{100 * r['ci95'][0]:.1f}–{100 * r['ci95'][1]:.1f}%"] for r in b["ev"]["known_by_mag"]]
    return table(h, rows)


def t_grid(b, lang):
    zh = lang == "zh"
    mags = b["grid"]["mag_grid"]
    h = (["距離 (AU)"] + [f"AB {m:g}：找回" for m in mags] + ["距離誤差中位數"]) if zh else \
        (["Distance (AU)"] + [f"AB {m:g}: recovered" for m in mags] + ["Median distance error"])
    rows = []
    for d in b["grid"]["d_grid"]:
        cells = [f"{d:g}"]
        errs = []
        for m in mags:
            r = next(x for x in b["grid"]["table"] if x["d_au"] == d and x["mag"] == m)
            cells.append(f"{r['recovered']}/{r['n']}")
            if r["median_d_err_pct"] is not None:
                errs.append(r["median_d_err_pct"])
        cells.append(f"{_median_low(errs):.2f}%" if errs else "–")
        rows.append(cells)
    return table(h, rows)


def t_dataset(b, lang):
    zh = lang == "zh"
    names = {"train": "訓練" if zh else "Train", "val": "驗證" if zh else "Validation", "test": "測試" if zh else "Test",
             "benchmark": "亮小行星基準" if zh else "Bright-asteroid benchmark"}
    h = ["用途", "天區", "候選", "注入", "已知小行星 (V≤18.5)", "假訊號"] if zh else \
        ["Role", "Fields", "Candidates", "Injected", "Known asteroids (V≤18.5)", "Bogus"]
    rows = [[names[k], str(v["fields"]), f"{v['candidates']:,}", f"{v['injected']:,}", f"{v['known_v_le_18_5']:,}", f"{v['bogus']:,}"]
            for k, v in b["ev"]["dataset_totals"].items()]
    return table(h, rows)


def t_hypotheses(b, lang):
    """Criteria with WHEN they were set: only H1 and H3 were fixed before the corresponding test."""
    zh = lang == "zh"
    k, d = b["ev"]["known_asteroids"], b["d"]
    h = ["假說", "判準", "設定時點", "結果", "是否達成"] if zh else ["Hypothesis", "Criterion", "When it was set", "Result", "Met?"]
    met, part, no = ("達成", "部分達成", "未達成") if zh else ("Met", "Partly met", "Not met")
    rows = [
        ["H1", "真實已知小行星 AUROC ≥ 0.95，且誤報率 1% 時召回率 ≥ 80%" if zh else "Real known-asteroid AUROC ≥ 0.95 and recall ≥ 80% at 1% FPR",
         "2026-10-20，訓練前（PLAN.md G3）" if zh else "2026-10-20, before training (PLAN.md G3)",
         f"AUROC {k['auroc']:.3f} ({k['auroc_ci95'][0]:.3f}–{k['auroc_ci95'][1]:.3f}); recall {100 * k['recall']:.1f}% ({100 * k['recall_ci95'][0]:.1f}–{100 * k['recall_ci95'][1]:.1f}%)",
         met if (k["auroc_ci95"][0] >= 0.95 and k["recall_ci95"][0] >= 0.80) else part],
        ["H2", "每個偵測器的誤報率 ≤ 1.5%（驗證集門檻）" if zh else "FPR ≤ 1.5% in every detector (validation threshold)",
         "2026-10-21，看過整體誤報率之後（事後設定）" if zh else "2026-10-21, after seeing the overall FPR (post hoc)",
         f"{100 * b['ev']['test_injected']['fpr']:.2f}% overall; {d['fpr_min_det_name']} {100 * d['fpr_min_det']:.2f}% – {d['fpr_max_det_name']} {100 * d['fpr_max_det']:.2f}%",
         no if d["fpr_max_det"] > 0.015 else met],
        ["H3", "注入遠距天體的距離誤差 ≤ 2%" if zh else "Distance error of injected distant bodies ≤ 2%",
         "2026-10-21，注入網格執行前（WEB_PAPER_PLAN.md）" if zh else "2026-10-21, before the injection grid was run (WEB_PAPER_PLAN.md)",
         f"{d['grid_recovered']}/{d['grid_n']} recovered; median {d['grid_median_err_pct']:.2f}%, max {d['grid_max_err_pct']:.2f}%",
         met if d["grid_max_err_pct"] <= 2 else part],
    ]
    return table(h, rows)


def t_manifest(b, lang):
    man = read_json(EVD / "manifest.json")
    h = ["檔案", "SHA-256（前 12 碼）"] if lang == "zh" else ["File", "SHA-256 (first 12)"]
    return table(h, [[f"<code>{k}</code>", f"<code>{v[:12]}</code>"] for k, v in man.items()])


def table(head, rows):
    th = "".join(f"<th>{h}</th>" for h in head)
    tb = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="table-wrap" tabindex="0" role="region" aria-label="table"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


TABLES = {"by_detector": t_by_detector, "known_by_mag": t_known_by_mag, "grid": t_grid, "dataset": t_dataset,
          "hypotheses": t_hypotheses, "manifest": t_manifest}


# ------------------------------------------------------------------ figures (inline SVG)
def svg_axes(W, H, P, xlab, ylab, xt, yt, X, Y):
    s = [f'<rect x="{P}" y="12" width="{W - P - 14}" height="{H - P - 12}" fill="none" stroke="#c9cdc8"/>']
    for v, lab in xt:
        s.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{H - P}" y2="{H - P + 4}" stroke="#5d676c"/><text x="{X(v):.1f}" y="{H - P + 16}" text-anchor="middle">{lab}</text>')
    for v, lab in yt:
        s.append(f'<line x1="{P - 4}" x2="{P}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#5d676c"/><text x="{P - 7}" y="{Y(v) + 4:.1f}" text-anchor="end">{lab}</text>')
    s.append(f'<text x="{(W + P) / 2:.0f}" y="{H - 4}" text-anchor="middle">{xlab}</text>')
    s.append(f'<text transform="translate(12 {(H - P) / 2:.0f}) rotate(-90)" text-anchor="middle">{ylab}</text>')
    return s


def f_roc(b, lang):
    r = b["ev"]["roc"]; W, H, P = 640, 300, 52
    zh = lang == "zh"
    X = lambda f: P + (math.log10(max(f, 1e-4)) + 4) / 4 * (W - P - 14)
    Y = lambda t: H - P - t * (H - P - 12)
    s = svg_axes(W, H, P, "誤報率 (log)" if zh else "False positive rate (log)", "召回率" if zh else "Recall",
                 [(1e-4, "10⁻⁴"), (1e-3, "10⁻³"), (1e-2, "10⁻²"), (1e-1, "10⁻¹"), (1, "1")], [(0, "0"), (0.5, "0.5"), (1, "1")], X, Y)
    s.append(f'<line x1="{X(0.01):.1f}" x2="{X(0.01):.1f}" y1="12" y2="{H - P}" stroke="#8a4b14" stroke-dasharray="4 4"/>')
    series = [("known_cnn", "#0f6b5c", "CNN · 已知小行星" if zh else "CNN · known asteroids", ""),
              ("injected_cnn", "#3f7fbf", "CNN · 注入天體" if zh else "CNN · injected movers", ""),
              ("known_snr", "#0f6b5c", "只用 S/N · 已知" if zh else "S/N only · known", "5 4"),
              ("injected_snr", "#3f7fbf", "只用 S/N · 注入" if zh else "S/N only · injected", "5 4")]
    for k, (key, col, lab, dash) in enumerate(series):
        pts = " ".join(f"{X(f):.1f},{Y(t):.1f}" for f, t in zip(r["fpr"][1:], r[key][1:]))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" stroke-dasharray="{dash}"/>')
        s.append(f'<line x1="{P + 14}" x2="{P + 40}" y1="{26 + 16 * k}" y2="{26 + 16 * k}" stroke="{col}" stroke-width="2" stroke-dasharray="{dash}"/><text x="{P + 46}" y="{30 + 16 * k}">{lab}</text>')
    return svg(W, H, s, "ROC")


def f_completeness(b, lang):
    rows = [r for r in b["ev"]["completeness_by_mag"] if r["n"] >= 20]
    W, H, P = 640, 280, 52
    zh = lang == "zh"
    lo, hi = rows[0]["ab_lo"], rows[-1]["ab_hi"]
    X = lambda m: P + (m - lo) / (hi - lo) * (W - P - 14)
    Y = lambda c: H - P - c * (H - P - 12)
    s = svg_axes(W, H, P, "注入天體 AB 星等" if zh else "Injected AB magnitude", "每張影像完整度" if zh else "Per-exposure completeness",
                 [(m, f"{m:g}") for m in range(int(lo), int(hi) + 1)], [(0, "0"), (0.5, "0.5"), (1, "1")], X, Y)
    s.append(f'<line x1="{P}" x2="{W - 14}" y1="{Y(0.5):.1f}" y2="{Y(0.5):.1f}" stroke="#c9cdc8" stroke-dasharray="3 3"/>')
    for key, col, lab, k in (("stage1", "#5d676c", "差分 S/N ≥ 5" if zh else "Difference S/N ≥ 5", 0), ("pipeline", "#0f6b5c", "+ CNN（驗證集門檻）" if zh else "+ CNN (validation threshold)", 1)):
        mid = [(r["ab_lo"] + r["ab_hi"]) / 2 for r in rows]
        s.append(f'<polyline points="{" ".join(f"{X(m):.1f},{Y(r[key]):.1f}" for m, r in zip(mid, rows))}" fill="none" stroke="{col}" stroke-width="2"/>')
        for m, r in zip(mid, rows):
            ci = r[key + "_ci95"]
            s.append(f'<line x1="{X(m):.1f}" x2="{X(m):.1f}" y1="{Y(ci[0]):.1f}" y2="{Y(ci[1]):.1f}" stroke="{col}"/><circle cx="{X(m):.1f}" cy="{Y(r[key]):.1f}" r="3" fill="{col}"/>')
        s.append(f'<line x1="{W - 230}" x2="{W - 204}" y1="{26 + 16 * k}" y2="{26 + 16 * k}" stroke="{col}" stroke-width="2"/><text x="{W - 198}" y="{30 + 16 * k}">{lab}</text>')
    return svg(W, H, s, "completeness")


def f_pipeline(b, lang):
    zh = lang == "zh"
    # explicit line breaks: automatic splitting cut words ("cutou/t", "S/N" -> "S/ /N")
    steps = ([["IRSA", "影像切片"], ["對齊到", "共同網格"], ["逐像素", "波長配對", "參考影像"], ["差分", "S/N"], ["CNN", "真／假"], ["串連軌跡", "視差搜尋"], ["JPL", "比對"]] if zh else
             [["IRSA", "cutouts"], ["Common", "grid"], ["Per-pixel", "λ-matched", "reference"], ["Difference", "S/N"], ["CNN", "real/bogus"], ["Link /", "parallax"], ["JPL", "check"]])
    W, H = 760, 120
    w = (W - 20) / len(steps)
    s = []
    for k, st in enumerate(steps):
        x = 10 + k * w
        cls = "box accent" if k in (2, 4) else "box"
        s.append(f'<rect class="{cls}" x="{x + 4:.0f}" y="30" width="{w - 14:.0f}" height="54" rx="8"/>')
        words = st
        for j, wd in enumerate(words[:3]):
            s.append(f'<text x="{x + w / 2 - 3:.0f}" y="{52 + 14 * j - 7 * (len(words[:3]) - 1) + 7}" text-anchor="middle">{wd}</text>')
        if k < len(steps) - 1:
            s.append(f'<path d="M{x + w - 10:.0f} 57 l8 0" stroke="#5d676c" marker-end="url(#ar)"/>')
    s.insert(0, '<defs><marker id="ar" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L6 3L0 6z" fill="#5d676c"/></marker></defs>')
    return svg(W, H, s, "pipeline")


def svg(W, H, parts, label):
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{label}" class="fig-svg">{"".join(parts)}</svg>'


FIGS = {"roc": f_roc, "completeness": f_completeness, "pipeline": f_pipeline}


def render(name, bundle):
    lang = "zh" if name in ZH_PAGES else "en"     # English is the primary interface
    s = read_text(SRC / name)
    s = re.sub(r"<!--TABLE:(\w+)-->", lambda m: TABLES[m.group(1)](bundle, lang), s)
    s = re.sub(r"<!--FIG:(\w+)-->", lambda m: FIGS[m.group(1)](bundle, lang), s)

    def val(m):
        path, _, spec = m.group(1).partition("|")
        return fmt(resolve(bundle, path.strip()), spec.strip(), lang)
    s = re.sub(r"\{\{([^}]+)\}\}", val, s)
    left = re.findall(r"\{\{|<!--(TABLE|FIG):", s)
    if left:
        raise SystemExit(f"{name}: unresolved markers {left}")
    write_text(OUT / name, s)
    return name


AJ_FIGS = ("roc", "completeness", "distances", "dwarfs", "curvature", "skymap", "null", "radius", "spectral", "reliability")


def manuscript_values():
    """The numbers of the AJ manuscript (scripts/paper_aas.py), with LaTeX turned into plain text."""
    import paper_aas
    V, _ = paper_aas.values()
    def clean(v):
        s = str(v)
        for a_, b_ in (("{,}", ","), ("\\,", "\u2009"), ("--", "\u2013"), ("\\%", "%"), ("not constrained", "—")):
            s = s.replace(a_, b_)
        return s
    out = {k: clean(v) for k, v in V.items()}
    out["refs_n"] = str(read_text(PAPER_AAS / "paper.tex").count("\\bibitem"))
    return out


def aj_figures():
    """Vector copies of the manuscript figures for the web pages."""
    out = OUT / "figures" / "aj"; out.mkdir(parents=True, exist_ok=True)
    for n in AJ_FIGS:
        run(["pdftocairo", "-svg", PAPER_AAS / f"fig_{n}.pdf", out / f"{n}.svg"])


def main():
    bundle = load_bundle()
    bundle["v"] = manuscript_values()
    aj_figures()
    write_json(OUT / "research" / "manuscript.json", bundle["v"], ensure_ascii=False)   # read by the home page
    for f in RESEARCH_EVIDENCE:
        shutil.copy(EVD / f, OUT / "research" / f)
    for f in RESEARCH_MODELS:
        shutil.copy(MODELS / f, OUT / "research" / f)
    for p in sorted(SRC.glob("*")):
        if p.suffix == ".html":
            print("rendered", render(p.name, bundle))
        elif p.is_file():
            shutil.copy(p, OUT / p.name)
    pub = {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "publication.json"}
    write_json(OUT / "publication.json", pub)
    print(f"publication.json: {len(pub)} files hashed")


if __name__ == "__main__":
    sys.exit(main())
