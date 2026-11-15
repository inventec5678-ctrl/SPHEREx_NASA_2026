"""Data figures for the AAS manuscript (paper_aas.py): matplotlib, journal style, PDF vector output.

  python scripts/paper_aas_figs.py                  # -> paper_aas/fig_*.pdf (the paper's own, white figures)
  python scripts/paper_aas_figs.py --dark           # -> web/app/public/paper/figures/aj/{dwarfs,null,radius}-dark.svg
  python scripts/paper_aas_figs.py --dark roc null  # dark variants of any of the figures

The dark variants are for the website only (transparent background, the site's ink and data colours, sans
font); they never overwrite the paper's PDFs or the white SVG copies made by render_paper.py, nor the side
outputs (dwarf_fit.json, curvature.json, reliability.json).
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import MODELS, OUTPUTS, PAPER_AAS as OUT, PAPER_EVIDENCE as EVD, PUBLIC, read_json, rel, write_json  # noqa: E402

COL = 3.35       # AAS column width, inches
WIDE = 7.1
D_H_KM = 1329.0  # D = D_H_KM / sqrt(p) * 10^(-H/5)
LINK_TOL_ARCSEC = 8

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "mathtext.fontset": "dejavuserif",
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8, "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.linewidth": 0.6, "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "lines.linewidth": 1.0, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
C = {"cnn": "#1f4e9c", "snr": "#9c1f1f", "inj": "#2f8f4e", "grey": "#666666", "acc": "#c46a00", "dist": "#6a3d9a",
     "ink": "k", "face": "white"}
C.update(regA=C["acc"], regB=C["inj"], regD=C["dist"])      # survey regions A, B, D

# ---- dark variants for the website (web/app/src/theme.css): page #05070c, figure plates #0b0f18
WEB_AJ = PUBLIC / "paper" / "figures" / "aj"
WEB_FIGS = ("dwarfs", "null", "radius")    # the figures the web pages show (web/app/src/manuscript.jsx)
DARK = False
C_DARK = {"cnn": "#6ec3ff",    # --sx-known
          "snr": "#ff6b6b",    # --sx-bad
          "inj": "#5fd39a",    # --sx-good
          "grey": "#a3a8b2",   # --sx-ink-3
          "acc": "#f5a25d",    # --sx-d5
          "dist": "#c08bff",   # --sx-distant
          "ink": "#f1f2f5",    # --sx-ink
          "face": "#0b0f18",   # --sx-surface (hollow marker faces)
          "regA": "#f2e6c9", "regB": "#5fd39a", "regD": "#c08bff"}   # as the regions on the site's sky map


def use_dark():
    """Switch the style and the palette to the website's dark theme."""
    global DARK
    from matplotlib import font_manager
    sans = "Manrope" if any(f.name == "Manrope" for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
    ink, ink2, ink3 = C_DARK["ink"], "#c9ccd3", C_DARK["grey"]
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": [sans, "DejaVu Sans"], "mathtext.fontset": "dejavusans",
        "text.color": ink2, "axes.labelcolor": ink2, "axes.titlecolor": ink, "axes.edgecolor": ink3,
        "xtick.color": ink3, "ytick.color": ink3, "xtick.labelcolor": ink2, "ytick.labelcolor": ink2, "legend.labelcolor": ink2,
        "grid.color": ink2, "grid.alpha": 0.08, "grid.linewidth": 0.4,
        "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none", "savefig.transparent": True,
        "svg.fonttype": "path", "svg.hashsalt": "spherex-dark",
    })
    C.update(C_DARK)
    DARK = True


def save(fig, name):
    if DARK:
        fig.savefig(WEB_AJ / f"{name}-dark.svg", metadata={"Date": None})
    else:
        fig.savefig(OUT / f"fig_{name}.pdf")


def halo(*texts):
    """Dark variants only: outline text in the plate colour so reference lines crossing it do not cut the glyphs."""
    if DARK:
        from matplotlib import patheffects
        for t in texts:
            t.set_path_effects([patheffects.withStroke(linewidth=1.6, foreground=C["face"])])


SOLAR_COLOUR = 0.28   # m_AB(SPHEREx) - V for solar colours, depth-weighted over detectors (see paper_aas.py)


