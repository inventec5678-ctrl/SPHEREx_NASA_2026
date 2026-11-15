"""Write VALIDATION.md from the same numbers the site shows (/api/validation): python scripts/write_validation_md.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402


def render(v):
    """The markdown text of VALIDATION.md for the /api/validation document v."""
    L =["# Validation", "", "Every number below is recomputed by `scripts/write_validation_md.py` from the files the site serves "
         "(`/api/validation`, shown on the site's *Find movers* page).", ""]
    L += ["## 1. Automatic proper-motion search (sxlib/pmsearch.py)", "",
          "The search compares the first and last survey-pass stacks without looking at any catalogue; Gaia DR3 and "
          "CatWISE2020 only label the result afterwards.", "", "| Target | Found blind | Measured | Catalogue |", "|---|---|---|---|"]
    for t in v["targets"]:
        L.append(f"| {t['id']} | {'yes' if t['found'] else 'no'} | {t['pm']:.2f}\"/yr | {t['pm_cat']}\"/yr |" if t["found"] else f"| {t['id']} | no | - | {t['pm_cat']}\"/yr |")
    L += ["", f"False alarms (movers the catalogues call static) across {v['fields_searched']} analysed fields: **{v['false_movers_in_fields']}**.", ""]
    ks = v.get("known_stars")
    if ks:
        L += [f"### Random Gaia DR3 high-proper-motion stars ({ks['n_done']} of {ks['n_total']} done; 9 < G < 16, 0.15 deg field, "
              f"{ks['per_pass_exposures']} exposures per pass)", "", "| Proper motion | Found / tried |", "|---|---|"]
        for g in ks["strata"]:
            rng = f"{g['pm_lo']}+" if g["pm_hi"] > 50 else f"{g['pm_lo']}-{g['pm_hi']}"
            L.append(f"| {rng}\"/yr | {g['found']} / {g['n']} |")
        a = ks["astrometry_resid_arcsec"]
        L += ["", f"Astrometry (measured shift minus Gaia proper motion + parallax): median {a['median']}\", 90th percentile {a['p90']}\" (n = {a['n']}).",
              f"Measured / catalogue proper motion for the stars found: median {ks['pm_ratio_median']}.",
              f"Extra \"new\" candidates in these fields: {ks['false_new_candidates']}.",
              "Below about 0.7\"/yr a star moves less than 0.12 px (0.75\") between passes a year apart: the detection limit.", ""]
    sp = v.get("spectral")
    if sp:
        L += ["## 2. Brown-dwarf spectral classifier (sxlib/specclass.py)", "", sp["training"] + ".", "",
              f"- Synthetic validation: accuracy {sp['synthetic_val_accuracy']:.3f}, ROC AUC {sp['synthetic_val_auc']:.3f}.",
              f"- Real SPHEREx spectra of the two known cold brown dwarfs: " + ", ".join(f"{k} {x:.3f}" for k, x in sp["real_positive_scores"].items()) + ".",
              f"- Real SPHEREx spectra of {sp['real_negatives']['n']} Gaia stars in the analysed fields: median score {sp['real_negatives']['median_score']}, "
              f"false-positive rate {sp['real_negatives']['false_positive_rate']['0.8'] * 100:.1f}% at 0.8.", ""]
    mi = v.get("mira")
    if mi:
        L += ["## 3. R Draconis against the AAVSO ephemeris", "",
              f"VSX (read through the CfA VizieR mirror): period {mi['vsx']['period_d']} d, maximum at JD {mi['vsx']['epoch_max_jd']}.", "",
              "| Pass | Phase (0 = visual max) | SPHEREx relative brightness |", "|---|---|---|"]
        L += [f"| {q['pass'] + 1} | {q['phase']} | x{q['rel_brightness']} |" for q in mi["passes"]]
        L += ["", f"Order of brightness agrees with the phase: **{mi['order_agrees']}**. A 246-day sinusoid fitted to the SPHEREx points puts the "
              "infrared maximum at phase " + ", ".join(f"{k} {x['phase_of_max']}" for k, x in mi["sinusoid"].items()) +
              ", with the largest amplitude at the shortest wavelengths (" + ", ".join(f"{k} {x['amplitude']}" for k, x in mi["sinusoid"].items()) + "), as expected for a Mira.", ""]
    rc = v.get("ring_control")
    if rc:
        L += ["## 4. Photometry of saturated stars: the Barnard's Star control", "",
              "Barnard's Star is steady, so its brightest/faintest pass ratio measures the method's own error.", "",
              "| Method | D1 | D2 | D3 | D4 | D5 | D6 |", "|---|---|---|---|---|---|---|"]
        for k, name in (("ring", "PSF-wing ring (used)"), ("psf", "SPHEREx PSF fit (rejected for saturated stars)")):
            L.append(f"| {name} | " + " | ".join(str(rc[k].get(f'D{d}', '-')) for d in range(1, 7)) + " |")
        L += ["", "The PSF fit (sxlib/psfphot.py) is calibrated on unsaturated stars (PSF / aperture flux 0.97-1.03 for Epsilon Indi B) "
              "but on saturated stars the pixels next to the core are already non-linear and the L2 PSF only reaches 5 px, so the ring stays.", ""]
    xe = v.get("xepoch")
    if xe:
        L += ["## 1b. Cross-epoch proper motions: SPHEREx against CatWISE2020 (sxlib/xepoch.py)", "",
              "SPHEREx alone spans one year. CatWISE measured the same stars around 2015.4, so the SPHEREx position against the CatWISE "
              "position has a baseline of about 10.5 years. Gaia stars fix the frame (affine, per pass) and label the result; they do not choose candidates.", "",
              f"- {xe['n_measured']} sources measured in 8 fields; scatter against Gaia proper motions: **{xe['scatter_per_axis_mas_yr']} mas/yr per axis** (isolated stars).",
              f"- False alarms: {xe['static']['flagged']} of {xe['static']['n']} stars Gaia calls static, and {xe['no_gaia']['flagged']} of {xe['no_gaia']['n']} sources without a Gaia match.",
              f"- Only {xe['isolated_fraction'] * 100:.0f}% of sources are isolated enough to be trusted (no other catalogue source within the match radius); "
              "without that cut dozens of static stars pass every other test, so the cut stays and the others are not searched.", "",
              "| Injected motion (isolated static stars, CatWISE position displaced) | Recovered |", "|---|---|"]
        L += [f"| {r['pm']}\"/yr | {r['found']} / {r['n']} ({r['frac'] * 100:.0f}%) |" for r in xe["injected_isolated"]]
        L += ["", "| Real Gaia movers in the fields | Stars | Isolated | Found |", "|---|---|---|---|"]
        L += [f"| {r['gaia_pm_lo']}{'+' if r['gaia_pm_hi'] > 50 else '-' + str(r['gaia_pm_hi'])}\"/yr | {r['n']} | {r['n_isolated']} | {r['found']} |" for r in xe["recall"]]
        L += ["", "The sample of real movers is tiny (the fields are small). Parallax: a joint proper-motion + parallax fit is run for every candidate, "
              "but **no parallax is claimed**: static stars scatter by 70-135 mas in the same fit, Epsilon Indi B gives 183 +/- 105 mas (catalogue 271) "
              "and the value depends on how the passes are registered (102-297 mas). An earlier figure of 304 +/- 71 mas came from leaving the passes "
              "unregistered and is withdrawn.", ""]
    vr = v.get("variables")
    if vr:
        t = vr["targets"]
        L += ["## 5. Automatic variable-star search (sxlib/varsearch.py)", "",
              "Blind detection on the pass stacks; forced photometry in every exposure; per detector a fit of "
              "F(lambda, t) = S(lambda) x L(pass); a candidate needs a significant change that agrees in at least two detectors. "
              "Gaia DR3 and VSX only label the result.", "",
              "| Star | Role | Flagged | Brightest / faintest pass | Significance |", "|---|---|---|---|---|"]
        for k, name, role in (("rdra", "R Draconis", "variable (Mira)"), ("rwaur", "RW Aurigae", "variable (T Tauri)"), ("barnard", "Barnard's Star", "control (constant)")):
            if k in t and t[k].get("amp") is not None:
                L.append(f"| {name} | {role} | {'yes' if t[k]['flagged'] else 'no'} | x{t[k]['amp']:.2f} | {t[k]['sig']} |")
        L += ["", f"- {vr['n_searched']} isolated stars searched in {vr['fields']} fields: {vr['n_candidates']} candidates, "
              f"{vr['by_status']['known_variable']} catalogued as variable, {vr['by_status']['catalogued_constant']} catalogued as constant (false alarms), {vr['by_status']['new']} not in the catalogues.",
              f"- Completeness against the catalogues: {vr['catalogued']['in_fields']} VSX / Gaia variables lie in the fields, {vr['catalogued']['searched']} are on a star "
              f"that could be searched, {vr['catalogued']['flagged']} were flagged. The others vary by under about 8% or on short periods; 3-4 passes of about two weeks cannot show that.",
              "- Blended stars (a neighbour within 5 px) are excluded: the undersampled PSF moves the neighbour's light in and out of the aperture and fakes variability.",
              "- The threshold for saturated stars (x1.30) was set on these same fields, so the Barnard control is not independent. No unsaturated real variable has been recovered yet.", ""]
    sv = v.get("static_veto")
    if sv:
        before = {"rdra": 14, "epsindi": 21, "barnard": 2, "wise0855": 0, "rwaur": 0, "cybele": 1, "taurus": 0}
        L += ["## 6. Bright-star residuals in the asteroid pipeline: the high-latitude control", "",
              "Fields far from the ecliptic hold almost no asteroids, so an unidentified fast track there is a false track. Before 2026-11-12 the "
              "linker chained subtraction residuals of bright and saturated stars into such tracks. The fix (sxlib/analyze.static_repeaters): a detection "
              "that sits where detections keep recurring within 1.6 px for more than 1.5 days, in at least three half-hour epochs, is left out of fast "
              "linking; nothing moving at the linker's minimum rate (0.5 arcsec/h) can stay there that long.", "",
              "| Field | Unidentified fast tracks before | Now |", "|---|---|---|"]
        L += [f"| {k} | {before[k]} | {sv.get(k, '-')} |" for k in before]
        L += ["", "The 65 Cybele field keeps all five known asteroids (three of them linked blind) and its one unidentified track; "
              "the simulated Planet X field is unchanged (tests/test_static_veto.py covers the rule).", ""]
    return "\n".join(L)


def main():
    from web.server import validation
    text = render(validation())
    # UTF-8 and LF on every OS, so the file is byte-identical whether written on Linux or Windows
    with open(ROOT / "VALIDATION.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")         # a Windows console may not encode every character
    print(text)


if __name__ == "__main__":
    main()
