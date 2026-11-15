"""WiseView-style tools of the lab (web/app/src/shiftadd.js, UPGRADE_PLAN.md §10 R7), run under node, offline.

  - float16 decoding of the pass stacks;
  - shift-and-add: a synthetic star moving across three passes piles up only along its own motion;
  - sky motion <-> field pixels through the local Jacobian of a TAN projection;
  - brightness map: percentiles, linear / asinh, invert;
  - the "spot the fake mover" puzzle: reproducible from its seed, the star where it says and as bright as it says;
  - on the real stacks (if present): WISE 0855 in D6 is sharper along its catalogue motion than without it or reversed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "web" / "app" / "src" / "shiftadd.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run(js):
    """Run an ES module snippet with `SA` = shiftadd.js; it prints one JSON value."""
    code = f"const SA = await import({json.dumps(MOD.as_uri())});\n{js}"
    r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_float16():
    v = run("console.log(JSON.stringify(Array.from(SA.f16(new Uint16Array([0x3c00, 0xc000, 0x3555, 0x0000, 0x7c00, 0x0001])))))")
    assert v[0] == 1.0 and v[1] == -2.0 and abs(v[2] - 0.33325) < 1e-4 and v[3] == 0.0
    assert v[4] is None or v[4] > 1e30          # JSON turns Infinity into null
    assert 0 < v[5] < 1e-7                       # smallest subnormal


def test_shift_and_add_piles_up_a_mover():
    js = """
    const n = 41, times = [60000, 60182.6, 60365.25], v = { vx: 1.6, vy: -0.8 }        // pixels per year
    const tref = times.reduce((s, t) => s + t, 0) / 3
    const frames = times.map((t) => { const f = new Float32Array(n * n); SA.addGaussian(f, n, 20 + v.vx * (t - tref) / 365.25, 20 + v.vy * (t - tref) / 365.25, 10); SA.addGaussian(f, n, 8, 30, 10); return f })
    const pk = (im, x, y) => SA.peakNear(im, n, x, y, 1.5)
    const zero = SA.shiftAdd(frames, n, times, { vx: 0, vy: 0 }), right = SA.shiftAdd(frames, n, times, v), wrong = SA.shiftAdd(frames, n, times, { vx: -v.vx, vy: -v.vy })
    const box = SA.shiftAdd(frames, n, times, v, 'mean', [15, 15, 25, 25])
    console.log(JSON.stringify({ zero: pk(zero, 20, 20), right: pk(right, 20, 20), wrong: pk(wrong, 20, 20), staticZero: pk(zero, 8, 30), staticRight: pk(right, 8, 30),
      median: pk(SA.shiftAdd(frames, n, times, v, 'median'), 20, 20), boxSame: box[20 * n + 20] === right[20 * n + 20], boxOutside: box[0] }))
    """
    r = run(js)
    # the three passes line up; bilinear shifts by fractions of a pixel blur a 0.65-pixel star a little, so the peak
    # is ~7.7 of 10 rather than 10 (and the unshifted sum ~5.9)
    assert r["right"] > 7.0, r
    assert r["zero"] < 0.85 * r["right"], r          # unshifted, the mover smears
    assert r["wrong"] < r["zero"], r                 # the opposite motion smears it twice as much
    assert r["staticZero"] > 9.9 and r["staticRight"] < 0.75 * r["staticZero"], r   # and a still star the other way round
    assert r["median"] > r["zero"] and r["boxSame"] and r["boxOutside"] is None, r


def test_motion_through_the_wcs():
    js = """
    // a TAN projection like the fields': 6.15 arcsec pixels, x to the west, y to the north, at Dec -56.8
    const d2r = Math.PI / 180, cd = 6.15 / 3600, ra0 = 331.1, dec0 = -56.8
    const world = (x, y) => { const xi = -(x - 50) * cd * d2r, eta = (y - 50) * cd * d2r, d0 = dec0 * d2r, den = Math.cos(d0) - eta * Math.sin(d0)
      return [(ra0 + Math.atan2(xi, den) / d2r + 360) % 360, Math.atan2(Math.sin(d0) + eta * Math.cos(d0), Math.hypot(xi, den)) / d2r] }
    const J = SA.jacobian(world, 50, 50), v = SA.motionToPix(J, 3.98, -2.47), back = SA.pixToMotion(J, v.vx, v.vy)
    console.log(JSON.stringify({ J, v, back }))
    """
    r = run(js)
    assert abs(r["J"][0][0] + 6.15) < 0.01 and abs(r["J"][1][1] - 6.15) < 0.01, r
    assert abs(r["v"]["vx"] + 3.98 / 6.15) < 0.01 and abs(r["v"]["vy"] + 2.47 / 6.15) < 0.01, r   # east is -x, north is +y
    assert abs(r["back"]["east"] - 3.98) < 1e-6 and abs(r["back"]["north"] + 2.47) < 1e-6, r


def test_brightness_map():
    js = """
    const a = Float32Array.from({ length: 1001 }, (_, k) => k)
    const lin = SA.stretchMap(a, { lo: 10, hi: 90, stretch: 'linear', invert: false }), inv = SA.stretchMap(a, { lo: 10, hi: 90, stretch: 'linear', invert: true })
    const ash = SA.stretchMap(a, { lo: 10, hi: 90, stretch: 'asinh', invert: false })
    console.log(JSON.stringify({ l: [lin(100), lin(500), lin(900), lin(NaN)], i: [inv(100), inv(900), inv(NaN)], a: [ash(100), ash(300), ash(900)] }))
    """
    r = run(js)
    near = lambda a, b: abs(a - b) < 1e-6  # noqa: E731
    assert near(r["l"][0], 0) and abs(r["l"][1] - 127.5) < 1 and near(r["l"][2], 255) and r["l"][3] == 0
    assert near(r["i"][0], 255) and near(r["i"][1], 0) and r["i"][2] == 255
    assert near(r["a"][0], 0) and r["a"][1] > 255 * 0.25 and near(r["a"][2], 255)     # asinh lifts the faint end above linear


def test_fake_mover_puzzle():
    js = """
    const n = 120, R0 = SA.rng(7)
    // three passes of pure noise (sigma 1) on a flat background of 5
    const g = () => { let s = 0; for (let k = 0; k < 12; k++) s += R0(); return s - 6 }
    const frames = [0, 1, 2].map(() => Float32Array.from({ length: n * n }, () => 5 + g()))
    const times = [60800, 60980, 61160]
    const a = SA.makePuzzle(SA.rng(42), frames, n, times, 'easy'), b = SA.makePuzzle(SA.rng(42), frames, n, times, 'easy'), h = SA.makePuzzle(SA.rng(9), frames, n, times, 'hard')
    const at = (p, k) => { const q = p.track[k]; return p.frames[k][Math.round(q.y) * p.C + Math.round(q.x)] - 5 }
    console.log(JSON.stringify({ same: JSON.stringify(a.track) === JSON.stringify(b.track), C: a.C, track: a.track, shift: a.shift, snr: a.snr, sig: a.sig, peak: [0, 1, 2].map((k) => at(a, k)),
      hard: { shift: h.shift, snr: h.snr }, d0: SA.trackDistance(a.track, a.track[1].x, a.track[1].y), d3: SA.trackDistance(a.track, a.track[1].x + 3, a.track[1].y),
      noisy: SA.makePuzzle(SA.rng(1), frames.map((f) => f.map(() => NaN)), n, times) }))
    """
    r = run(js)
    assert r["same"] and r["C"] == 32
    assert all(4 <= q["x"] <= 27 and 4 <= q["y"] <= 27 for q in r["track"]), r["track"]
    span = ((r["track"][2]["x"] - r["track"][0]["x"]) ** 2 + (r["track"][2]["y"] - r["track"][0]["y"]) ** 2) ** 0.5
    assert abs(span - r["shift"]) < 1e-6 and 2.0 <= r["shift"] <= 3.2 and 14 <= r["snr"] <= 24
    assert 0.8 < r["sig"] < 1.2                                  # the noise it measured
    assert all(p > 0.45 * r["snr"] * r["sig"] for p in r["peak"]), r["peak"]   # the star is there in every pass
    assert 0.9 <= r["hard"]["shift"] <= 1.6 and 6 <= r["hard"]["snr"] <= 9
    assert r["d0"] < 1e-9 and abs(r["d3"] - 3) < 1.0
    assert r["noisy"] is None                                    # no clean cut, no puzzle


def test_real_stacks_wise0855():
    f = ROOT / "web" / "data" / "fields" / "wise0855"
    if not (f / "pass" / "stacks_g6.bin").exists():
        pytest.skip("no WISE 0855 stacks here")
    js = f"""
    import('node:fs').then(({{ readFileSync }}) => {{
      const field = JSON.parse(readFileSync({json.dumps(str(f / 'field.json'))}))
      const n = field.shape[0], P = field.products.passes.length, tg = field.target
      const raw = readFileSync({json.dumps(str(f / 'pass' / 'stacks_g6.bin'))})
      const a = SA.f16(new Uint16Array(raw.buffer, raw.byteOffset, P * n * n)), frames = Array.from({{ length: P }}, (_, p) => a.subarray(p * n * n, (p + 1) * n * n))
      const times = SA.passTimes(field.products.passes, field.exposures)
      const x = tg.passes.reduce((s, q) => s + q.x, 0) / P, y = tg.passes.reduce((s, q) => s + q.y, 0) / P
      const w = field.wcs, d2r = Math.PI / 180
      const world = (px, py) => {{ const xi = (px + 1 - w.crpix[0]) * w.cdelt[0] * d2r, eta = (py + 1 - w.crpix[1]) * w.cdelt[1] * d2r, a0 = w.crval[0] * d2r, d0 = w.crval[1] * d2r, den = Math.cos(d0) - eta * Math.sin(d0)
        return [((a0 + Math.atan2(xi, den)) / d2r + 360) % 360, Math.atan2(Math.sin(d0) + eta * Math.cos(d0), Math.hypot(xi, den)) / d2r] }}
      const v = SA.motionToPix(SA.jacobian(world, x, y), tg.pmra / 1000, tg.pmdec / 1000)
      const pk = (m) => SA.peakNear(SA.shiftAdd(frames, n, times, m), n, x, y)
      console.log(JSON.stringify({{ zero: pk({{ vx: 0, vy: 0 }}), cat: pk(v), rev: pk({{ vx: -v.vx, vy: -v.vy }}) }}))
    }})
    """
    r = run(js)
    assert r["cat"] > 1.1 * r["zero"] and r["cat"] > 1.3 * r["rev"], r