def load(name):
    return read_json(EVD / name)


def roc(ev):
    r = ev["roc"]
    fpr = np.array(r["fpr"])
    fig, ax = plt.subplots(figsize=(COL, 2.5))
    # markers as well as colours, so the four curves stay distinct in greyscale
    mk = dict(markevery=0.08, ms=3.2, mfc=C["face"], mew=0.7)
    ax.plot(fpr, r["known_cnn"], color=C["cnn"], marker="o", label="Classifier, known asteroids", **mk)
    ax.plot(fpr, r["known_snr"], color=C["cnn"], ls="--", marker="o", label="Significance only, known asteroids", **mk)
    ax.plot(fpr, r["injected_cnn"], color=C["inj"], marker="s", label="Classifier, injected sources", **mk)
    ax.plot(fpr, r["injected_snr"], color=C["inj"], ls="--", marker="s", label="Significance only, injected sources", **mk)
    ax.axvline(0.01, color=C["grey"], ls=":", lw=0.8)
    ax.set_xscale("log"); ax.set_xlim(1e-4, 1); ax.set_ylim(0, 1.01)
    ax.set_xlabel("Fraction of artifacts retained (false-positive rate)"); ax.set_ylabel("Completeness")
    ax.legend(loc="lower right", frameon=False)
    save(fig, "roc"); plt.close(fig)


def completeness(ev, sg):
    rows = [r for r in ev["completeness_by_mag"] if r["n"] >= 20]
    m = np.array([(r["ab_lo"] + r["ab_hi"]) / 2 for r in rows])
    p = np.array([r["pipeline"] for r in rows]); lo = np.array([r["pipeline_ci95"][0] for r in rows]); hi = np.array([r["pipeline_ci95"][1] for r in rows])
    s1 = np.array([r["stage1"] for r in rows])
    fig, ax = plt.subplots(figsize=(COL, 2.4))
    ax.fill_between(m, lo, hi, color=C["cnn"], alpha=0.15, lw=0)
    ax.plot(m, s1, color=C["grey"], ls="--", label="Single exposure, detection only")
    ax.plot(m, p, color=C["cnn"], marker="o", ms=2.5, label="Single exposure, after classification")
    t = sg["table"]
    ms = np.array([r["mag"] for r in t]); fs = np.array([r["recovered"] / r["n"] for r in t])
    ax.plot(ms, fs, color=C["acc"], marker="s", ms=3, label="Shift-and-stack, linked over 3 passes")
    ax.axhline(0.5, color=C["grey"], lw=0.5, ls=":")
    ax.set_xlabel("AB magnitude (single SPHEREx channel)"); ax.set_ylabel("Fraction recovered")
    ax.set_ylim(-0.02, 1.03); ax.set_xlim(14, 21.5)
    ax.legend(loc="lower left", frameon=False)
    save(fig, "completeness"); plt.close(fig)


def distances(grid):
    fp = {f["field"]: f.get("n_passes", 3) for f in grid["per_field"]}
    fig, ax = plt.subplots(figsize=(COL, 2.3))
    xs, ys, cs = [], [], []
    for f in grid["per_field"]:
        if fp[f["field"]] < 3:
            continue
        for b in f["bodies"]:
            if b["recovered"]:
                xs.append(b["d_au"] * (1 + 0.04 * (b["mag"] - 16))); ys.append(abs(b["d_fit"] - b["d_au"]) / b["d_au"] * 100); cs.append(b["mag"])
    sc = ax.scatter(xs, np.maximum(ys, 1e-3), c=cs, cmap="viridis", s=10, vmin=15, vmax=17, lw=0)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Injected distance (AU)"); ax.set_ylabel("|Distance error| (%)")
    ax.axhline(2, color=C["grey"], ls=":", lw=0.8); ax.text(330, 2.4, "2%", fontsize=6.5, color=C["grey"])
    cb = fig.colorbar(sc, ax=ax, pad=0.02); cb.set_label("AB", fontsize=7); cb.ax.tick_params(labelsize=6)
    save(fig, "distances"); plt.close(fig)


