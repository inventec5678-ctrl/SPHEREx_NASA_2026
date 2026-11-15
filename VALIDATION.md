# Validation

Every number below is recomputed by `scripts/write_validation_md.py` from the files the site serves (`/api/validation`, shown on the site's *Find movers* page).

## 1. Automatic proper-motion search (sxlib/pmsearch.py)

The search compares the first and last survey-pass stacks without looking at any catalogue; Gaia DR3 and CatWISE2020 only label the result afterwards.

| Target | Found blind | Measured | Catalogue |
|---|---|---|---|
| barnard | yes | 10.52"/yr | 10.39"/yr |
| epsindi | yes | 4.33"/yr | 4.68"/yr |
| wise0855 | yes | 7.03"/yr | 8.15"/yr |

False alarms (movers the catalogues call static) across 9 analysed fields: **0**.

### Random Gaia DR3 high-proper-motion stars (45 of 45 done; 9 < G < 16, 0.15 deg field, 45 exposures per pass)

| Proper motion | Found / tried |
|---|---|
| 0.5-1.0"/yr | 1 / 15 |
| 1.0-2.0"/yr | 6 / 15 |
| 2.0+"/yr | 12 / 15 |

Astrometry (measured shift minus Gaia proper motion + parallax): median 0.397", 90th percentile 0.806" (n = 44).
Measured / catalogue proper motion for the stars found: median 1.047.
Extra "new" candidates in these fields: 0.
Below about 0.7"/yr a star moves less than 0.12 px (0.75") between passes a year apart: the detection limit.

## 2. Brown-dwarf spectral classifier (sxlib/specclass.py)

60000 synthetic spectra (50% T/Y dwarfs; stars, M giants/Miras, L dwarfs, YSOs, galaxies), no real data.

- Synthetic validation: accuracy 0.969, ROC AUC 0.992.
- Real SPHEREx spectra of the two known cold brown dwarfs: epsindi 1.000, wise0855 0.999.
- Real SPHEREx spectra of 420 Gaia stars in the analysed fields: median score 0.0, false-positive rate 0.5% at 0.8.

## 3. R Draconis against the AAVSO ephemeris

VSX (read through the CfA VizieR mirror): period 246.12 d, maximum at JD 2457370.0.

| Pass | Phase (0 = visual max) | SPHEREx relative brightness |
|---|---|---|
| 1 | 0.12 | x1.2 |
| 2 | 0.79 | x1.1 |
| 3 | 0.54 | x0.9 |

Order of brightness agrees with the phase: **True**. A 246-day sinusoid fitted to the SPHEREx points puts the infrared maximum at phase D1 0.97, D2 0.06, D3 0.12, D6 0.05, with the largest amplitude at the shortest wavelengths (D1 0.84, D2 0.2, D3 0.37, D6 0.28), as expected for a Mira.

## 4. Photometry of saturated stars: the Barnard's Star control

Barnard's Star is steady, so its brightest/faintest pass ratio measures the method's own error.

| Method | D1 | D2 | D3 | D4 | D5 | D6 |
|---|---|---|---|---|---|---|
| PSF-wing ring (used) | 1.16 | 1.37 | 1.05 | 1.08 | 1.14 | 1.16 |
| SPHEREx PSF fit (rejected for saturated stars) | 1.54 | 1.27 | 1.13 | 2.04 | 1.03 | 1.13 |

The PSF fit (sxlib/psfphot.py) is calibrated on unsaturated stars (PSF / aperture flux 0.97-1.03 for Epsilon Indi B) but on saturated stars the pixels next to the core are already non-linear and the L2 PSF only reaches 5 px, so the ring stays.

## 1b. Cross-epoch proper motions: SPHEREx against CatWISE2020 (sxlib/xepoch.py)

SPHEREx alone spans one year. CatWISE measured the same stars around 2015.4, so the SPHEREx position against the CatWISE position has a baseline of about 10.5 years. Gaia stars fix the frame (affine, per pass) and label the result; they do not choose candidates.

