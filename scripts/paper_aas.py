"""The journal manuscript (AASTeX 6.31, two-column): a technical paper on the detection pipeline and the
distant-body search, written for an astronomy audience. Every number is filled in from the evidence files.

  python scripts/paper_aas_figs.py && python scripts/paper_aas.py
  -> paper_aas/paper.tex, paper_aas/paper.pdf, web/app/public/paper/static/pdfs/spherex_movers_manuscript.pdf
"""
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PAPER_AAS as OUT, PAPER_EVIDENCE as EVD, PUBLIC, read_json, read_text, run, tectonic, write_text  # noqa: E402
import render_paper  # noqa: E402

TECTONIC = tectonic()
TEX_TEMPLATE = Path(__file__).with_name("paper_aas_tex.txt")
MANUSCRIPT_PDF = PUBLIC / "paper" / "static" / "pdfs" / "spherex_movers_manuscript.pdf"
LOG_TAIL = 4000            # characters of tectonic output shown on failure
# m_AB(SPHEREx) - V for a body with solar colours (flat reflectance), averaged over the six detectors with weights
# set by their depth; solar AB magnitudes from Willmer (2018). Positive: the body is fainter in SPHEREx than in V.
SOLAR_COLOUR = 0.28
D_H_KM = 1329.0            # D = D_H_KM / sqrt(p) * 10^(-H/5)
MAKEMAKE_AU = 52.72        # distance at which the curvature figure is read off for Makemake
CURV_MAX_PX = 8            # linear-drift model holds while the orbit's curvature stays below this (pixels)
P9_V, P9_V_ERR_LO = 22.0, 1.4   # Brown et al. (2024): Planet Nine V = 22.0 (+1.1/-1.4)
EFF = {}   # effective stacked limit per region, filled by values()