def dwarfs():
    """Re-run the blind distant search on the real dwarf-planet detections and plot the linked track with its fit."""
    from sxlib import link
    from sxlib.analyze import P_LINK
    cov = read_json(OUTPUTS / "dwarf_coverage.json")
    fig, axs = plt.subplots(1, 2, figsize=(WIDE, 2.5))
    out = {}
    for ax, name in zip(axs, ("Makemake", "Haumea")):
        pool = []
        for k, p in enumerate(cov[name]["passes"]):
            doc = read_json(OUTPUTS / "dwarf" / f"dw_{name}_{k}" / "field.json"); ex = doc["exposures"]
            pool += [dict(c, mjd=ex[c["i"]]["mjd"], pas=k) for c in doc["candidates"] if p["mjd0"] - 1 <= ex[c["i"]]["mjd"] <= p["mjd1"] + 1 and c["p"] >= P_LINK]
        tracks = link.search_distant(pool)                 # searched once: the figure and the count use the same tracks
        tr = max(tracks, key=lambda t: len(t["members"]))
        mem = [pool[m] for m in tr["members"]]
        ref = min(mem, key=lambda c: c["mjd"])
        ra0, dec0 = np.mean([c["ra"] for c in mem]), np.mean([c["dec"] for c in mem])
        cosd = np.cos(np.radians(dec0))
        tt = np.linspace(min(c["mjd"] for c in mem) - 5, max(c["mjd"] for c in mem) + 5, 600)
        mra, mdec = link.predict_distant(ref["ra"], ref["dec"], ref["mjd"], tr["d_au"], tt, pm=tuple(tr["pm_arcsec_yr"]))
        ax.plot((mra - ra0) * cosd, mdec - dec0, color=C["grey"], lw=0.7, label=f"Fit: {tr['d_au']:.2f} AU")
        for k, mk in zip(range(3), ("o", "s", "^")):
            pts = [c for c in mem if c["pas"] == k]
            if not pts:
                continue
            ax.scatter([(c["ra"] - ra0) * cosd for c in pts], [c["dec"] - dec0 for c in pts], s=6, marker=mk, color=[C["cnn"], C["acc"], C["inj"]][k],
                       lw=0, label=f"Window {k + 1} ({len(pts)})", zorder=3)
        ax.invert_xaxis(); ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel(r"$\Delta\alpha\cos\delta$ (deg)"); ax.set_ylabel(r"$\Delta\delta$ (deg)")
        ax.set_title(name, fontsize=8); ax.legend(frameon=False, fontsize=6.5, loc="best")
        out[name] = {"d": tr["d_au"], "n": len(mem), "rms": tr["rms_arcsec"], "pm": tr["pm_arcsec_yr"], "n_tracks": len(tracks)}
    fig.tight_layout(); save(fig, "dwarfs"); plt.close(fig)
    if not DARK:
        write_json(OUT / "dwarf_fit.json", out, default=float)


def skymap(disc):
    fig, ax = plt.subplots(figsize=(COL, 2.6))
    path = np.array([[0, -17], [26, -5], [40, 1], [53, 8], [67, 14], [82, 19], [97, 23], [114, 26], [130, 26]], float)
    ax.fill_between(path[:, 0], path[:, 1] - 12, path[:, 1] + 12, color=C["cnn"], alpha=0.08, lw=0, label=r"BB21 path $\pm12^\circ$")
    ax.plot(path[:, 0], path[:, 1], color=C["cnn"], lw=0.8)
    mk = {"A": ("o", C["regA"]), "B": ("s", C["regB"]), "D": ("^", C["regD"])}
    for g, (m, c) in mk.items():
        fs = [f for f in disc["survey"]["fields"] if f["region"] == g]
        ax.scatter([f["ra"] for f in fs], [f["dec"] for f in fs], marker=m, s=9, color=c, lw=0, label=f"Region {g} ({len(fs)})")
    ph = disc["survey"]["phan_2025_extrapolated"]
    ax.plot([ph[0]], [ph[1]], marker="x", color=C["ink"], ms=5, mew=0.8, ls="none", label="IRAS/AKARI cand., 2025")
    ax.set_xlim(125, 20); ax.set_ylim(-58, 40)
    ax.set_xlabel(r"$\alpha$ (deg)"); ax.set_ylabel(r"$\delta$ (deg)")
    ax.legend(frameon=False, fontsize=6, loc="lower left", ncol=1)
    save(fig, "skymap"); plt.close(fig)


