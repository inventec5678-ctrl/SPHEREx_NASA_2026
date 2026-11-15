# Planet X and SPHEREx: challenge requirements and where each is met

Source: the NASA Space Apps 2026 challenge page "Planet X and SPHEREx" (last published 2026-10-29).
Checked against the live site on 2026-11-12 (twice). Every row now works on **any position a user types**, not only
on the pre-analysed fields: a finished quick look writes the same lab products as a full analysis.

## Objective (required)

| # | Requirement | Status | Where |
|---|---|---|---|
| O1 | A public-facing web tool that displays SPHEREx images of the sky | Done | the whole site, at https://yu8bryan.com/ (a Google Cloud VM with an NVIDIA L4, static IP 34.104.246.96, behind Cloudflare) |
| O2 | Users enter the coordinates (RA, Dec) of a patch of sky | Done | the search box on the first screen of the home page (decimal, sexagesimal, or an object name resolved by SIMBAD), the top bar on every page, the all-sky map, or `/?ra=…&dec=…` |
| O3 | Show a series of images of that patch like a little video, so moving objects are easy to spot | Done | **Quick look** (`#/sky/<ra dec>`): Enter plays; frames stream in within about a minute, one detector at a time for a steady picture; difference frames appear from about a third of the download; per-pass stacks follow. Analysed fields: the viewer `#/field/<id>` opens on the images |
| O4 | Test on Barnard's Star | Done | `#/target/barnard`: measured proper motion 10.07″ ± 0.20″ vs 10.30″ predicted over 361 days (DR1 + QR3) |
| O5 | Test on Epsilon Indi B (a pair of brown dwarfs) | Done | `#/target/epsindi`: 6.11″ ± 0.07″ vs 6.16″ over 497 days; T-dwarf methane spectrum. Ba and Bb (~0.7″ apart) are unresolved at 6.15″/px; the page says so |
| O6 | Test on WISE 0855 (08h55m10.831s −7d14m42.53s) | Done | `#/target/wise0855`: 9.5 ± 2.0″ vs 8.1″ in D6; Y-dwarf spectrum; neighbour-contamination warning |
| O7 | Test on variable stars RW Aurigae and R Draconis | Done | `#/target/rwaur`, `#/target/rdra`: light curves; saturated cores handled with PSF-wing photometry (R Dra ×1.63 in D1; Barnard control ×1.05–1.37) |

## Potential considerations (optional)

| # | Consideration | Status | Where |
|---|---|---|---|
| C1 | Easy to update with the latest data releases | Done | "Check for new SPHEREx data" + one-click re-analysis on every field lab (`/api/field/<id>/fresh`, `/refresh`); weekly timer `deploy/spherex-update.timer` (enabled; at most one re-analysis per run); quick look always queries IRSA live |
| C2 | Creative display of the 102 bands; per-detector stacks for signal-to-noise | Done | lab (analysed fields and every finished quick look): per-pass stacks of all bands or one detector (D1–D6), false colour D6/D3/D1; quick-look player: per-pass, per-detector stacks |
| C3 | Spectra on the fly ("extra kudos") | Done | any lab, including a quick look of a new position: click any pixel → forced photometry in every exposure (`/api/field/<id>/point`) → spectrum + light curve, CSV download |
| C4 | Add together or subtract images taken at different times | Done | any lab: Blink / One pass / Add all / Subtract (pass A − pass B); quick-look player and viewer: wavelength-matched difference frames |
| C5 | Let users choose the field of view | Done | 0.15° / 0.3° / 0.6° for quick look and full analysis (`?fov=` in the URL); zoom 1×/2×/4× in the lab |
| C6 | Overlay data from other telescopes such as Gaia or WISE | Done | Gaia DR3 and CatWISE2020 overlays propagated by proper motion to each pass, on the SPHEREx image (any lab, viewer); Aladin Lite with WISE, 2MASS, DSS2 and the SPHEREx DR1 all-sky HiPS |
| C7 | Coordinates in the URL, so the tool can be embedded | Done | `/?ra=…&dec=…`, `/?target=barnard`, `#/sky/08h55m10.8s -07d14m42s`, `&fov=0.6`; the view state too (`&v=diff&d=6&k=12`, and in the lab `?t=diff&a=2&b=0&band=6&x=…&y=…`); chrome-less player `&embed=1` with a copyable `<iframe>` snippet |
| C8 | Display metadata such as contamination flags | Done | quick-look player: per-frame share of each SPHEREx flag by its FLAGS-header name (OVERFLOW, PERSIST, GHOST, OUTLIER, HOT, …) and a flag overlay (`&pf=1`); lab: per-pass flag layer (`?fl=1`, `pass/flags.bin`); measurements list how many exposures were flagged at the point and drop them; viewer flag layer; each frame shows time, detector and wavelength |
| C9 | Use public tools: Astropy for data, Aladin (CDS) for display | Done | backend: Astropy (WCS, time, coordinates, space motion), reproject; frontend: Aladin Lite v3 embedded in the lab and quick look |

## Background (stated hope)

| # | Hope | Status | Where |
|---|---|---|---|
| B1 | "help as many people as possible pitch in to make discoveries" | Done | `#/movers`: blink-and-vote on every automatic mover (catalogued ones double as practice), and "Positions people flagged": in any lab a visitor can flag a measured position (moving / variable / unusual spectrum / other), others open it and vote (`/api/report` with `x`,`y`; `/api/spots`). A quick look someone reported on is never pruned |