def values():
    b = render_paper.load_bundle()
    d, ev, grid = b["d"], b["ev"], b["grid"]
    disc = b["disc"] if b.get("disc") is not None else read_json(EVD / "discovery.json")
    sg = read_json(EVD / "stack_grid.json")
    null = read_json(EVD / "stack_null.json")
    met = b["metrics"]
    dw = read_json(OUT / "dwarf_fit.json")
    k, kc, ti = ev["known_asteroids"], ev["known_asteroids_clean"], ev["test_injected"]
    pc = lambda x, n=1: f"{100 * x:.{n}f}"
    ci = lambda a, n=3: f"{a[0]:.{n}f}--{a[1]:.{n}f}"
    cip = lambda a, n=1: f"{100 * a[0]:.{n}f}--{100 * a[1]:.{n}f}"
    dws = {x["name"]: x for x in disc["dwarfs"]}
    t = {r["mag"]: r for r in sg["table"]}
    V = {
        "k_auc": f"{k['auroc']:.3f}", "k_ci": ci(k["auroc_ci95"]), "k_rec": pc(k["recall"]), "k_rec_ci": cip(k["recall_ci95"]),
        "k_snr": f"{k['auroc_snr']:.3f}", "k_n": k["n_known"], "k_fields": k["n_fields"],
        "kc_auc": f"{kc['auroc']:.3f}", "kc_ci": ci(kc["auroc_ci95"]), "kc_rec": pc(kc["recall"]), "kc_fpr": pc(kc["fpr"], 2),
        "kc_snr": f"{kc['auroc_snr']:.3f}", "kc_n": kc["n_known"], "kc_fields": kc["n_fields"], "kc_bogus": f"{kc['n_bogus']:,}",
        "ti_auc": f"{ti['auroc']:.3f}", "ti_ci": ci(ti["auroc_ci95"]), "ti_rec": pc(ti["recall"]), "ti_fpr": pc(ti["fpr"], 2),
        "temp": f"{met['temperature']:.3f}", "mag50": f"{d['mag50_pipeline']:.1f}",
        "fpr_min": pc(d["fpr_min_det"], 2), "fpr_max": pc(d["fpr_max_det"], 2), "fpr_min_name": d["fpr_min_det_name"], "fpr_max_name": d["fpr_max_det_name"],
        "g3_rec": d["grid_3p_recovered"], "g3_n": d["grid_3p_n"], "g3_f": d["grid_3p_fields"], "g2_n": d["grid_2p_n"], "g2_rec": d["grid_2p_recovered"],
        "g_med": f"{d['grid_median_err_pct']:.2f}", "g_max": f"{d['grid_max_err_pct']:.0f}", "g_false": d["grid_false_total"], "g_fields": d["grid_fields_n"],
        "g_pm": d["grid_pm_err_median"], "g_bad": d["grid_bad_fits"],
        "a_med": d["astro_median"], "a_n": d["astro_n"], "a_obj": d["astro_objects"], "a_px": d["astro_px"], "a_p90": d["astro_p90"], "a_bad": d["astro_bad_tracks"],
        "cy_n": d["cybele_n"], "cy_rate": d["cybele_rate"], "cy_tracks": d["cy_tracks"], "cy_blind": d["cy_blind_tracks"], "cy_blind_known": d["cy_blind_known"],
        "cy_assist": d["cy_assisted"], "cy_ok": d["cy_jpl_ok"], "cy_bad": d["cy_jpl_bad"],
        "mm_d": f"{dw['Makemake']['d']:.2f}", "mm_n": dw["Makemake"]["n"], "mm_rms": f"{dw['Makemake']['rms']:.1f}",
        "mm_jpl": f"{dws['Makemake']['single']['r_jpl_au']:.2f}", "mm_err": f"{abs(dw['Makemake']['d'] - dws['Makemake']['single']['r_jpl_au']) / dws['Makemake']['single']['r_jpl_au'] * 100:.2f}",
        "hm_d": f"{dw['Haumea']['d']:.2f}", "hm_n": dw["Haumea"]["n"], "hm_rms": f"{dw['Haumea']['rms']:.1f}",
        "hm_jpl": f"{dws['Haumea']['single']['r_jpl_au']:.2f}", "hm_err": f"{abs(dw['Haumea']['d'] - dws['Haumea']['single']['r_jpl_au']) / dws['Haumea']['single']['r_jpl_au'] * 100:.2f}",
        "er_jpl": f"{dws['Eris']['single']['r_jpl_au']:.2f}", "mm_det": dws["Makemake"]["single"]["detections_on_body"], "hm_det": dws["Haumea"]["single"]["detections_on_body"],
        "st_1819": sum(t[m]["recovered"] for m in (18.0, 18.5, 19.0)), "st_1819n": sum(t[m]["n"] for m in (18.0, 18.5, 19.0)),
        "st_195": sum(t[m]["recovered"] for m in (19.5, 20.0, 20.5)), "st_195n": sum(t[m]["n"] for m in (19.5, 20.0, 20.5)),
        "st_m50": f"{disc['limits']['m50_ab']:.1f}", "st_false": sg["false_tracks_total"],
        "sv_fields": disc["survey"]["n_fields"], "sv_area": disc["survey"]["area_deg2"], "sv_A": disc["survey"]["by_region"]["A"],
        "sv_B": disc["survey"]["by_region"]["B"], "sv_D": disc["survey"]["by_region"]["D"], "sv_raw": disc["n_raw"], "sv_pass": disc["n_pass_checks"],
        "sv_flux": disc["rejected_by"]["flux"], "sv_known": disc["rejected_by"]["not_known"],
        "nl_true": null["total_true"], "nl_a": null["total_null"][0], "nl_b": null["total_null"][1], "nl_mean": null["total_null_mean"],
        "nl_sig": f"{(null['total_true'] - null['total_null_mean']) / np.sqrt(null['total_null_mean']):.1f}",
        # Brown et al. (2024): V = 22.0 (+1.1/-1.4); fraction brighter than the stacked limit converted to V
        "p9_frac": f"{50 * (1 + math.erf((disc['limits']['m50_ab'] - SOLAR_COLOUR - P9_V) / (P9_V_ERR_LO * math.sqrt(2)))):.1f}",
        "ph_ra": f"{disc['survey']['phan_2025_extrapolated'][0]:.2f}", "ph_dec": f"{disc['survey']['phan_2025_extrapolated'][1]:.2f}",
        "n_train": ev["dataset_totals"]["train"]["fields"],
    }
    # curvature of real orbits against the linear-drift model (paper_aas_figs.curvature)
    cv = read_json(OUT / "curvature.json")
    dd = np.array([q["d"] for q in cv]); mx = np.array([q["max_all"] for q in cv]); w2 = np.array([q["w2"] for q in cv])
    k = np.where(mx < CURV_MAX_PX)[0][0]
    dcrit = float(np.exp(np.interp(np.log(CURV_MAX_PX), np.log([mx[k], mx[k - 1]]), np.log([dd[k], dd[k - 1]]))))
    lo = np.interp(np.log(MAKEMAKE_AU), np.log(dd), [q["w2_lo"] for q in cv]); hi = np.interp(np.log(MAKEMAKE_AU), np.log(dd), [q["w2_hi"] for q in cv])
    V.update({"d_crit": f"{dcrit:.0f}", "w2_mm": f"{np.interp(np.log(MAKEMAKE_AU), np.log(dd), w2):.0f}", "w2_lo": f"{lo:.0f}", "w2_hi": f"{hi:.0f}",
              "derr_50": f"{np.interp(np.log(50), np.log(dd), [q['derr'] for q in cv]):.1f}",
              "cv_500": f"{np.interp(np.log(500), np.log(dd), mx):.1f}"})
    # reflected-light size limits at opposition: D = D_H_KM / sqrt(p) 10^(-H/5), H = m - 5 log10(d (d - 1))
    def dmax(m, pv, d):
        """Largest undetected diameter for an AB limit m: converted to V for solar colours (flat reflectance)."""
        return D_H_KM / np.sqrt(pv) * 10 ** (-(m - SOLAR_COLOUR - 5 * np.log10(d * (d - 1))) / 5)
    def dist_for(m, pv, D0):
        g = np.geomspace(20, 5000, 20000); return float(g[np.argmin(abs(dmax(m, pv, g) - D0))])
    m_st = disc["limits"]["m50_ab"]; m_si = d["mag50_pipeline"]
    D_FIELD_MIN = 2 / np.radians(0.5)    # a body stays inside a 0.5 deg field over three passes only beyond ~230 au
    D_STACK_MIN = 400.0                  # parallax-only stacking holds where in-pass orbital motion stays below ~1 pixel
    # effective stacked limit per region: a body must outshine the brightest chance track of its region
    eff = {}
    for g in "ABD":
        sn = [c["snr"] for c in disc["candidates"] if c["region"] == g and c["method"] == "stack"]
        eff[g] = m_st - 2.5 * np.log10(max(sn) / 7.0) if sn else m_st
    # region A: replace the heuristic by the Monte Carlo injections into its three fields (check_regionA.py):
    # magnitude of 50% completeness for tracks whose stacked significance exceeds the largest chance track
    mc = read_json(OUT / "regionA_mc.json")
    bod = [b_ for r_ in mc for b_ in r_["bodies"]]; smaxA = max(c["snr"] for c in disc["candidates"] if c["region"] == "A" and c["method"] == "stack")
    def m50_of(ok):
        mags = sorted({b_["mag"] for b_ in bod}); fr = [np.mean([ok(b_) for b_ in bod if b_["mag"] == m_]) for m_ in mags]
        k = next(i for i in range(len(fr) - 1) if fr[i] >= 0.5 > fr[i + 1])
        return mags[k] + (fr[k] - 0.5) / (fr[k] - fr[k + 1]) * (mags[k + 1] - mags[k])
    mcA7, mcAs = m50_of(lambda b_: b_["recovered"]), m50_of(lambda b_: b_["recovered"] and b_["s_stack"] > smaxA)
    epsA = np.median([x for r_ in mc for x in r_["epsR_frac"]])
    V.update({"effA_heur": f"{eff['A']:.1f}", "mcA7": f"{mcA7:.1f}", "mcAs": f"{mcAs:.1f}", "mcA_n": len(bod), "mcA_nf": len({r_['field'] for r_ in mc}),
              "epsA": f"{100 * epsA:.1f}", "smaxA": f"{smaxA:.1f}"})
    eff["A"] = mcAs
    EFF.update(eff)
    V["effA"] = f"{eff['A']:.1f}"
    m_eff = min(eff.values())
    V.update({"phan500": f"{dmax(eff['D'], 0.4, 500) / 1000:,.0f}", "phan700": f"{dmax(eff['D'], 0.4, 700) / 1000:,.0f}", "solcol": f"{SOLAR_COLOUR:.2f}"})
    V.update({"d_field": f"{D_FIELD_MIN:.0f}", "effA": f"{eff['A']:.1f}", "effB": f"{eff['B']:.1f}", "effD": f"{eff['D']:.1f}", "m_eff": f"{m_eff:.1f}"})
    def excluded(pv, D0):
        """Distance range over which a body of diameter D0 would have been detected (single exposures beyond
        D_FIELD_MIN, the conservative stacked limit beyond D_STACK_MIN); None if nowhere."""
        g = np.geomspace(D_FIELD_MIN, 3000, 30000)
        lim = np.where(g >= D_STACK_MIN, np.minimum(dmax(m_si, pv, g), dmax(m_eff, pv, g)), dmax(m_si, pv, g))
        ok = D0 >= lim
        if not ok.any():
            return None
        i0 = int(np.argmax(ok)); i1 = i0 + int(np.argmin(ok[i0:])) - 1 if not ok[i0:].all() else len(g) - 1
        return float(g[i0]), float(g[i1])
    for pv, tag in ((0.08, "d"), (0.4, "b")):
        for name, D0 in (("earth", 12742), ("nep", 49528), ("jup", 139820)):
            r = excluded(pv, D0)
            V[f"{name}_{tag}"] = "not constrained" if r is None else f"{r[0]:.0f}--{r[1]:.0f}\\,au"
        V[f"pl230_{tag}"] = f"{dmax(m_si, pv, D_FIELD_MIN) / 1000:,.0f}"; V[f"d500_{tag}"] = f"{dmax(m_eff, pv, 500) / 1000:,.0f}"
    # methane: parametric effective albedo, 30% and 10% of the visible p = 0.4 (D scales as p_eff^-1/2)
    for pv, tag in ((0.12, "m30"), (0.04, "m10")):
        for name, D0 in (("nep", 49528), ("jup", 139820)):
            r = excluded(pv, D0)
            V[f"{name}_{tag}"] = "not constrained" if r is None else f"{r[0]:.0f}--{r[1]:.0f}\\,au"
    m50_det = b["recovery"]["mag50_pipeline_by_detector"]
    for k_, v_ in m50_det.items():
        V[f"m50_{k_}"] = f"{v_:.1f}"
    dp = read_json(OUT / "dwarf_profile.json")
    V.update({"mm_w": "/".join(str(dp["Makemake"]["windows"].get(str(k), 0)) for k in range(3)),
              "hm_w": "/".join(str(dp["Haumea"]["windows"].get(str(k), 0)) for k in range(3)),
              "mm_prof": f"{dp['Makemake']['second'] / dp['Makemake']['rms']:.0f}", "hm_prof": f"{dp['Haumea']['second'] / dp['Haumea']['rms']:.0f}"})
    tabs = {"by_mag": ev["known_by_mag"], "by_det": ev["by_detector"], "totals": ev["dataset_totals"], "grid": grid["table"], "sg": sg["table"],
            "null": null["fields"], "disc": disc, "m50_det": m50_det}
    return V, tabs