def nulltest(null):
    rows = null["fields"]
    true = np.array([r["true"]["confirmed"] for r in rows]); nm = np.array([(r["shift1"]["confirmed"] + r["shift2"]["confirmed"]) / 2 for r in rows])
    fig, ax = plt.subplots(figsize=(COL, 2.3))
    reg = [r["id"][2] for r in rows]
    for g, c in (("A", C["regA"]), ("B", C["regB"]), ("D", C["regD"])):
        idx = [k for k, x in enumerate(reg) if x == g]
        ax.scatter(nm[idx] + np.random.default_rng(1).uniform(-0.12, 0.12, len(idx)), true[idx], s=10, color=c, lw=0, label=f"Region {g}")
    mx = max(true.max(), nm.max()) + 1
    ax.plot([0, mx], [0, mx], color=C["grey"], lw=0.7, ls="--")
    ax.set_xlabel("Confirmed tracks, relabelled pass times\n(mean of two cyclic relabellings)"); ax.set_ylabel("Confirmed tracks, true times")
    ax.set_xlim(-0.5, mx); ax.set_ylim(-0.5, mx); ax.legend(frameon=False, loc="upper left")
    save(fig, "null"); plt.close(fig)


def curvature():
    """How far a circular Keplerian orbit departs from the parallax + linear-drift model, sampled at the real
    observing windows of Makemake: residuals of a fit to all three windows, and the offset of the middle window
    predicted from a fit to the first and third windows only (what the blind Makemake/Haumea tracks used)."""
    from sxlib import link
    cov = read_json(OUTPUTS / "dwarf_coverage.json")
    wins = [(p["mjd0"], p["mjd1"]) for p in cov["Makemake"]["passes"]]
    t = np.concatenate([np.linspace(a, b, 30) for a, b in wins])
    ra0, dec0 = cov["Makemake"]["passes"][0]["ra"], cov["Makemake"]["passes"][0]["dec"]
    E = link._earth(t); E0 = link._earth(np.array([t[0]]))[0]; u0 = link._unit(ra0, dec0)
    def body(d, ang):
        b = E0 @ u0; s = -b + np.sqrt(b * b - (E0 @ E0 - d * d)); rh = (E0 + s * u0) / d
        a = np.cross(rh, [0, 0, 1.0]); a /= np.linalg.norm(a); bb = np.cross(rh, a); v = np.cos(ang) * a + np.sin(ang) * bb
        w = 2 * np.pi * d ** -1.5; tt = (t - t[0]) / 365.25
        g = d * (np.cos(w * tt)[:, None] * rh + np.sin(w * tt)[:, None] * v) - E
        return np.degrees(np.arctan2(g[:, 1], g[:, 0])) % 360, np.degrees(np.arcsin(g[:, 2] / np.linalg.norm(g, axis=1)))
    ds = np.geomspace(30, 600, 16); rows = []
    for d in ds:
        r = []
        for ang in np.linspace(0, np.pi, 8, endpoint=False):
            ra, dec = body(d, ang); dets = [{"ra": a, "dec": b, "mjd": m} for a, b, m in zip(ra, dec, t)]
            grid = np.geomspace(max(20, d * 0.7), d * 1.4, 600)
            dfit, rms, pm = link.fit_distant(dets, d_grid=grid)
            pra, pdec = link.predict_distant(ra[0], dec[0], t[0], dfit, t, pm=pm); x, y = link._tangent(ra, dec, pra, pdec)
            sel = np.r_[0:30, 60:90]
            d13, _, pm13 = link.fit_distant([dets[k] for k in sel], d_grid=grid)
            pra, pdec = link.predict_distant(ra[0], dec[0], t[0], d13, t[30:60], pm=pm13); x2, y2 = link._tangent(ra[30:60], dec[30:60], pra, pdec)
            r.append((np.hypot(x, y).max(), np.median(np.hypot(x2, y2)), abs(dfit - d) / d * 100))
        r = np.array(r)
        rows.append({"d": float(d), "max_all": float(np.median(r[:, 0])), "w2": float(np.median(r[:, 1])), "w2_lo": float(r[:, 1].min()),
                     "w2_hi": float(r[:, 1].max()), "derr": float(np.median(r[:, 2]))})
    if not DARK:
        write_json(OUT / "curvature.json", rows)
    d = np.array([q["d"] for q in rows])
    fig, ax = plt.subplots(figsize=(COL, 2.4))
    ax.fill_between(d, [q["w2_lo"] for q in rows], [q["w2_hi"] for q in rows], color=C["acc"], alpha=0.18, lw=0)
    ax.plot(d, [q["w2"] for q in rows], color=C["acc"], label="Middle window, predicted from windows 1+3")
    ax.plot(d, [q["max_all"] for q in rows], color=C["cnn"], label="Maximum residual, fit to all windows")
    ax.axhline(LINK_TOL_ARCSEC, color=C["grey"], ls=":", lw=0.8); ax.text(250, 9.5, r"linking tolerance $8''$", fontsize=6.5, color=C["grey"])
    ax.plot([52.72], [26], marker="*", color=C["ink"], ms=7, ls="none", label="Makemake (observed)")
    ax.plot([49.82], [66], marker="D", color=C["ink"], ms=3.5, ls="none", label="Haumea (observed)")
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(28, 650)
    from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter
    ax.xaxis.set_major_locator(FixedLocator([30, 50, 100, 200, 500])); ax.xaxis.set_major_formatter(ScalarFormatter()); ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Heliocentric distance (au)"); ax.set_ylabel(r"Model departure ($''$)")
    ax.legend(frameon=False, fontsize=6.0, loc="lower left")
    save(fig, "curvature"); plt.close(fig)