## Beyond the checklist (2026-11-12)

| Addition | Where |
|---|---|
| Automatic proper-motion search on pass stacks (blind; catalogues only label), with per-detector agreement and a vacated-position test | `sxlib/pmsearch.py`; field lab "Moving stars found automatically"; quick look; `#/movers` |
| Public review queue: blink first/last pass, vote real / artefact / not sure | `#/movers`, `/api/movers`, `/api/report` (`mover`) |
| Self-trained brown-dwarf spectral classifier (synthetic training, real-data test) | `sxlib/specclass.py`, `scripts/train_specclass.py`; score on every clicked spectrum, target and mover |
| Validation on random Gaia high-proper-motion stars, R Dra vs the AAVSO VSX ephemeris, Barnard's Star photometry control | `scripts/validate_pm.py`, `scripts/external_checks.py`, `VALIDATION.md`, panel on `#/movers` |
| SPHEREx PSF-fit photometry (kept for unsaturated sources; rejected for saturated ones by the control) | `sxlib/psfphot.py`, `scripts/psf_targets.py` |
| New releases picked up automatically (IRSA TAP lists `spherex_qrN` / `spherex_drN`; newest processing of each exposure wins) | `sxlib/archive.collections()` |
| Quick looks run as their own systemd units (a web restart no longer kills them); pass stacks grow while frames download; SPHEREx DR1 all-sky HiPS shown first | `web/server.py`, `sxlib/quicklook.py` |
| Disk health endpoint; weekly update skips when disk is low | `/api/health`, `scripts/update_fields.py` |
| First-visit three-step guide; 30-second captioned demo videos (EN, 繁中) | `web/app/src/tour.jsx`, `demo/` |

## Added on 2026-11-12 (evening): audit fixes

| Addition | Where |
|---|---|
| The tool comes first: search on the first screen, Enter plays, the home page loads 0.3 MB instead of 22 MB | `web/app/src/landing.jsx`, `search.jsx`, `near.jsx` |
| A guide page: how to read the images, validation, limits, and this checklist with a direct link per row | `#/guide`, `#/guide/requirements` (`guide.jsx`) |
| Bright-star residuals no longer become "unidentified movers" (R Dra 14 → 0, Eps Ind 21 → 0) | `sxlib/analyze.static_repeaters`, `tests/test_static_veto.py` |
| Cross-epoch proper motions, SPHEREx against CatWISE (14 mas/yr per axis; 0 false alarms in 1270 static stars) | `sxlib/xepoch.py`, `scripts/pm_search.py --validate` |
| Automatic variable-star search (finds R Dra and RW Aur blind; Barnard control not flagged) | `sxlib/varsearch.py`, `scripts/var_search.py` |
| Name resolution with proper motion applied to today's date | `/api/resolve` (SIMBAD, Harvard mirror) |
| Keyboard, reduced motion, phones: Space / arrows in every player, keyboard point picking in the lab, no autoplay under reduced motion, full-width viewer and pinch zoom on phones | `quick.jsx`, `lab.jsx`, `viewer.jsx`, `blink.jsx` |
| Practice mode in the review queue (catalogued movers hide the answer until judged) | `movers.jsx` |
| Licence, dependency list, tests | `LICENSE`, `NOTICE`, `requirements.txt`, `tests/`, `npm test` |

## Known limits

- Since 2026-11-13 every analysed field is on SPHEREx DR1 + QR3 (IRSA retired QR2). The same 45 random Gaia high-proper-motion stars are now found 19 times (QR2 + QR3: 25), mostly the slow movers below 2"/yr, and the median position error rose from 0.27" to 0.40". The cause (new flags, the effective PSF, or the exposure mix) is not yet known; the before/after table is on the validation page (`web/data/validation/dr1.json`). The five targets' motions agree with the catalogue on both releases.
- Bright stars saturate SPHEREx (Barnard in every band, RW Aur at long wavelengths); the pages say which points are missing and why.
- A quick look downloads 280–460 cutouts from IRSA (20 at a time since 2026-11-12: 0.83 → 1.33 cutouts/s measured). Measured end to end, including the lab products: Wolf 359 by name, 0.3°, 280 frames, 391 s; Kapteyn's Star, 0.15°, 366 frames, 404 s (at the old 12 at a time). The first frames appear within seconds; when IRSA is busy it is slower.
- The simulated "Planet X" field has no lab products (rebuilding them would drop the injected planet).
- With SPHEREx alone the automatic search needs a star to move about 0.75" between the first and last pass (~0.7"/yr; found reliably only above 2"/yr). The cross-epoch stage reaches about 0.1-0.15"/yr, but only for the half of the stars that are isolated. No parallax is claimed.
- The variable-star search has 3-4 epochs: it found 2 of the 37 catalogued variables it could check (the two targets); small or fast variability is out of reach.
- AAVSO's own site blocks scripted access, so the variable-star check uses the VSX ephemeris (via VizieR) rather than contemporaneous AAVSO photometry; RW Aur is irregular and has no ephemeris.
- HTTPS ends at Cloudflare: the hop from Cloudflare to the VM is plain http (SSL mode Flexible), and Cloudflare cuts off a request after 100 s without a response (524).