def tables(T):
    tot = T["totals"]
    names = {"train": "Training", "val": "Validation", "test": "Test", "benchmark": "Bright-asteroid benchmark"}
    t1 = "\n".join(f"{names[k]} & {v['fields']} & {v['candidates']:,} & {v['injected']:,} & {v['known_v_le_18_5']} & {v['bogus']:,} \\\\" for k, v in tot.items())
    vlab = lambda r: "$<15$" if r["v_lo"] == 0 else f"{r['v_lo']:g}--{r['v_hi']:g}"
    t2 = "\n".join(f"{vlab(r)} & {r['n']} & {100 * r['recall']:.1f} & {100 * r['ci95'][0]:.1f}--{100 * r['ci95'][1]:.1f} \\\\" for r in T["by_mag"])
    lam = {1: "0.75--1.11", 2: "1.10--1.64", 3: "1.63--2.42", 4: "2.40--3.82", 5: "3.81--4.42", 6: "4.41--5.00"}
    m50 = T["m50_det"]
    t3 = "\n".join(f"D{r['detector']} & {lam[r['detector']]} & {m50['D' + str(r['detector'])]:.1f} & {r['known_n']} & {100 * r['known_recall']:.1f} ({100 * r['known_recall_ci95'][0]:.1f}--{100 * r['known_recall_ci95'][1]:.1f}) & {100 * r['injected_recall']:.1f} & {r['bogus_n']:,} & {100 * r['fpr']:.2f} \\\\" for r in T["by_det"])
    rows = {}
    for r in T["grid"]:
        rows.setdefault(r["d_au"], {})[r["mag"]] = r
    t4 = "\n".join(f"{dd:g} & " + " & ".join(f"{rows[dd][m]['recovered']}/{rows[dd][m]['n']}" for m in sorted(rows[dd])) + " & "
                   + (f"{np.median([rows[dd][m]['median_d_err_pct'] for m in rows[dd] if rows[dd][m]['median_d_err_pct'] is not None]):.2f}") + " \\\\" for dd in sorted(rows))
    t5 = "\n".join(f"{r['mag']:.1f} & {r['recovered']}/{r['n']} & {r['median_d_err_pct']:.2f} \\\\" if r["median_d_err_pct"] is not None else f"{r['mag']:.1f} & {r['recovered']}/{r['n']} & --- \\\\" for r in T["sg"])
    disc = T["disc"]
    reg = {}
    for f in disc["survey"]["fields"]:
        reg.setdefault(f["region"], {"n": 0, "area": 0.0})
        reg[f["region"]]["n"] += 1; reg[f["region"]]["area"] += 0.25 * (1 - f["masked_fraction"])
    nl = {}
    for r in T["null"]:
        g = r["id"][2]; nl.setdefault(g, [0, 0, 0])
        nl[g][0] += r["true"]["confirmed"]; nl[g][1] += r["shift1"]["confirmed"]; nl[g][2] += r["shift2"]["confirmed"]
    cand = {}
    for c in disc["candidates"]:
        g = c["region"]; cand.setdefault(g, [0, 0])
        cand[g][0] += 1; cand[g][1] += all(v for kk, v in c["checks"].items() if kk != "excess")
    desc = {"A": "RA 75--105$^\\circ$, northern Galactic-plane crossing", "B": "RA 45--74$^\\circ$, near predicted aphelion", "D": "IRAS/AKARI candidate, extrapolated"}
    effl = EFF      # set by values(): region A from the Monte Carlo injections, B and D from equation (7)
    t6 = "\n".join(f"{g} & {desc[g]} & {reg[g]['n']} & {reg[g]['area']:.2f} & 0 & {cand.get(g, [0, 0])[0]} & {cand.get(g, [0, 0])[1]} & {nl.get(g, [0, 0, 0])[1]}, {nl.get(g, [0, 0, 0])[2]} & {effl[g]:.1f} \\\\" for g in "ABD")
    return {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6}