def radius_limits(m_single, m_stack):
    """Largest body (diameter) that would stay below the detection limits, in reflected sunlight at opposition:
    m = H + 5 log10(r Delta), D = 1329 km / sqrt(p) 10^(-H/5), with r = d and Delta = d - 1.
    m_stack is the conservative (region A) effective stacked limit."""
    d = np.geomspace(30, 1500, 400)
    fig, ax = plt.subplots(figsize=(COL, 2.6))
    D_FIELD_MIN = 2 / np.radians(0.5)   # a fixed 0.5 deg field retains a body over three passes only beyond ~230 au
    D_STACK_MIN = 400.0                 # parallax-only stacking holds where in-pass orbital motion is below ~1 pixel
    for m, ls, lab, d0 in ((m_single, "--", rf"single exposure, $d \geq {D_FIELD_MIN:.0f}$ au", D_FIELD_MIN),
                           (m_stack, "-", r"stacked, region A, $d \geq 400$ au", D_STACK_MIN)):
        for p, col in ((0.08, C["snr"]), (0.4, C["cnn"])):
            dd = d[d >= d0]
            H = m - SOLAR_COLOUR - 5 * np.log10(dd * (dd - 1))
            D = D_H_KM / np.sqrt(p) * 10 ** (-H / 5)
            ax.plot(dd, D, color=col, ls=ls, label=f"AB {m:.1f} ({lab}), $p={p}$")
    # parametric methane case: effective near-IR albedo 10% of the visible p = 0.4 (not a model atmosphere)
    for m, d0 in ((m_single, D_FIELD_MIN), (m_stack, D_STACK_MIN)):
        dd = d[d >= d0]; H = m - SOLAR_COLOUR - 5 * np.log10(dd * (dd - 1))
        ax.plot(dd, D_H_KM / np.sqrt(0.04) * 10 ** (-H / 5), color=C["cnn"], ls=":", lw=1.1,
                label=r"$p=0.4$, CH$_4$: $p_{\rm eff}=0.04$ (parametric)" if d0 == D_STACK_MIN else None)
    ax.axvspan(30, D_FIELD_MIN, color=C["grey"], alpha=0.12, lw=0)
    ax.text(40, 2.2e5, "not retained\nin fixed fields", fontsize=6.0, color=C["grey"])
    ax.axvline(D_STACK_MIN, color=C["grey"], lw=0.5, ls="-.")
    for name, D0 in (("Pluto", 2377), ("Earth", 12742), ("Neptune", 49528), ("Jupiter", 139820)):
        ax.axhline(D0, color=C["grey"], lw=0.5, ls=":"); ax.text(32, D0 * 1.08, name, fontsize=6.3, color=C["grey"])
    ax.axvspan(380, 800, color=C["dist"], alpha=0.07, lw=0); p9 = ax.text(415, 1.3e6, "Planet Nine\n(predicted)", fontsize=6.2, color=C["dist"])
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(30, 1500); ax.set_ylim(1e3, 4e6)
    ax.set_xlabel("Heliocentric distance (au)"); ax.set_ylabel("Maximum undetected diameter (km)")
    lg = ax.legend(frameon=False, fontsize=5.6, loc="lower right"); halo(p9, *lg.get_texts())
    save(fig, "radius"); plt.close(fig)


