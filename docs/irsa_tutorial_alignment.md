# Our pipeline against IRSA's SPHEREx tutorials and tools (upgrade items R6 + R5)

Written 2026-11-13. Sources: the six IRSA SPHEREx notebooks (https://caltech-ipac.github.io/irsa-tutorials/,
versions dated 5 March – 17 September 2026), the SPHEREx Archive User Guide
(https://irsa.ipac.caltech.edu/spherex-archive-documentation/), the Spectrophotometry Tool help
(https://irsa.ipac.caltech.edu/onlinehelp/spherex/#sp), and live DR1 / QR3 cutouts fetched today.
Our code as of today: `sxlib/archive.py`, `sxlib/stack.py`, `sxlib/products.py`, `sxlib/psfphot.py`.
The user-facing version of this table is the "給開發者 / For developers" section of `#/guide/dev`.

## Summary

| # | Step | Ours | IRSA notebook / tool | Verdict |
|---|---|---|---|---|
| 1 | Find images | `archive.search_images`: SIA, `COLLECTION` = every `spherex_(qr|dr)N` IRSA's TAP lists (today `spherex_dr1`, `spherex_qr3`), science rows only, newest release per (obs_id, detector) | Data Overview §5 (`Irsa.query_sia(..., collection=['spherex_dr1','spherex_qr3'])`) | Same |
| 2 | Cutouts | `archive.fetch_cutout`: `access_url?center=ra,dec&size=deg` | Spectral Image Cutouts (same IBE cutout service; images found with TAP `spherex.artifact ⋈ spherex.plane`) | Same service; they use TAP |
| 3 | Wavelength per pixel | `archive._lam_grid`: `WCS(hdr, fobj=hdul, key="W")` | Data Overview §8b, Cutouts §6, SDT §12: same, **plus `spectral_wcs.sip = None`** | **Differs — fix below (measured)** |
| 4 | Background | `IMAGE − ZODI`, then the field-median residual (`stack.Field.add`), then a 5–9 px annulus median (`products.phot`) | Data Overview §11: ZODI is a model, not subtracted from IMAGE; the Spectrophotometry Tool ignores ZODI and fits a local background with the flux; SDT uses `sep.Background` | Equivalent for point sources |
| 5 | Flags | `HARD_BAD = [0,1,2,4,5,6,9,10,11,14,15,17,26,28]` masked; SOURCE / GHOST / OUTLIER kept as features | Data Overview §9 (names from `MSKNnnnn` header keys); tool ignores SUR_ERROR, NONFUNC, MISSING_DATA, HOT, COLD, NONLINEAR, PERSIST, BLOOM, SNOWBALL, HALO, SATELLITE_HALO | Mostly same; SNOWBALL missing; names outdated — fix below |
| 6 | PSF | `psfphot`: one symmetrised mean PSF per detector (all zones averaged, 8 rotations/flips, 0.4 px blur), sampled at pixel centres for an ePSF; position refined ±0.6 px | PSF Models: the ePSF row whose (XCENTER, YCENTER) is nearest the source's parent-image pixel; `ImagePSF(oversampling=5)`; evaluated (sampled) at pixel centres | Same ePSF convention; we average zones because we fit on a rotated, resampled grid |
| 7 | Spectrum at a point | `/api/field/<id>/point` and target spectra: 2 px aperture (no aperture correction) + PSF fit for the targets | Spectrophotometry Tool (Tractor forced PSF photometry, fixed position, µJy via the solid-angle pixel map); SDT §12 aperture photometry 3–5 px | Compared directly (R5, below) |
| 8 | MJy/sr → µJy | constant `(6.15″)²` per pixel on our resampled TAN grid | SDT §8 / tool: solid-angle pixel map (SAPM) of the native pixels | Equivalent after resampling (surface brightness is resampled, then multiplied by the grid pixel's solid angle); not measured separately |
| 9 | Source finding | time differences + CNN (asteroids), pass-stack positions (proper motion) | Source Discovery Tool: one D2 − D4 colour-difference image + SExtractor | Different question; no one-to-one comparison (see below) |
| 10 | All-sky view | Aladin Lite on `https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube` | HiPS All-Sky Cube | Same product; IRSA: visual only |
| 11 | Stacks | per pass × detector median stacks (`products.py`) | Mosaic Cube (IRSA Mosaic Tool, no API): all dates merged per channel | Different goal (we keep dates apart) |
| 12 | Version bookkeeping | release (`DR1`/`QR3`) per exposure in new builds (`stack.Field.add`); processing version not stored | Cutouts §6 / PSF §4.2 keep the primary header `VERSION` per cutout | Partly — recommendation below |

## Differences, measured, with the exact fix

### 3. Spectral WCS: turn SIP off (measured on 24 exposures)

The IMAGE header's SIP distortion terms belong to the celestial WCS. astropy also applies them to the alternate
WCS "W" unless told not to; IRSA's notebooks all set `spectral_wcs.sip = None`. We do not.

Test (a one-off check script, not kept in the repository): 24 random DR1 exposures of Barnard's Star, wavelength at the star's
position from the cutout's own spectral WCS, against the `lambda` the Spectrophotometry Tool reports for the same
exposure:

| | median \|ours − IRSA\| | max |
|---|---|---|
| SIP on (our code today) | 3.0 nm | 14.0 nm |
| SIP off | 0.3 nm | 1.8 nm |

Per detector (SIP on): D1 −3.0, D2 −3.1, D3 −2.2, D4 −9.5, D5 −2.5, D6 −2.9 nm (always too short). The size
depends on where the source sits on the array; up to ~0.2 of a spectral channel in D4. The same offset shows in the
field products: RW Aurigae's 276 field points are short by 0.2 – 12 nm per detector (median 6 nm).

Fix (`sxlib/archive.py`, `_lam_grid`):

```python
def _lam_grid(hdul, hdr, shape, step=8):
    """Per-pixel wavelength from the WAVE-TAB WCS, sampled every `step` px."""
    w = WCS(hdr, fobj=hdul, key="W")
    w.sip = None          # SIP describes the sky distortion only; IRSA's tutorials turn it off for the spectral WCS
    ...
```

Cached cutouts store the wavelength grid (`lam_y`, `lam_x`, `lam` in `cache/cutouts/*.npz`), so the fix only
reaches new downloads. To correct the cache without re-downloading, recompute the grid from the stored header:
the header JSON keeps the IMAGE header but not the WCS-WAVE table, so in practice the rebuild has to re-fetch
(or the cache key has to change, e.g. add `|nosip` to `_cache_key`).

### 5. Flags

Live DR1 and QR3 cutouts (2026-11-13) define these bits in the FLAGS header (`MSKN0000`…`MSKN0028`):
0 TRANSIENT, 1 OVERFLOW, 2 SUR_ERROR, 6 NONFUNC, 7 DICHROIC, 9 MISSING_DATA, 10 HOT, 11 COLD, 12 FULLSAMPLE,
14 PHANMISS, 15 NONLINEAR, 17 PERSIST, 19 OUTLIER, 20 CROSSTALK, 21 SOURCE, 22 GHOST, 23 GHOST_FPA, 24 GHOST_EXT,
25 STREAK, 26 BLOOM, 27 SNOWBALL, 28 HALO. Bits 4 (PHANTOM) and 5 (REFERENCE) are no longer defined.

- We mask more than the tool does (TRANSIENT, OVERFLOW, PHANMISS are only warnings there). That is conservative and
  fine for difference imaging, but it is why bright stars (RW Aur, Barnard's Star) have no core photometry in our
  products: IRSA flags OVERFLOW on 307 of RW Aur's 335 measurements and still fits them.
- We do not mask SNOWBALL (27), which the tool ignores in its fit.
- `FLAG_NAMES` lacks 20, 25, 26, 27, 28 and names 23/24 "GHOST", so the player's per-frame flag shares never show
  CROSSTALK, STREAK, BLOOM, SNOWBALL or HALO.

Fix (`sxlib/archive.py`):

```python
HARD_BAD = [0, 1, 2, 4, 5, 6, 9, 10, 11, 14, 15, 17, 26, 27, 28]   # + SNOWBALL (27), as IRSA's tool
FLAG_NAMES = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 4: "PHANTOM", 5: "REFERENCE", 6: "NONFUNC", 7: "DICHROIC",
              9: "MISSING_DATA", 10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST",
              19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE", 22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT",
              25: "STREAK", 26: "BLOOM", 27: "SNOWBALL", 28: "HALO"}
```

(Keeping GHOST_BITS = [22, 23, 24] is right; the tool's table says GHOST_FPA cannot appear in images and GHOST_EXT
not yet. If the per-frame summary should stay short, map 23/24 to "GHOST" in the display only.) Better still,
read the names from the header so a new bit needs no code change:
`{int(k[4:]): v for k, v in h["FLAGS"].header.items() if k.startswith("MSKN")}`.

### 6. PSF

Agreement: the lead's new ePSF path (`archive._store_epsf`, `epsf_to_grid`, `psfphot.model(sample=True)`) follows
the tutorial: nearest zone by XCENTER/YCENTER on 0-based parent-image pixels (`Exposure.psf_at`, using CRPIX1A/2A
exactly as tutorial §4.3), and the ePSF *sampled* at pixel centres, not integrated (tutorial §7.2,
`render_epsf_stamp_centered` evaluates `ImagePSF` at pixel centres and renormalises).

Difference: `psfphot.psf_for` averages all 441 zones of a detector and symmetrises over 8 orientations, because the
fit runs on our north-up resampled grid, not in the detector frame; the tutorial and the tool use the one zone at
the source. The ePSF's effective area varies across a detector (tutorial §7.1, NEFF_MEAN), so the averaged PSF is
too wide in some zones and too narrow in others; the R5 per-detector ratios below show the size of that effect.
A per-exposure fit in the native frame (zone ePSF, no resampling), as the tool does, would remove it.

### 12. Versions

Record what processing each exposure came from, as the cutouts notebook does. In `stack.Field.add` (next to
`"release"`):

```python
"version": exp.header.get("VERSION") or "",          # only if fetch_cutout keeps h[0].header["VERSION"] in meta
"proc": (re.search(r"_spx_(l2b[\w-]*?)\.fits", exp.meta["url"]) or [None, ""])[1],   # e.g. l2b-v27-2026-232
```

and in `fetch_cutout` keep `h[0].header.get("VERSION")` (e.g. `7.0.5` for DR1 and QR3 today) in the cached header
JSON.

## R5: the Spectrophotometry Tool, and how we run it

**Interface.** The tool has a web form only (help: "SPHEREx Data Explorer: Spectrophotometry Tool"; the IRSA
mosaic notebook says the same of the Mosaic Tool: "does not have an API"). No Python package or notebook implements
it; the PSF notebook only mentions it as the reference result. The form's Submit button POSTs the Data Explorer's
Firefly endpoint `https://irsa.ipac.caltech.edu/applications/spherex/CmdSrv/async` with `cmd=tableSearch` and a
JSON `request` (`id=SpectrophotometryProcessor`, `UserTargetWorldPt="ra;dec;EQ_J2000"`, `shapeFit=false`,
`useDeep=""`, `startTime`/`endTime` in MJD with `exposureTimeMode=mjd`), read from the app's own JavaScript. The
reply names an IVOA UWS job, `https://irsa.ipac.caltech.edu/api/spherex/spectrophotometry/async/<jobId>`, with
parameters `POINT=ra,dec` and `TIME=mjd0,mjd1`. A direct POST to that UWS service returns 403; GETs of the job
record and of `results/phot-tool-result.vot` are public. There is no login and no bot check; the help page itself
points users at the UWS job link. `scripts/irsa_spectro_compare.py` sends the form's request without a browser and
keeps at most two jobs running (IRSA's throttle). The result VOTable uses `arraysize="4x*"` char arrays, which
astropy refuses (E01), so the script parses it with ElementTree.

**Jobs.** Moving targets: one job per group of frames (frames > 20 days apart split), at `targets.position_at` for
the middle of the group (the tool does not re-centre). Variable targets: one job for the whole span. 15 jobs; each
took 4–16 minutes.

**Matching.** Every IRSA measurement carries `obs_publisher_did` = `ivo://irsa.ipac/spherex_dr1?<obs_id>/D<det>`;
ours is matched on (obs_id, detector), so a variable star's own changes cancel in each ratio. Statistics use pairs
where IRSA's flags have neither CONTAINS_BAD_PIXEL (bit 32) nor FIT_ERROR (bit 33), our point has no flag, and both
have S/N > 10.

**Results** are in `web/data/validation/spectro.json` and on the validation page (`#/guide/trust`, card "Our
spectra vs IRSA's official tool"). See the final report of this work item for the numbers of this run; re-run
after the DR1 rebuild:

```
SX_INSECURE=1 .venv/bin/python scripts/irsa_spectro_compare.py run        # IRSA jobs that are not cached, then compare
.venv/bin/python scripts/irsa_spectro_compare.py compare                  # compare only (offline)
.venv/bin/python scripts/irsa_spectro_compare.py compare barnard.new      # against a rebuilt field before it is swapped in
```

On Windows (PowerShell): `$env:SX_INSECURE = "1"; .venv\Scripts\python scripts\irsa_spectro_compare.py run`, and
likewise for `compare`.

The IRSA side is cached under `cache/irsa_spectro/<target>/<key>.{json,vot}` (key = position and time window), so
a field rebuild needs no new IRSA jobs unless IRSA's frame list changes.

## Source Discovery Tool

Not compared one to one. The tool's demo subtracts a D4 image from a reprojected D2 image of the same epoch and runs
SExtractor on the colour difference to pick red sources; it then extracts aperture spectra of chosen sources. Our
detections are (a) differences between epochs at matched wavelengths (asteroids) and (b) position changes between
pass stacks (proper motion); neither makes a static-source list to compare with. Its spectrum step (aperture radii
3–5 px, flux via the solid-angle pixel map, CONTAINS_BAD_PIXEL bits for flagging) is close to our aperture spectrum
and is covered by the R5 comparison against the official tool. SExtractor and `sep` are not installed here.
