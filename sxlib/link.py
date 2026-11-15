"""Link single-exposure detections into moving-object tracks.

link_linear  - fast movers within one survey pass: constant sky velocity.
fit_distant  - slow movers across passes ("Planet X"): a fixed barycentric position at
               distance d; the apparent motion is Earth's parallax. Grid-search d.

The distance grids are evaluated as arrays (all trial distances at once) rather than one
distance per Python iteration; the arithmetic per element is the same as the scalar form.
"""
import itertools

import astropy.units as u
import numpy as np
from astropy.coordinates import get_body_barycentric
from astropy.time import Time

ARCSEC_PER_RAD = 206264.8
PASS_DAYS = 90.0              # detections are put into survey passes by round((mjd - first) / 90 d)
EPOCH_H = 0.5                 # distinct "epochs" are 30-min bins
D_GRID_FIT = (30.0, 3000.0, 3000)       # fit_distant / distance_profile_ratio grid (geomspace)
N_GRID_LINK = 1500                      # link_groups / probe_distant grid size
PM_BOUND = np.sqrt(2.0)       # bound orbits: speed below escape = sqrt(2) x circular
_CHUNK = 512                  # trial distances (or pair rows) evaluated per array block


def _tangent(ra, dec, ra0, dec0):
    """Gnomonic projection (arcsec) about (ra0, dec0). Broadcasts."""
    ra, dec, ra0, dec0 = map(np.radians, (ra, dec, ra0, dec0))
    cd, sd, cd0, sd0 = np.cos(dec), np.sin(dec), np.cos(dec0), np.sin(dec0)
    cda = np.cos(ra - ra0)
    cosc = sd0 * sd + cd0 * cd * cda
    x = cd * np.sin(ra - ra0) / cosc
    y = (cd0 * sd - sd0 * cd * cda) / cosc
    return np.degrees(x) * 3600, np.degrees(y) * 3600


def _cols(dets, *keys):
    return [np.array([d[k] for d in dets], float) for k in keys]