def spectral_vetting():
    """Schematic of spectral vetting: per-channel reflectance of a distant icy body (smooth continuum with ice and
    methane bands) against the per-channel fluxes of a chance alignment of stellar residuals. Illustrative only:
    the band profiles are Gaussians, not fits to data."""
    rng = np.random.default_rng(4)
    det = [(0.75, 1.11), (1.11, 1.64), (1.64, 2.42), (2.42, 3.82), (3.82, 4.42), (4.42, 5.00)]
    lam = np.concatenate([np.geomspace(a, b, 17, endpoint=False) for a, b in det])
    def bands(l, spec):
        r = np.ones_like(l)
        for c, w, dpt in spec:
            r *= 1 - dpt * np.exp(-0.5 * ((l - c) / w) ** 2)
        return r
    ice = [(1.5, 0.06, 0.35), (2.0, 0.08, 0.5), (3.0, 0.12, 0.85)]
    ch4 = [(1.15, 0.03, 0.25), (1.4, 0.04, 0.3), (1.7, 0.05, 0.6), (2.3, 0.07, 0.75), (3.3, 0.08, 0.85)]
    co2 = [(4.27, 0.03, 0.6)]
    lf = np.linspace(0.75, 5.0, 800)
    fig, axs = plt.subplots(2, 1, figsize=(COL, 3.6), sharex=True)
    ax = axs[0]
    ax.plot(lf, bands(lf, ice + co2) * (1 + 0.05 * (lf - 0.75)), color=C["cnn"], lw=0.9, label=r"H$_2$O + CO$_2$ ice surface")
    ax.plot(lf, 0.85 * bands(lf, ch4), color=C["acc"], lw=0.9, label=r"CH$_4$-rich (ice or atmosphere)")
    for (a, b), shade in zip(det, [0, 1, 0, 1, 0, 1]):
        if shade:
            ax.axvspan(a, b, color=C["ink"], alpha=0.04, lw=0)
    for k, (a, b) in enumerate(det):
        ax.text((a + b) / 2, 1.22, f"D{k + 1}", ha="center", fontsize=6.3, color=C["grey"])
    ax.set_ylim(0, 1.32); ax.set_ylabel("Reflectance (relative)")
    ax.legend(frameon=False, fontsize=6.2, loc="lower left")
    ax = axs[1]
    true = bands(lam, ice + co2) * (1 + 0.05 * (lam - 0.75))
    obs = true + rng.normal(0, 0.08, lam.size)
    ax.errorbar(lam, obs, yerr=0.08, fmt="o", ms=2, lw=0.5, color=C["cnn"], label=r"Distant body: consistent with model ($\chi^2_\nu \approx 1$)")
    ax.plot(lf, bands(lf, ice + co2) * (1 + 0.05 * (lf - 0.75)), color=C["cnn"], lw=0.6, alpha=0.6)
    # chance alignment: residuals of different stars in different passes -> no common spectrum
    resid = 0.7 + 0.45 * rng.standard_normal(lam.size) * (1 + 0.6 * np.sin(lam * 5.3))
    ax.plot(lam, resid, "s", ms=2, color=C["snr"], label="Chance alignment of residuals: no consistent spectrum")
    ax.set_ylim(-0.6, 2.75); ax.set_xlabel(r"Wavelength ($\mu$m)"); ax.set_ylabel("Flux / solar spectrum")
    ax.legend(frameon=False, fontsize=6.0, loc="upper left")
    fig.tight_layout(h_pad=0.4)
    save(fig, "spectral"); plt.close(fig)