def main():
    V, T = values()
    V.update(tables(T))
    tex = re.sub(r"<<(\w+)>>", lambda m: m.group(0) if m.group(1) == "anon" else str(V[m.group(1)]), read_text(TEX_TEMPLATE))
    left = [k for k in re.findall(r"<<\w+>>", tex) if k != "<<anon>>"]
    if left:
        raise SystemExit(f"unfilled: {left}")
    # dual-anonymous review: paper.tex/pdf is the anonymised submission, paper_named.* keeps the author block
    for name, opt in (("paper_named", ""), ("paper", ",anonymous")):
        write_text(OUT / f"{name}.tex", tex.replace("<<anon>>", opt))
        r = run([TECTONIC, "-X", "compile", f"{name}.tex"], cwd=OUT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False)
        if r.returncode:
            print(r.stdout[-LOG_TAIL:], r.stderr[-LOG_TAIL:]); raise SystemExit("tectonic failed")
        warn = [ln for ln in r.stderr.splitlines() if "Overfull" in ln or "undefined" in ln.lower()]
        print(name, "\n".join(warn[:20]))
    dst = MANUSCRIPT_PDF
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUT / "paper.pdf", dst)   # the public site carries the anonymised manuscript (dual-anonymous review)
    print("ok", dst, f"{dst.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