def link_linear(dets, tol_arcsec=8.0, min_rate=0.5, max_rate=300.0, max_span_d=3.0,
                min_points=4, min_epochs=3):
    """dets: list of dicts with mjd, ra, dec (and anything else). Returns list of tracks
    {members: [det indices], rate_arcsec_h, pa_deg, rms_arcsec, span_h}.
    Defaults (>=4 detections over >=3 distinct 30-min epochs, 8" tolerance) were chosen on the
    65 Cybele field: looser settings produced dozens of chance alignments of artifacts."""
    if len(dets) < min_points:
        return []
    ra, dec, mjd = _cols(dets, "ra", "dec", "mjd")
    t = mjd * 24.0  # hours
    x, y = _tangent(ra, dec, np.median(ra), np.median(dec))
    order = np.argsort(t)
    ts = t[order]
    span = max_span_d * 24
    used = np.zeros(len(dets), bool)
    scored = []
    # every pair (a, b), b later than a by 0.5 h .. span, moving at min_rate..max_rate, seeds a straight line;
    # the members of each seed are the detections within tol of it (in pair order, as the scalar loop had them)
    for ai, a in enumerate(order[:-1]):
        dtv = ts[ai + 1:] - ts[ai]
        stop = np.flatnonzero(dtv > span)
        nb = stop[0] if stop.size else dtv.size
        bs, dtv = order[ai + 1:ai + 1 + nb], dtv[:nb]
        if not bs.size:
            continue
        # dt is t[b] - t[a] exactly as before (ts is t in time order)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.hypot(x[bs] - x[a], y[bs] - y[a]) / dtv
        ok = (dtv >= 0.5) & (min_rate <= v) & (v <= max_rate)
        if not ok.any():
            continue
        bs, dtv = bs[ok], dtv[ok]
        near = np.flatnonzero(np.abs(t - t[a]) <= span)
        if near.size < min_points:
            continue
        vx, vy = (x[bs] - x[a]) / dtv, (y[bs] - y[a]) / dtv
        tn = t[near] - t[a]
        for r0 in range(0, bs.size, _CHUNK):
            sl = slice(r0, r0 + _CHUNK)
            px = x[a] + vx[sl, None] * tn
            py = y[a] + vy[sl, None] * tn
            hit = np.hypot(x[near] - px, y[near] - py) <= tol_arcsec
            cnt = hit.sum(1)
            for k in np.flatnonzero(cnt >= min_points):
                scored.append((int(cnt[k]), a, bs[r0 + k], near[hit[k]]))
    scored.sort(key=lambda s: -s[0])
    tracks = []
    for _, a, b, mem in scored:
        mem = mem[~used[mem]]
        if len(mem) < min_points:
            continue
        if len(np.unique(np.round(t[mem] / EPOCH_H))) < min_epochs:
            continue
        # least-squares refit
        A = np.vstack([np.ones(len(mem)), t[mem] - t[mem].mean()]).T
        cx, *_ = np.linalg.lstsq(A, x[mem], rcond=None)
        cy, *_ = np.linalg.lstsq(A, y[mem], rcond=None)
        res = np.hypot(x[mem] - A @ cx, y[mem] - A @ cy)
        rate = np.hypot(cx[1], cy[1])
        if rate < min_rate or rate * np.ptp(t[mem]) < 2 * tol_arcsec:
            continue      # no significant motion within the pass: leave it for search_distant
        inl = res <= tol_arcsec
        keep = mem[inl]
        if len(keep) < min_points:
            continue
        used[keep] = True
        tracks.append({"members": [int(k) for k in keep], "rate_arcsec_h": float(rate),
                       "pa_deg": float(np.degrees(np.arctan2(cx[1], cy[1])) % 360),
                       "rms_arcsec": float(np.sqrt(np.mean(res[inl] ** 2))),
                       "span_h": float(np.ptp(t[keep]))})
    return tracks


def _earth(mjd):
    """Barycentric Earth position(s) (au), shape (n, 3)."""
    return get_body_barycentric("earth", Time(np.atleast_1d(mjd), format="mjd")).xyz.to(u.au).value.T


