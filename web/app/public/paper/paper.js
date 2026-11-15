/*
 * SPHEREx paper pages: header, scroll reveals, the section rail and — on the
 * project page — the PARALLAX stage. One rAF loop reads scroll positions and
 * writes styles directly, as on the SELENE cover.
 *
 * The stage (pinned, 380svh), by scroll progress p:
 *   0.00 – 0.18  a veil lifts off the lens
 *   0.08 – 0.24  PARALLAX resolves (tracking closes in), then yields at 0.42 – 0.52
 *   0.20 – 0.86  one year passes: Earth goes once round the Sun (inset), and a distant
 *                body traces its parallax loop plus a slow drift against the fixed stars;
 *                the three survey passes leave their detections behind
 *   0.86 – 1.00  everything falls away to black, where the page continues
 * The loop is exaggerated for legibility; the HUD says so.
 */
(function () {
  "use strict";
  document.documentElement.classList.remove("no-js");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const range = (v, a, b) => clamp((v - a) / (b - a));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => 1 - Math.pow(1 - t, 3);

  const subs = [];
  const loop = (t) => { subs.forEach((f) => f(t)); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);

  // Header turns solid once the page has moved.
  const bar = document.querySelector(".topbar");
  if (bar) subs.push(() => bar.classList.toggle("solid", window.scrollY > 40));

  // Reveal on first sight.
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
  }), { rootMargin: "0px 0px -8% 0px" });
  document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));

  // Section rail: progress bar and the section in view.
  const rail = document.querySelector(".rail");
  if (rail) {
    const links = [...rail.querySelectorAll("a[href^='#']")];
    const secs = links.map((a) => document.querySelector(a.getAttribute("href")));
    const fill = rail.querySelector(".bar i");
    const main = document.querySelector("main");
    subs.push(() => {
      const r = main.getBoundingClientRect();
      fill.style.transform = `scaleX(${clamp(-r.top / Math.max(1, r.height - innerHeight))})`;
      let on = 0;
      secs.forEach((s, i) => { if (s && s.getBoundingClientRect().top < innerHeight * 0.35) on = i; });
      links.forEach((a, i) => a.classList.toggle("on", i === on));
    });
  }

  // ---- the PARALLAX stage --------------------------------------------------
  const stage = document.querySelector(".stage");
  if (!stage) return;
  const pin = stage.querySelector(".pin");
  const cv = stage.querySelector("canvas");
  const ctx = cv.getContext("2d");
  const title = stage.querySelector(".title");
  const veil = stage.querySelector(".veil");
  const hud = stage.querySelector(".hud");
  const q = (s) => stage.querySelector(s);
  const clock = q("[data-clock]"), plx = q("[data-plx]"), dist = q("[data-dist]"), pass = q("[data-pass]");
  const D_TRUE = 500;                          // au, the body in the loop
  const PLX_AMP = 206265 / D_TRUE;             // arcsec, parallax amplitude for 1 au baseline

  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const stars = Array.from({ length: 420 }, () => ({ x: rnd(), y: rnd(), r: Math.pow(rnd(), 3) * 1.8 + 0.25, a: 0.25 + rnd() * 0.7, tw: rnd() * 6.28 }));
  const motes = Array.from({ length: 120 }, () => ({ x: rnd(), y: rnd(), r: 0.4 + rnd() * 1.6, s: 0.3 + rnd(), a: 0.2 + rnd() * 0.5 }));
  // Three survey passes, half a year apart (fractions of the year), each about two weeks long.
  const PASSES = [0.02, 0.52, 1.0];

  const size = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    cv.width = Math.round(cv.clientWidth * dpr); cv.height = Math.round(cv.clientHeight * dpr);
  };
  size(); new ResizeObserver(size).observe(cv);

  // Sky position of the body at year fraction f: parallax ellipse + linear drift (exaggerated).
  const sky = (f, W, H) => {
    const s = Math.min(W, H);
    const a = 2 * Math.PI * f;
    return { x: W * 0.56 + s * (0.17 * Math.sin(a) + 0.09 * (f - 0.5)), y: H * 0.47 + s * (0.075 * Math.cos(a) - 0.04 * (f - 0.5)) };
  };

  let last = 0;
  subs.push((time) => {
    const r = stage.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) return;
    const p = reduced ? 0.62 : clamp(-r.top / Math.max(1, r.height - innerHeight));
    const dt = last ? Math.min(0.1, (time - last) / 1000) : 1 / 60; last = time;
    const W = cv.clientWidth, H = cv.clientHeight, dpr = cv.width / Math.max(1, W);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const exit = range(p, 0.86, 1);
    const settle = ease(range(p, 0, 0.4));
    const f = ease(range(p, 0.2, 0.86));          // fraction of the year shown

    // Fixed background stars: they do not move between passes (that is the point).
    ctx.save();
    ctx.translate(0, -exit * H * 0.35);
    const zoom = lerp(1.12, 1, settle);
    ctx.translate(W / 2, H / 2); ctx.scale(zoom, zoom); ctx.translate(-W / 2, -H / 2);
    for (const s of stars) {
      const tw = reduced ? 1 : 0.75 + 0.25 * Math.sin(time / 900 + s.tw);
      ctx.globalAlpha = s.a * tw * (1 - exit);
      ctx.fillStyle = s.r > 1.4 ? "#f2e6c9" : "#dfe6f2";
      ctx.beginPath(); ctx.arc(s.x * W, s.y * H, s.r, 0, 6.283); ctx.fill();
    }

    // The parallax loop, drawn up to the current time.
    const draw = range(p, 0.2, 0.86);
    if (draw > 0) {
      ctx.globalAlpha = 0.55 * (1 - exit);
      ctx.strokeStyle = "#6fb6ff"; ctx.lineWidth = 1; ctx.setLineDash([3, 5]);
      ctx.beginPath();
      for (let i = 0; i <= 160; i++) {
        const ff = (i / 160) * f; const pt = sky(ff, W, H);
        i ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y);
      }
      ctx.stroke(); ctx.setLineDash([]);
      // Detections left behind by each pass that has happened.
      PASSES.forEach((pf, k) => {
        if (f < pf - 0.001) return;
        const pt = sky(pf, W, H);
        ctx.globalAlpha = (1 - exit);
        ctx.strokeStyle = "#f2e6c9"; ctx.lineWidth = 1;
        ctx.strokeRect(pt.x - 9, pt.y - 9, 18, 18);
        ctx.fillStyle = "#f2e6c9"; ctx.font = "500 10px 'IBM Plex Mono', monospace";
        ctx.fillText(`P${k + 1}`, pt.x + 13, pt.y - 10);
      });
    }

    // The body and its reticle.
    const b = sky(f, W, H);
    const show = range(p, 0.16, 0.26) * (1 - exit);
    if (show > 0) {
      ctx.globalAlpha = show;
      const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, 14);
      g.addColorStop(0, "rgba(111,182,255,0.9)"); g.addColorStop(1, "rgba(111,182,255,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(b.x, b.y, 14, 0, 6.283); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(b.x, b.y, 2.2, 0, 6.283); ctx.fill();
      ctx.strokeStyle = "rgba(111,182,255,0.9)"; ctx.lineWidth = 1;
      const R = 22, L = 7;
      [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
        ctx.beginPath();
        ctx.moveTo(b.x + sx * R, b.y + sy * (R - L)); ctx.lineTo(b.x + sx * R, b.y + sy * R); ctx.lineTo(b.x + sx * (R - L), b.y + sy * R);
        ctx.stroke();
      });
    }
    ctx.restore();

    // Inset: Earth's orbit seen from above, with the line of sight.
    const ins = range(p, 0.22, 0.32) * (1 - range(p, 0.8, 0.9));
    if (ins > 0) {
      const s = Math.min(W, H), cx = W - s * 0.17 - 24, cy = H - s * 0.17 - 64, R = s * 0.1;
      ctx.globalAlpha = ins;
      ctx.strokeStyle = "rgba(201,204,211,0.35)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.stroke();
      ctx.fillStyle = "#f2e6c9"; ctx.beginPath(); ctx.arc(cx, cy, 3.5, 0, 6.283); ctx.fill();
      const a = 2 * Math.PI * f - Math.PI / 2;
      const ex = cx + R * Math.cos(a), ey = cy + R * Math.sin(a);
      ctx.strokeStyle = "rgba(111,182,255,0.55)"; ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(cx, cy - s * 0.32); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#6fb6ff"; ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, 6.283); ctx.fill();
      ctx.fillStyle = "rgba(201,204,211,0.6)"; ctx.font = "500 10px 'IBM Plex Mono', monospace";
      ctx.fillText("SUN", cx + 7, cy + 4); ctx.fillText("EARTH · 1 AU", ex + 8, ey + 4);
    }
    ctx.globalAlpha = 1;

    // Lens dust, lifting with the veil.
    const v = 1 - range(p, 0, 0.18);
    if (v > 0.001) {
      ctx.fillStyle = "#dfe6f2";
      for (const m of motes) {
        if (!reduced) { m.x += 0.006 * m.s * dt; m.y -= 0.004 * m.s * dt; if (m.x > 1) m.x -= 1; if (m.y < 0) m.y += 1; }
        ctx.globalAlpha = m.a * v;
        ctx.beginPath(); ctx.arc(m.x * W, (m.y - p * 0.6) * H, m.r * (1 + p * 4), 0, 6.283); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    veil.style.opacity = String(v);
    veil.style.transform = `translate3d(0, ${-range(p, 0, 0.18) * 24}vh, 0) scale(${1 + range(p, 0, 0.18) * 0.25})`;

    // Title.
    const tIn = ease(range(p, 0.08, 0.24)), tOut = range(p, 0.42, 0.52);
    title.style.opacity = String(tIn * (1 - tOut));
    title.querySelector("h1").style.letterSpacing = `${lerp(0.6, 0.24, tIn)}em`;
    title.style.transform = `translate3d(0, ${-p * 6}vh, 0)`;
    title.style.filter = tIn < 0.99 ? `blur(${(1 - tIn) * 10}px)` : "";

    // Telemetry.
    hud.style.opacity = String(range(p, 0.02, 0.1) * (1 - range(p, 0.84, 0.92)));
    const day = Math.round(f * 365.25);
    clock.textContent = `T+ ${String(day).padStart(3, "0")} D`;
    const shift = PLX_AMP * Math.abs(Math.sin(Math.PI * f)) * 2;   // separation from the first pass, 2 au baseline
    plx.textContent = `${shift.toFixed(0)}″`;
    const k = PASSES.filter((pf) => f >= pf - 0.001).length;
    pass.textContent = `${k} / 3`;
    // With two passes a drift can absorb any displacement; the third pass separates distance from drift.
    dist.textContent = k < 3 ? "— au" : `${D_TRUE} au`;
    pin.style.background = "#05070c";
  });
})();