def reliability():
    """Reliability diagram of the calibrated classifier on the two held-out test fields (positives = injected
    sources; real asteroids and other real changes count as negatives here, so the observed fraction is a lower
    limit to the fraction of real sources)."""
    z = np.load(MODELS / "test_scores.npz"); p, y = z["prob"], z["y"]
    bins = np.linspace(0, 1, 11); idx = np.clip(np.digitize(p, bins) - 1, 0, 9)
    mp = np.array([p[idx == i].mean() for i in range(10)]); fy = np.array([y[idx == i].mean() for i in range(10)])
    n = np.bincount(idx, minlength=10)
    lo = fy - 1.96 * np.sqrt(fy * (1 - fy) / n); hi = fy + 1.96 * np.sqrt(fy * (1 - fy) / n)
    fig, ax = plt.subplots(figsize=(COL, 2.5))
    ax.plot([0, 1], [0, 1], color=C["grey"], ls="--", lw=0.7)
    ax.errorbar(mp, fy, yerr=[fy - np.maximum(lo, 0), np.minimum(hi, 1) - fy], fmt="o", ms=3, color=C["cnn"], lw=0.7)
    for x_, y_, n_ in zip(mp, fy, n):
        ax.text(x_ + 0.015, y_ - 0.06, f"{n_:,}", fontsize=5.5, color=C["grey"])
    ax.set_xlabel("Mean predicted probability"); ax.set_ylabel("Fraction of injected sources")
    ax.set_xlim(0, 1); ax.set_ylim(-0.02, 1.02)
    save(fig, "reliability"); plt.close(fig)
    ece = float(sum(abs(mp[i] - fy[i]) * n[i] for i in range(10)) / n.sum())
    if not DARK:
        mid = (p > 0.1) & (p < 0.9)
        write_json(OUT / "reliability.json", {"ece": ece, "frac_extreme": float((n[0] + n[9]) / n.sum()),
                                              "mid_mean_p": float(p[mid].mean()), "mid_frac": float(y[mid].mean())}, indent=None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dark", nargs="*", metavar="FIG", help=f"dark SVGs for the website instead (default: {' '.join(WEB_FIGS)})")
    args = ap.parse_args()
    ev, grid, sg, disc, null = load("evidence.json"), load("planetx_grid.json"), load("stack_grid.json"), load("discovery.json"), load("stack_null.json")

    def radius():
        rows = [r for r in ev["completeness_by_mag"] if r["n"] >= 20]
        m50 = next(a["ab_lo"] / 2 + a["ab_hi"] / 2 + (a["pipeline"] - 0.5) / (a["pipeline"] - b["pipeline"]) * ((b["ab_lo"] + b["ab_hi"]) / 2 - (a["ab_lo"] + a["ab_hi"]) / 2)
                   for a, b in zip(rows, rows[1:]) if a["pipeline"] >= 0.5 > b["pipeline"])
        import paper_aas      # region-A effective limit from the Monte Carlo injections (same value as in the text)
        paper_aas.values()
        radius_limits(m50, min(paper_aas.EFF.values()))
    # in this order: radius reads paper_aas/dwarf_fit.json (via paper_aas.values), which dwarfs writes
    figs = {"roc": lambda: roc(ev), "completeness": lambda: completeness(ev, sg), "distances": lambda: distances(grid),
            "skymap": lambda: skymap(disc), "null": lambda: nulltest(null), "dwarfs": dwarfs, "curvature": curvature,
            "radius": radius, "spectral": spectral_vetting, "reliability": reliability}
    if args.dark is None:
        OUT.mkdir(parents=True, exist_ok=True)
        for f in figs.values():
            f()
        print("figures:", sorted(p.name for p in OUT.glob("fig_*.pdf")))
        return
    names = args.dark or list(WEB_FIGS)
    bad = sorted(set(names) - set(figs))
    if bad:
        ap.error(f"unknown figure(s) {bad}; choose from {list(figs)}")
    use_dark()
    WEB_AJ.mkdir(parents=True, exist_ok=True)
    for n, f in figs.items():
        if n in names:
            f()
            print("wrote", rel(WEB_AJ / f"{n}-dark.svg"))


if __name__ == "__main__":
    main()