def _unit(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def circular_pm(d_au):
    """Angular rate (arcsec/yr) of a body on a circular heliocentric orbit at d_au seen from the
    Sun: v = 2*pi*d^-0.5 au/yr  ->  2*pi*d^-1.5 rad/yr. (~150"/yr at 420 au, ~116"/yr at 500 au.)"""
    return ARCSEC_PER_RAD * 2 * np.pi * np.asarray(d_au, float) ** -1.5


def _range(e0, u0, d_au):
    """Distance s along u0 from e0 to the sphere of radius d_au about the barycentre."""
    b = e0 @ u0
    return -b + np.sqrt(b * b - (e0 @ e0 - np.asarray(d_au, float) ** 2))


def _radec(v):
    """Direction (deg) of vectors v (..., 3)."""
    ra = np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360
    dec = np.degrees(np.arcsin(v[..., 2] / np.linalg.norm(v, axis=-1)))
    return ra, dec


def predict_distant(ra0, dec0, mjd0, d_au, mjd, earth=None, earth0=None, pm=(0.0, 0.0)):
    """Geocentric direction at mjd of a body seen at (ra0, dec0) at mjd0 at distance d_au, plus its own
    orbital motion as a linear drift pm = (mu_ra*cos(dec), mu_dec) in arcsec/yr (zero = fixed in space).
    earth / earth0: precomputed barycentric Earth positions (au) for mjd / mjd0."""
    e0 = _earth(mjd0)[0] if earth0 is None else earth0
    u0 = _unit(ra0, dec0)
    v = (e0 + _range(e0, u0, d_au) * u0)[None, :] - (_earth(mjd) if earth is None else earth)
    ra, dec = _radec(v)
    if pm[0] or pm[1]:
        dt = (np.atleast_1d(mjd) - mjd0) / 365.25
        dec = dec + pm[1] * dt / 3600
        ra = ra + pm[0] * dt / 3600 / np.cos(np.radians(dec))
    return ra, dec


def _predict_grid(ra0, dec0, e0, d_grid, E):
    """predict_distant (no drift) for every trial distance at once: (ra, dec), each (len(d_grid), len(E))."""
    u0 = _unit(ra0, dec0)
    s = _range(e0, u0, d_grid)
    pos = e0[None, :] + s[:, None] * u0[None, :]
    return _radec(pos[:, None, :] - E[None, :, :])


def _pm_fit(x, y, dt, d_au):
    """Least-squares drift through the reference epoch, limited to bound orbits at d_au."""
    w = float(dt @ dt)
    if w <= 0:
        return 0.0, 0.0
    mx, my = float(x @ dt) / w, float(y @ dt) / w
    cap = PM_BOUND * circular_pm(d_au)
    m = np.hypot(mx, my)
    if m > cap:
        mx, my = mx * cap / m, my * cap / m
    return mx, my


def _pm_fit_grid(x, y, dt, d_grid):
    """_pm_fit for rows x, y (nd, n) at distances d_grid (nd,)."""
    w = float(dt @ dt)
    if w <= 0:
        z = np.zeros(len(d_grid))
        return z, z
    mx, my = (x @ dt) / w, (y @ dt) / w
    cap = PM_BOUND * circular_pm(d_grid)
    m = np.hypot(mx, my)
    over = m > cap
    msafe = np.where(over, m, 1.0)
    return np.where(over, mx * cap / msafe, mx), np.where(over, my * cap / msafe, my)


def _rms_grid(dets, d_grid, with_pm=True):
    """(rms per trial distance, drift per trial distance) of detections about the parallax path through the
    earliest detection."""
    ra, dec, mjd = _cols(dets, "ra", "dec", "mjd")
    ref = int(np.argmin(mjd))
    dt = (mjd - mjd[ref]) / 365.25
    E = _earth(mjd)
    rms = np.empty(len(d_grid))
    pmx, pmy = np.zeros(len(d_grid)), np.zeros(len(d_grid))
    for c0 in range(0, len(d_grid), _CHUNK):
        dg = d_grid[c0:c0 + _CHUNK]
        pra, pdec = _predict_grid(ra[ref], dec[ref], E[ref], dg, E)
        x, y = _tangent(ra, dec, pra, pdec)
        if with_pm:
            mx, my = _pm_fit_grid(x, y, dt, dg)
        else:
            mx = my = np.zeros(len(dg))
        rms[c0:c0 + len(dg)] = np.sqrt(np.mean((x - mx[:, None] * dt) ** 2 + (y - my[:, None] * dt) ** 2, axis=1))
        pmx[c0:c0 + len(dg)], pmy[c0:c0 + len(dg)] = mx, my
    return rms, pmx, pmy


def _fit_grid():
    return np.geomspace(*D_GRID_FIT)


def fit_distant(dets, d_grid=None, with_pm=True):
    """Fit distance (and, with_pm, the body's own orbital motion) to detections from >=2 survey passes.
    Returns (d_au, rms_arcsec, (mu_ra*, mu_dec) arcsec/yr). The motion is solved linearly for every
    trial distance and capped at the escape speed, which is what separates it from parallax."""
    d_grid = np.asarray(d_grid if d_grid is not None else _fit_grid(), float)
    rms, pmx, pmy = _rms_grid(dets, d_grid, with_pm)
    r = np.where(np.isnan(rms), np.inf, rms)
    i = int(np.argmin(r))                 # first minimum, as the scalar loop's strict "<" picked
    if not r[i] < np.inf:
        return (np.nan, np.inf, (0.0, 0.0))
    return float(d_grid[i]), float(rms[i]), (round(float(pmx[i]), 2), round(float(pmy[i]), 2))


def distance_profile_ratio(dets, d_grid=None, sep=0.2):
    """Residual-profile diagnostic of a distant track: the lowest r.m.s. at any trial distance differing by more
    than `sep` (fractionally) from the best fit, divided by the best r.m.s. Values near 1 flag a distance-drift
    ambiguity. Returns (ratio, best_d, second_d)."""
    d_grid = np.asarray(d_grid if d_grid is not None else _fit_grid(), float)
    rms, _, _ = _rms_grid(dets, d_grid)
    i = int(np.argmin(rms))
    far = np.abs(d_grid / d_grid[i] - 1) > sep
    j = int(np.flatnonzero(far)[np.argmin(rms[far])])
    return float(rms[j] / max(rms[i], 1e-3)), float(d_grid[i]), float(d_grid[j])


def _stationary_groups(dets, idx, tol_arcsec, min_points=3, min_epochs=2):
    """Groups of >= min_points detections at one position (within tol) inside one pass."""
    sub = [dets[k] for k in idx]
    ra, dec, mjd = _cols(sub, "ra", "dec", "mjd")
    t = mjd * 24
    used = np.zeros(len(idx), bool)
    out = []
    for i in np.argsort(-np.array([d.get("p", 0) for d in sub])):
        if used[i]:
            continue
        x, y = _tangent(ra, dec, ra[i], dec[i])
        mem = np.flatnonzero((np.hypot(x, y) <= tol_arcsec) & ~used)
        if len(mem) >= min_points and len(np.unique(np.round(t[mem] / EPOCH_H))) >= min_epochs:
            used[mem] = True
            out.append([idx[m] for m in mem])
    return out


def _passes(mjd):
    return np.round((mjd - mjd.min()) / PASS_DAYS).astype(int)


def search_distant(dets, tol_arcsec=8.0, min_shift_px=3.0, d_range=(30, 3000), pix_arcsec=6.15, min_passes=3):
    """Distant bodies barely move within a ~2-week pass but shift between passes by Earth's parallax
    PLUS their own orbital motion (as large as the parallax at a few hundred au). 1) find stationary
    groups (>=3 detections, >=2 epochs) per pass; 2) for each trial distance, take groups from other
    passes that lie within reach of the parallax prediction given a bound orbit, fit one linear drift
    through them, and keep the set that leaves every group within tol. min_passes=3: with two passes
    any offset is explained by some drift, so distance and motion cannot be told apart.
    Returns tracks with members, d_au, rms_arcsec, pm_arcsec_yr, n_passes."""
    if len(dets) < 6:
        return []
    groups = pass_groups(dets, _passes(np.array([d["mjd"] for d in dets])), tol_arcsec)
    return absorb(link_groups(groups, dets, tol_arcsec, min_shift_px, d_range, pix_arcsec, min_passes), dets, tol_arcsec)


def _best_combo(cand, gpass, x, y, dt, tol_d, dau, sx, sy, min_shift, min_passes, max_combos=400):
    """Among the candidate groups (at most one per pass), the combination that one bound drift explains
    best: most passes within tolerance, then lowest rms. Trying every combination matters close in, where
    the drift is large and the group nearest the drift-free prediction is often not the body."""
    per = [np.flatnonzero(cand & (gpass == pz)) for pz in np.unique(gpass[cand])]
    if len(per) + 1 < min_passes:
        return None
    per = [p[np.argsort(np.hypot(x[p], y[p]))][:6] for p in per]      # keep the 6 nearest per pass
    shift = np.hypot(sx, sy)
    best = None
    for combo in itertools.islice(itertools.product(*per), max_combos):
        pick = np.array(combo)
        mx, my = _pm_fit(x[pick], y[pick], dt[pick], dau)
        r = np.hypot(x[pick] - mx * dt[pick], y[pick] - my * dt[pick])
        good = r <= tol_d[pick]
        ok = pick[good]
        if len(ok) + 1 < min_passes or not (shift[ok] >= min_shift).any():
            continue
        score = (len(ok), -float(np.sqrt(np.mean(r[good] ** 2))))
        if best is None or score > best[0]:
            best = (score, ok)
    return best


def _seeded_link(gi, gra, gdec, gpass, gmjd, E, grid, tol_arcsec, min_shift, min_passes, used=None):
    """Best (score, d_au, partner groups) over the distance grid for the group gi, or None. The drift-free
    predictions for all trial distances are computed at once; only distances with a candidate partner go on to
    the combination search."""
    dt = (gmjd - gmjd[gi]) / 365.25
    sx, sy = _tangent(gra, gdec, gra[gi], gdec[gi])
    free = gpass != gpass[gi]
    if used is not None:
        free &= ~used
    best = None
    for c0 in range(0, len(grid), _CHUNK):
        dg = grid[c0:c0 + _CHUNK]
        pra, pdec = _predict_grid(gra[gi], gdec[gi], E[gi], dg, E)
        X, Y = _tangent(gra, gdec, pra, pdec)
        tol = tol_arcsec + curvature_arcsec(dg[:, None], dt[None, :])
        reach = tol + PM_BOUND * circular_pm(dg)[:, None] * np.abs(dt)[None, :]
        C = (np.hypot(X, Y) <= reach) & free[None, :]
        for k in np.flatnonzero(C.any(1)):
            res = _best_combo(C[k], gpass, X[k], Y[k], dt, tol[k], dg[k], sx, sy, min_shift, min_passes)
            if res and (best is None or res[0] > best[0]):
                best = (res[0], dg[k], res[1])
    return best


def absorb(tracks, dets, tol_arcsec=8.0, max_iter=2, merge=True):
    """One body is often split into several groups per pass (many visits, long passes), so linking can
    return several partial tracks. For each track (largest first) take every detection on its fitted
    path (parallax + drift, with the curvature allowance), refit, and drop tracks already covered."""
    if not tracks:
        return tracks
    ra, dec, mjd = _cols(dets, "ra", "dec", "mjd")
    E = _earth(mjd)
    out, taken = [], set()
    for t in sorted(tracks, key=lambda t: -len(t["members"])):
        if len(set(t["members"]) & taken) >= 0.5 * len(t["members"]):
            continue
        mem, d, pm = list(t["members"]), t["d_au"], t.get("pm_arcsec_yr", (0.0, 0.0))
        for _ in range(max_iter):
            ref = min(mem, key=lambda k: mjd[k])
            pra, pdec = predict_distant(ra[ref], dec[ref], mjd[ref], d, mjd, E, E[ref], pm=pm)
            x, y = _tangent(ra, dec, pra, pdec)
            tol = tol_arcsec + curvature_arcsec(d, (mjd - mjd[ref]) / 365.25)
            new = [k for k in np.flatnonzero(np.hypot(x, y) <= tol) if k not in taken]
            # refinement may add detections but must not drop a whole observing window: the windows that were
            # linked are what separates distance from drift (a body near ~50 au departs from the linear-drift
            # path in the middle window by tens of arcsec, and losing it would leave two windows a year apart)
            if len(new) < len(t["members"]) * 0.8 or n_windows(mjd[new]) < n_windows(mjd[mem]):
                break
            mem = new
            d, rms, pm = fit_distant([dets[k] for k in mem])
        d, rms, pm = fit_distant([dets[k] for k in mem])
        taken.update(mem)
        smem = sorted(mem)
        out.append({**t, "members": [int(k) for k in smem], "d_au": d, "rms_arcsec": rms, "pm_arcsec_yr": pm,
                    "n_passes": n_windows(mjd[smem])})     # recount: absorbing can drop a whole pass
    if not merge:
        return out
    # merged pieces define a better path: collect every detection on it once more
    return absorb(merge_tracks(out, dets, tol_arcsec), dets, tol_arcsec, merge=False)


def merge_tracks(tracks, dets, tol_arcsec=8.0):
    """Pieces of one body (different visits picked by different links) agree when fitted together:
    merge two tracks when one distance + drift fits their union about as well as each alone."""
    tracks = sorted(tracks, key=lambda t: -len(t["members"]))
    mjd_min = min(x["mjd"] for x in dets) if dets else 0.0
    merged = True
    while merged and len(tracks) > 1:
        merged = False
        for a, b in itertools.combinations(range(len(tracks)), 2):
            A, B = tracks[a], tracks[b]
            mem = sorted(set(A["members"]) | set(B["members"]))
            d, rms, pm = fit_distant([dets[k] for k in mem])
            if rms <= tol_arcsec + float(curvature_arcsec(d, 1.0)):
                passes = {int(round((dets[k]["mjd"] - mjd_min) / PASS_DAYS)) for k in mem}
                tracks[a] = {**A, "members": mem, "d_au": d, "rms_arcsec": rms, "pm_arcsec_yr": pm, "n_passes": len(passes)}
                del tracks[b]
                merged = True
                break
    return tracks


def _group_arrays(groups):
    gra, gdec, gmjd = _cols(groups, "ra", "dec", "mjd")
    return gra, gdec, np.array([g["pass"] for g in groups]), gmjd, _earth(gmjd)


def link_groups(groups, dets, tol_arcsec=8.0, min_shift_px=3.0, d_range=(30, 3000), pix_arcsec=6.15, min_passes=3):
    """Link per-pass groups (each {pass, members, ra, dec, mjd}) across passes with one distance plus a
    bound orbital drift. Shared by search_distant (groups of single detections) and the shift-and-stack
    search (one stacked peak per group)."""
    if len({g["pass"] for g in groups}) < min_passes:
        return []
    gra, gdec, gpass, gmjd, E = _group_arrays(groups)
    grid = np.geomspace(*d_range, N_GRID_LINK)
    used = np.zeros(len(groups), bool)
    out = []
    for i in range(len(groups)):
        if used[i]:
            continue
        best = _seeded_link(i, gra, gdec, gpass, gmjd, E, grid, tol_arcsec, min_shift_px * pix_arcsec, min_passes, used)
        if best:
            gi = [i] + [int(k) for k in best[2]]
            mem = sorted({m for k in gi for m in groups[k]["members"]})
            d_fit, rms, pm = fit_distant([dets[m] for m in mem])
            # the groups line up at their mean positions, but every member must sit on one path too
            if rms > tol_arcsec + float(curvature_arcsec(d_fit, 1.0)):
                continue
            used[gi] = True
            out.append({"members": [int(m) for m in mem], "d_au": d_fit, "rms_arcsec": rms, "pm_arcsec_yr": pm,
                        "n_passes": len({groups[k]["pass"] for k in gi})})
    return out


def pass_groups(dets, passes, tol_arcsec=8.0, slow_rate=15.0, min_points=3, min_epochs=2):
    """Per-pass groups for distant-body linking. Beyond ~150 au a body is nearly stationary within a pass
    (stationary groups); closer in (tens of au) it drifts a few arcsec per hour by parallax, so slow
    straight tracklets (<= slow_rate "/h) count too. Each group is placed at its mean time."""
    ra_all, dec_all, mjd = _cols(dets, "ra", "dec", "mjd")
    groups = []
    for pz in np.unique(passes):
        idx = np.flatnonzero(passes == pz)
        # stationary groups first: beyond ~150 au a body stays within tol for a day or more, and in a field
        # with several such bodies (moving almost in parallel) slow tracklets would mix them
        taken = set()
        for g in _stationary_groups(dets, idx, tol_arcsec, min_points=min_points, min_epochs=min_epochs):
            taken.update(g)
            groups.append({"pass": int(pz), "members": g, "ra": np.mean(ra_all[g]),
                           "dec": np.mean(dec_all[g]), "mjd": float(np.mean(mjd[g])), "kind": "stationary"})
        rest = np.array([k for k in idx if k not in taken], int)
        if len(rest) < 4:
            continue
        sub = [dets[k] for k in rest]
        for tr in link_linear(sub, tol_arcsec, min_rate=0.5, max_rate=slow_rate, max_span_d=40.0, min_points=4, min_epochs=3):
            mem = [int(rest[m]) for m in tr["members"]]
            t0 = float(np.mean(mjd[mem]))
            # position at the mean time from the tracklet's own straight line
            tt = mjd[mem] - t0
            A = np.vstack([np.ones_like(tt), tt]).T
            cra = np.linalg.lstsq(A, ra_all[mem], rcond=None)[0][0]
            cde = np.linalg.lstsq(A, dec_all[mem], rcond=None)[0][0]
            groups.append({"pass": int(pz), "members": mem, "ra": float(cra), "dec": float(cde), "mjd": t0, "kind": "tracklet"})
    return groups


def n_windows(mjd, gap=40.0):
    """Number of observing windows (survey passes) spanned by a set of times: runs separated by > gap days."""
    m = np.sort(np.asarray(mjd, float))
    return int(1 + (np.diff(m) > gap).sum()) if m.size else 0


def curvature_arcsec(d_au, dt_yr):
    """How far a body on a circular orbit at d_au departs from a straight-line drift over dt_yr
    (~30" at 50 au over a year, negligible beyond a few hundred au)."""
    w = 2 * np.pi * np.asarray(d_au, float) ** -1.5
    return ARCSEC_PER_RAD * 0.5 * w * w * np.asarray(dt_yr) ** 2


def probe_distant(dets, seed, tol_arcsec=8.0, d_range=(30, 3000), min_passes=3, pix_arcsec=6.15):
    """'Could the detection `seed` be a distant planet?' Seeded version of search_distant: build the
    stationary groups of every pass, then ask whether groups in other passes line up with the seed's
    group under parallax + a bound orbit for one distance. Returns a dict with ok, reason and, when ok,
    d_au, pm_arcsec_yr, rms_arcsec, n_passes, members (indices into dets)."""
    mjd = np.array([d["mjd"] for d in dets])
    passes = _passes(mjd)
    n_pass_total = len(np.unique(passes))
    if n_pass_total < min_passes:
        return {"ok": False, "reason": "few_passes", "n_passes_field": int(n_pass_total)}
    groups = pass_groups(dets, passes, tol_arcsec, min_points=2, min_epochs=1)
    # the seed's own group (or the seed alone)
    gi = next((k for k, g in enumerate(groups) if seed in g["members"]), None)
    if gi is None:
        groups.append({"pass": int(passes[seed]), "members": [seed], "ra": dets[seed]["ra"], "dec": dets[seed]["dec"], "mjd": float(mjd[seed])})
        gi = len(groups) - 1
    gra, gdec, gpass, gmjd, E = _group_arrays(groups)
    best = _seeded_link(gi, gra, gdec, gpass, gmjd, E, np.geomspace(*d_range, N_GRID_LINK), tol_arcsec,
                        3 * pix_arcsec, min_passes)
    if not best:
        return {"ok": False, "reason": "no_parallax_partner", "n_passes_field": int(n_pass_total)}
    mem = sorted({m for k in [gi, *best[2]] for m in groups[k]["members"]})
    d_fit, rms, pm = fit_distant([dets[m] for m in mem])
    if rms > 3 * (tol_arcsec + float(curvature_arcsec(d_fit, 1.0))):
        return {"ok": False, "reason": "poor_fit", "n_passes_field": int(n_pass_total)}
    return {"ok": True, "d_au": round(d_fit, 1), "pm_arcsec_yr": list(pm), "rms_arcsec": round(rms, 2),
            "n_passes": len({groups[k]["pass"] for k in [gi, *best[2]]}), "members": [int(m) for m in mem]}