- 1659 sources measured in 8 fields; scatter against Gaia proper motions: **13.8 mas/yr per axis** (isolated stars).
- False alarms: 0 of 1300 stars Gaia calls static, and 0 of 324 sources without a Gaia match.
- Only 50% of sources are isolated enough to be trusted (no other catalogue source within the match radius); without that cut dozens of static stars pass every other test, so the cut stays and the others are not searched.

| Injected motion (isolated static stars, CatWISE position displaced) | Recovered |
|---|---|
| 0.05"/yr | 12 / 658 (2%) |
| 0.08"/yr | 173 / 658 (26%) |
| 0.1"/yr | 334 / 658 (51%) |
| 0.15"/yr | 519 / 658 (79%) |
| 0.2"/yr | 570 / 658 (87%) |
| 0.3"/yr | 599 / 658 (91%) |

| Real Gaia movers in the fields | Stars | Isolated | Found |
|---|---|---|---|
| 0.15+"/yr | 4 | 2 | 2 |
| 0.1-0.15"/yr | 3 | 1 | 0 |
| 0.05-0.1"/yr | 28 | 20 | 2 |

The sample of real movers is tiny (the fields are small). Parallax: a joint proper-motion + parallax fit is run for every candidate, but **no parallax is claimed**: static stars scatter by 70-135 mas in the same fit, Epsilon Indi B gives 183 +/- 105 mas (catalogue 271) and the value depends on how the passes are registered (102-297 mas). An earlier figure of 304 +/- 71 mas came from leaving the passes unregistered and is withdrawn.

## 5. Automatic variable-star search (sxlib/varsearch.py)

Blind detection on the pass stacks; forced photometry in every exposure; per detector a fit of F(lambda, t) = S(lambda) x L(pass); a candidate needs a significant change that agrees in at least two detectors. Gaia DR3 and VSX only label the result.

| Star | Role | Flagged | Brightest / faintest pass | Significance |
|---|---|---|---|---|
| R Draconis | variable (Mira) | yes | x1.90 | 5.9 |
| RW Aurigae | variable (T Tauri) | yes | x1.23 | 7.85 |
| Barnard's Star | control (constant) | no | x1.04 | 1.35 |

- 927 isolated stars searched in 9 fields: 2 candidates, 2 catalogued as variable, 0 catalogued as constant (false alarms), 0 not in the catalogues.
- Completeness against the catalogues: 194 VSX / Gaia variables lie in the fields, 40 are on a star that could be searched, 2 were flagged. The others vary by under about 8% or on short periods; 3-4 passes of about two weeks cannot show that.
- Blended stars (a neighbour within 5 px) are excluded: the undersampled PSF moves the neighbour's light in and out of the aperture and fakes variability.
- The threshold for saturated stars (x1.30) was set on these same fields, so the Barnard control is not independent. No unsaturated real variable has been recovered yet.

## 6. Bright-star residuals in the asteroid pipeline: the high-latitude control

Fields far from the ecliptic hold almost no asteroids, so an unidentified fast track there is a false track. Before 2026-11-12 the linker chained subtraction residuals of bright and saturated stars into such tracks. The fix (sxlib/analyze.static_repeaters): a detection that sits where detections keep recurring within 1.6 px for more than 1.5 days, in at least three half-hour epochs, is left out of fast linking; nothing moving at the linker's minimum rate (0.5 arcsec/h) can stay there that long.

| Field | Unidentified fast tracks before | Now |
|---|---|---|
| rdra | 14 | 0 |
| epsindi | 21 | 0 |
| barnard | 2 | 0 |
| wise0855 | 0 | 0 |
| rwaur | 0 | 0 |
| cybele | 1 | 2 |
| taurus | 0 | 1 |

The 65 Cybele field keeps all five known asteroids (three of them linked blind) and its one unidentified track; the simulated Planet X field is unchanged (tests/test_static_veto.py covers the rule).
