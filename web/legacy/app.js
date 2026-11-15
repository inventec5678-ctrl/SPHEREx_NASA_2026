"use strict";
// SPHEREx Sky Change Explorer - front end (no build step).

const DET_INFO = {
  1: { c: "#7aa8ff", r: "0.75–1.1 µm" }, 2: { c: "#6fe0d4", r: "1.1–1.6 µm" }, 3: { c: "#9be37a", r: "1.6–2.4 µm" },
  4: { c: "#f2d46b", r: "2.4–3.8 µm" }, 5: { c: "#f5a25d", r: "3.8–4.4 µm" }, 6: { c: "#ef6f6c", r: "4.4–5.0 µm" },
};
const $ = (s) => document.querySelector(s);
const S = {
  fields: [], field: null, frames: [], cur: 0, playing: false, timer: null, mode: "sky",
  dets: new Set([1, 2, 3, 4, 5, 6]), sel: null, imgs: new Map(), lut: null, votes: {},
};
const SCALE = 2;                 // screen pixels per field pixel
const PREFETCH = 8;              // frames loaded ahead of the one shown
const PASS_GAP_D = 40;           // exposures closer than this (days) belong to one survey pass
const MJD_UNIX0 = 40587;
const PIX_ARCSEC = 6.15;
const AU_ARCSEC = 206265;
const STRIP_N = 7;               // stamps per track

// ------------------------------------------------------------------ data
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function init() {
  buildDetChips();
  bindUI();
  drawParallaxCalc();
  loadMetrics();
  S.fields = await api("/api/fields");
  const sel = fillFieldSelect();
  const want = new URLSearchParams(location.hash.slice(1)).get("field");
  const first = S.fields.find((f) => f.id === want) || S.fields[0];
  if (first) { sel.value = first.id; await loadField(first.id); }
  else $("#fieldName").textContent = "No fields processed yet";
}

function fillFieldSelect() {
  const sel = $("#fieldSel");
  sel.replaceChildren(...S.fields.map((f) => new Option(`${f.name}${f.simulated ? "  (simulation)" : ""}`, f.id)));
  return sel;
}

async function loadField(id) {
  stop();
  const f = await api(`/api/field/${id}`);
  S.field = f; S.sel = null; S.imgs.clear();
  f.byExp = new Map();
  for (const c of f.candidates) {
    if (!f.byExp.has(c.i)) f.byExp.set(c.i, []);
    f.byExp.get(c.i).push(c);
  }
  f.cand = new Map(f.candidates.map((c) => [c.id, c]));
  f.simByExp = new Map((f.simulated_truth || []).map((t) => [t.i, t]));
  S.tl = null;
  history.replaceState(null, "", `#field=${id}`);
  $("#fieldName").textContent = f.name;
  $("#fieldDesc").textContent = f.description || "";
  renderStats();
  S.votes = await api(`/api/reports/${id}`).catch(() => ({}));
  renderTracks();
  renderDistant();
  setFrames();
}

function renderStats() {
  const f = S.field;
  const fast = f.tracks.filter((t) => t.kind === "fast");
  const unk = f.tracks.filter((t) => !t.known);
  const items = [
    [f.exposures.length, "images"],
    [`${f.exposures[0].iso.slice(0, 7)} → ${f.exposures.at(-1).iso.slice(0, 7)}`, "time span"],
    [fast.length, "moving objects"],
    [unk.length, "unidentified"],
  ];
  $("#fieldStats").innerHTML = items.map(([v, k]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join("");
}

// ------------------------------------------------------------------ frames
function setFrames(keep) {
  const f = S.field;
  let ex = f.exposures.filter((e) => S.dets.has(e.detector) && e.coverage > 0.2);
  if (S.sel !== null) {
    const t = f.tracks[S.sel];
    const set = new Set(t.members.map((m) => f.cand.get(m).i));
    ex = f.exposures.filter((e) => set.has(e.i));
  }
  const prev = S.frames[S.cur];
  S.frames = ex.map((e) => e.i);
  S.cur = keep && prev !== undefined ? Math.max(0, S.frames.indexOf(prev)) : 0;
  const sl = $("#frameSlider");
  sl.max = Math.max(0, S.frames.length - 1);
  sl.value = S.cur;
  draw();
}

function frameImg(kind, i) {
  const key = `${kind}${i}`;
  if (!S.imgs.has(key)) {
    const im = new Image();
    im.src = `/data/fields/${S.field.id}/${kind}/${String(i).padStart(4, "0")}.webp`;
    im.onload = () => { if (S.frames[S.cur] === i) draw(); refreshStrips(i); };
    S.imgs.set(key, im);
  }
  return S.imgs.get(key);
}

function prefetch() {
  const kind = S.mode === "sky" ? "sci" : "diff";
  for (let k = 1; k <= PREFETCH; k++) {
    const i = S.frames[(S.cur + k) % S.frames.length];
    if (i !== undefined) frameImg(kind, i);
  }
}

// grey level -> packed RGBA (one 32-bit write per pixel when colouring a difference frame)
function diffLUT() {
  if (S.lut) return S.lut;
  const lut = new Uint32Array(256), px = new Uint8ClampedArray(lut.buffer);
  for (let v = 0; v < 256; v++) {
    const snr = (v - 128) / 16;                         // the frame encodes 128 + 16*S/N
    const a = Math.min(1, Math.max(0, (Math.abs(snr) - 1.5) / 6.5)) ** 0.8;  // |S/N|<1.5 stays dark
    if (snr >= 0) px.set([14 + 241 * a, 16 + 170 * a, 24 + 30 * a, 255], v * 4);
    else px.set([14 + 40 * a, 16 + 120 * a, 24 + 230 * a, 255], v * 4);
  }
  return (S.lut = lut);
}

const work = document.createElement("canvas");
let workKey = null;              // the difference frame currently coloured in `work`
function colourDiff(im, W, H) {
  if (workKey === im.src) return;
  work.width = W; work.height = H;
  const w = work.getContext("2d", { willReadFrequently: true });
  w.drawImage(im, 0, 0);
  const d = w.getImageData(0, 0, W, H), lut = diffLUT();
  const src = d.data, out = new Uint32Array(src.buffer);
  for (let p = 0, q = 0; q < out.length; p += 4, q++) out[q] = lut[src[p]];
  w.putImageData(d, 0, 0);
  workKey = im.src;
}

function draw() {
  const f = S.field;
  const sky = $("#sky"), ov = $("#overlay");
  const [H, W] = f.shape;
  for (const c of [sky, ov]) if (c.width !== W * SCALE || c.height !== H * SCALE) { c.width = W * SCALE; c.height = H * SCALE; }
  const ctx = sky.getContext("2d");
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, sky.width, sky.height);
  const i = S.frames[S.cur];
  const o = ov.getContext("2d");
  o.clearRect(0, 0, ov.width, ov.height);
  if (i === undefined) { $("#frameLabel").textContent = "no images for these detectors"; return; }
  const e = f.exposures[i];
  const im = frameImg(S.mode === "sky" ? "sci" : "diff", i);
  if (im.complete && im.naturalWidth) {
    ctx.imageSmoothingEnabled = false;
    if (S.mode === "sky") ctx.drawImage(im, 0, 0, sky.width, sky.height);
    else {
      colourDiff(im, W, H);
      ctx.drawImage(work, 0, 0, sky.width, sky.height);
    }
  }
  drawOverlay(o, i);
  $("#hudTime").textContent = `${e.iso} UTC`;
  $("#hudBand").innerHTML = `<span style="color:${DET_INFO[e.detector].c}">● D${e.detector}</span> ${e.lam_um.toFixed(2)} µm`;
  $("#frameLabel").textContent = `${S.cur + 1} / ${S.frames.length}`;
  $("#frameSlider").value = S.cur;
  drawTimeline();
  prefetch();
}

const px = (x) => (x + 0.5) * SCALE;
const py = (y) => (S.field.shape[0] - 0.5 - y) * SCALE;

function drawOverlay(o, i) {
  const f = S.field;
  const thr = f.p_link || 0.5;
  o.lineWidth = 1.5;
  if ($("#showTracks").checked) {
    const tracks = S.sel !== null ? [f.tracks[S.sel]] : f.tracks;
    for (const t of tracks) {
      const pts = t.members.map((m) => f.cand.get(m)).sort((a, b) => a.i - b.i);
      o.strokeStyle = t.kind === "distant" ? "#c08bffaa" : t.known ? "#6ec3ff88" : "#ffb547aa";
      o.setLineDash([4, 4]);
      o.beginPath();
      pts.forEach((c, k) => (k ? o.lineTo(px(c.x), py(c.y)) : o.moveTo(px(c.x), py(c.y))));
      o.stroke();
      o.setLineDash([]);
    }
  }
  for (const c of f.byExp.get(i) || []) {
    const inSel = S.sel !== null && c.track === S.sel;
    if (!inSel && S.sel !== null) continue;
    if (c.known && $("#showKnown").checked) {
      ring(o, c, 11, "#6ec3ff");
      o.fillStyle = "#6ec3ff"; o.font = "12px system-ui";
      o.fillText(c.known.replace(/\s*\(.*\)/, ""), px(c.x) + 14, py(c.y) - 8);
    } else if ($("#showCands").checked && (c.p >= thr || inSel)) {
      const col = c.track !== null && c.track !== undefined
        ? (f.tracks[c.track].kind === "distant" ? "#c08bff" : "#ffb547") : `rgba(255,255,255,${0.35 + 0.6 * c.p})`;
      ring(o, c, inSel ? 13 : 9, col);
    }
  }
  const sim = f.simByExp.get(i);
  if (sim && S.revealSim) { ring(o, sim, 16, "#ff4fd8"); }
}

function ring(o, c, r, col) {
  o.strokeStyle = col;
  o.beginPath(); o.arc(px(c.x), py(c.y), r, 0, Math.PI * 2); o.stroke();
}

// survey passes laid out across the timeline with the long gaps between them compressed (per field and width)
function timelineLayout(f, W) {
  if (S.tl && S.tl.W === W) return S.tl;
  const passes = [];
  for (const m of f.exposures.map((e) => e.mjd).sort((a, b) => a - b)) {
    const p = passes.at(-1);
    if (p && m - p.end < PASS_GAP_D) p.end = m; else passes.push({ start: m, end: m });
  }
  const gap = 0.04 * W, usable = W - gap * (passes.length - 1);
  const tot = passes.reduce((s, p) => s + Math.max(p.end - p.start, 1), 0);
  let x0 = 0;
  for (const p of passes) { p.x0 = x0; p.w = usable * Math.max(p.end - p.start, 1) / tot; x0 += p.w + gap; }
  const X = (m) => { const p = passes.find((q) => m >= q.start - 1e-6 && m <= q.end + 1e-6); return p.x0 + p.w * (m - p.start) / Math.max(p.end - p.start, 1); };
  return (S.tl = { W, passes, X });
}

function drawTimeline() {
  const cv = $("#timeline"), f = S.field;
  if (!f) return;
  const W = cv.clientWidth * devicePixelRatio, H = 38 * devicePixelRatio;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext("2d");
  g.clearRect(0, 0, W, H);
  const { passes, X } = timelineLayout(f, W);
  S.tlX = X; S.tlPasses = passes;
  g.font = `${10 * devicePixelRatio}px system-ui`;
  for (const p of passes) {
    g.fillStyle = "#141c2e"; g.fillRect(p.x0, 14 * devicePixelRatio, p.w, H - 14 * devicePixelRatio);
    g.fillStyle = "#8b98b3";
    const d = new Date((p.start - MJD_UNIX0) * 86400e3);
    g.fillText(d.toISOString().slice(0, 7), p.x0 + 2, 11 * devicePixelRatio);
  }
  const shown = new Set(S.frames);
  for (const e of f.exposures) {
    const x = X(e.mjd);
    g.fillStyle = shown.has(e.i) ? DET_INFO[e.detector].c : "#2a3550";
    g.fillRect(x, (16 + (e.detector - 1) * 3.5) * devicePixelRatio, 1.5 * devicePixelRatio, 3 * devicePixelRatio);
  }
  const cur = f.exposures[S.frames[S.cur]];
  if (cur) { g.fillStyle = "#fff"; g.fillRect(X(cur.mjd) - devicePixelRatio, 13 * devicePixelRatio, 2 * devicePixelRatio, H); }
}

// ------------------------------------------------------------------ tracks
function trackTitle(t) {
  if (t.kind === "distant") return `Distant-body candidate #${t.id}`;
  return t.known ? t.known : `Unidentified mover #${t.id}`;
}

function renderTracks() {
  const f = S.field, ol = $("#trackList");
  ol.innerHTML = "";
  let list = f.tracks.filter((t) => t.kind === "fast");
  if ($("#onlyUnknown").checked) list = list.filter((t) => !t.known);
  list.sort((a, b) => (!!a.known - !!b.known) || b.mean_p - a.mean_p);
  $("#trackCount").textContent = `${list.length} shown`;
  $("#noTracks").hidden = list.length > 0;
  for (const t of list) ol.append(trackItem(t));
}

function renderDistant() {
  const f = S.field, ol = $("#distantList");
  ol.innerHTML = "";
  const list = f.tracks.filter((t) => t.kind === "distant");
  $("#noDistant").hidden = list.length > 0;
  for (const t of list) ol.append(trackItem(t));
  const box = $("#simBox");
  if (f.simulated && f.simulated.length) {
    const s = f.simulated[0];
    const fit = list.map((t) => t.d_au);
    box.hidden = false;
    box.innerHTML = `<strong>This field contains a simulated planet.</strong> We injected a body at
      <b>${s.d_au.toFixed(0)} AU</b> (AB mag ${s.mag_ab.toFixed(1)}) into the real images, using SPHEREx's own PSF.
      ${fit.length ? `The pipeline recovered a distant-body track at <b>${fit.map((d) => d.toFixed(0)).join(", ")} AU</b>.` :
      "The pipeline did not link it this time."}
      <br><label><input type="checkbox" id="revealSim"> Reveal the injected position</label>`;
    $("#revealSim").onchange = (ev) => { S.revealSim = ev.target.checked; draw(); };
  } else box.hidden = true;
}

function trackItem(t) {
  const f = S.field;
  const li = $("#trackTpl").content.firstElementChild.cloneNode(true);
  li.dataset.id = t.id;
  const badge = li.querySelector(".badge");
  badge.textContent = t.kind === "distant" ? "parallax" : t.known ? "known" : "unknown";
  badge.classList.add(t.kind === "distant" ? "distant" : t.known ? "known" : "x");
  li.querySelector(".title").textContent = trackTitle(t);
  const n = t.members.length;
  li.querySelector(".meta").textContent = t.kind === "distant"
    ? `${n} detections · ${t.n_passes} survey passes · fitted distance ${t.d_au} AU · AI ${(t.mean_p * 100).toFixed(0)}%`
    : `${n} detections · ${t.rate_arcsec_h}″/h · over ${t.span_h} h · from ${t.start} · AI ${(t.mean_p * 100).toFixed(0)}%` +
      (t.l2_frac != null ? ` · SPHEREx outlier flag ${(t.l2_frac * 100).toFixed(0)}%` : "");
  const strip = li.querySelector(".strip");
  const mem = t.members.map((m) => f.cand.get(m)).sort((a, b) => a.i - b.i);
  const step = Math.max(1, Math.floor(mem.length / STRIP_N));
  for (let k = 0; k < mem.length && strip.children.length < STRIP_N; k += step) {
    const cv = document.createElement("canvas");
    cv.width = cv.height = 21 * 3; cv.dataset.cand = mem[k].id;
    strip.append(cv);
    drawStamp(cv, mem[k]);
  }
  li.querySelector(".trk").onclick = () => selectTrack(t.id);
  const vote = li.querySelector(".vote");
  vote.querySelectorAll("button").forEach((b) => (b.onclick = () => sendVote(t.id, b.dataset.v, li)));
  showTally(li, t.id);
  return li;
}

function drawStamp(cv, c) {
  const im = frameImg("sci", c.i);
  const g = cv.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.fillStyle = "#000"; g.fillRect(0, 0, cv.width, cv.height);
  if (!(im.complete && im.naturalWidth)) return;
  const H = S.field.shape[0];
  g.drawImage(im, Math.round(c.x) - 10, H - 1 - Math.round(c.y) - 10, 21, 21, 0, 0, cv.width, cv.height);
  g.strokeStyle = "#ffb54799"; g.beginPath(); g.arc(cv.width / 2, cv.height / 2, 9, 0, 7); g.stroke();
}

function refreshStrips(i) {
  document.querySelectorAll(".strip canvas").forEach((cv) => {
    const c = S.field.cand.get(+cv.dataset.cand);
    if (c && c.i === i) drawStamp(cv, c);
  });
}

function selectTrack(id) {
  const f = S.field;
  S.sel = S.sel === id ? null : id;
  document.querySelectorAll(".track").forEach((li) => {
    const on = +li.dataset.id === S.sel;
    li.classList.toggle("sel", on);
    li.querySelector(".vote").hidden = !on;
  });
  $("#trackBanner").hidden = S.sel === null;
  if (S.sel !== null) {
    const t = f.tracks[S.sel];
    $("#trackBannerText").textContent = `Following ${trackTitle(t)}: ${t.members.length} detections`;
  }
  setFrames();
  if (S.sel !== null) play();
}

async function sendVote(track, verdict, li) {
  S.votes = await api("/api/report", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field: S.field.id, track, verdict }),
  });
  showTally(li, track, true);
}

function showTally(li, track, thanks) {
  const v = S.votes[String(track)];
  li.querySelector(".tally").textContent = v
    ? `${thanks ? "Thanks! " : ""}${v.real} real · ${v.artifact} artifact · ${v.unsure} unsure` : "";
}

// ------------------------------------------------------------------ playback
function play() {
  if (S.frames.length < 2) return;
  S.playing = true; $("#playBtn").textContent = "❚❚";
  clearInterval(S.timer);
  S.timer = setInterval(() => { S.cur = (S.cur + 1) % S.frames.length; draw(); }, 1000 / +$("#speed").value);
}
function stop() { S.playing = false; clearInterval(S.timer); $("#playBtn").textContent = "▶"; }
function step(d) { stop(); S.cur = (S.cur + d + S.frames.length) % S.frames.length; draw(); }

// ------------------------------------------------------------------ UI wiring
function buildDetChips() {
  const box = $("#detChips");
  for (const d of [1, 2, 3, 4, 5, 6]) {
    const b = document.createElement("button");
    b.className = "chip on"; b.textContent = `D${d}`; b.title = `Detector ${d}: ${DET_INFO[d].r}`;
    b.style.borderColor = DET_INFO[d].c; b.style.color = DET_INFO[d].c;
    b.onclick = () => {
      if (S.dets.has(d) && S.dets.size > 1) S.dets.delete(d); else S.dets.add(d);
      b.classList.toggle("on", S.dets.has(d));
      setFrames(true);
    };
    box.append(b);
  }
}

function bindUI() {
  $("#fieldSel").onchange = (e) => loadField(e.target.value);
  $("#playBtn").onclick = () => (S.playing ? stop() : play());
  $("#prevBtn").onclick = () => step(-1);
  $("#nextBtn").onclick = () => step(1);
  $("#frameSlider").oninput = (e) => { stop(); S.cur = +e.target.value; draw(); };
  $("#speed").oninput = () => S.playing && play();
  $("#trackClear").onclick = () => selectTrack(S.sel);
  $("#onlyUnknown").onchange = renderTracks;
  for (const id of ["#showCands", "#showTracks", "#showKnown"]) $(id).onchange = draw;
  document.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    S.mode = b.dataset.mode; draw();
  }));
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${b.dataset.tab}`));
  }));
  $("#timeline").onclick = (ev) => {
    if (!S.tlX) return;
    const x = ev.offsetX * devicePixelRatio;
    let best = 0, bd = 1e9;
    S.frames.forEach((i, k) => { const d = Math.abs(S.tlX(S.field.exposures[i].mjd) - x); if (d < bd) { bd = d; best = k; } });
    stop(); S.cur = best; draw();
  };
  $("#overlay").onmousemove = (ev) => {
    if (!S.field) return;
    const r = ev.target.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width * S.field.shape[1] - 0.5;
    const y = S.field.shape[0] - 0.5 - (ev.clientY - r.top) / r.height * S.field.shape[0];
    const [ra, dec] = pix2world(x, y);
    $("#cursorInfo").textContent = `RA ${ra.toFixed(4)}°  Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(4)}°`;
  };
  $("#overlay").onclick = (ev) => {
    const f = S.field, i = S.frames[S.cur];
    const r = ev.target.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width * f.shape[1] - 0.5;
    const y = f.shape[0] - 0.5 - (ev.clientY - r.top) / r.height * f.shape[0];
    const hit = (f.byExp.get(i) || []).find((c) => Math.hypot(c.x - x, c.y - y) < 4 && c.track !== null);
    if (hit) selectTrack(hit.track);
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === " ") { e.preventDefault(); S.playing ? stop() : play(); }
    if (e.key === "ArrowRight") step(1);
    if (e.key === "ArrowLeft") step(-1);
  });
  $("#jobForm").onsubmit = submitJob;
  $("#jobClose").onclick = () => ($("#jobBox").hidden = true);
  $("#dSlider").oninput = drawParallaxCalc;
  let resizeQueued = false;      // one redraw per animation frame while the window is being resized
  window.addEventListener("resize", () => {
    if (resizeQueued) return;
    resizeQueued = true;
    requestAnimationFrame(() => { resizeQueued = false; drawTimeline(); });
  });
}

function pix2world(x, y) {
  const w = S.field.wcs;
  const xi = (x + 1 - w.crpix[0]) * w.cdelt[0] * Math.PI / 180;
  const eta = (y + 1 - w.crpix[1]) * w.cdelt[1] * Math.PI / 180;
  const a0 = w.crval[0] * Math.PI / 180, d0 = w.crval[1] * Math.PI / 180;
  const den = Math.cos(d0) - eta * Math.sin(d0);
  const ra = a0 + Math.atan2(xi, den);
  const dec = Math.atan2(Math.sin(d0) + eta * Math.cos(d0), Math.hypot(xi, den));
  return [((ra * 180 / Math.PI) + 360) % 360, dec * 180 / Math.PI];
}

// ------------------------------------------------------------------ jobs
async function submitJob(ev) {
  ev.preventDefault();
  const ra = parseFloat($("#raIn").value), dec = parseFloat($("#decIn").value);
  if (!(ra >= 0 && ra < 360 && dec >= -90 && dec <= 90)) { alert("Enter RA 0–360 and Dec −90…+90 (degrees)."); return; }
  const j = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ra, dec }) });
  if (j.status === "done") { await refreshFields(j.id); return; }
  $("#jobBox").hidden = false;
  $("#jobTitle").textContent = `Analysing RA ${ra}, Dec ${dec}` + (j.position > 1 ? ` (queue position ${j.position})` : "");
  pollJob(j.id);
}

async function pollJob(id) {
  const j = await api(`/api/jobs/${id}`);
  $("#jobLog").textContent = j.log.join("\n");
  const stage = Math.max(0, ...j.log.map((l) => +(l.match(/^\[(\d)\/6\]/) || [0, 0])[1]));
  const m = j.log.map((l) => l.match(/exposure (\d+)\/(\d+)/)).filter(Boolean).at(-1);
  const frac = stage >= 4 && m ? (3 + (m[1] / m[2])) / 6 : stage / 6;
  $("#jobBar").style.width = `${Math.round((j.status === "done" ? 1 : frac) * 100)}%`;
  if (j.status === "done") { $("#jobTitle").textContent = "Done!"; await refreshFields(id); return; }
  if (j.status === "error") { $("#jobTitle").textContent = `Failed: ${j.error}`; return; }
  setTimeout(() => pollJob(id), 2000);
}

async function refreshFields(id) {
  S.fields = await api("/api/fields");
  fillFieldSelect().value = id;
  await loadField(id);
}

// ------------------------------------------------------------------ Planet X calculator + metrics
function drawParallaxCalc() {
  const d = +$("#dSlider").value;
  $("#dVal").textContent = d;
  const shift = 2 * AU_ARCSEC / d;       // max apparent shift between opposite sides of Earth's orbit
  $("#pVal").textContent = shift.toFixed(0);
  $("#pxVal").textContent = (shift / PIX_ARCSEC).toFixed(0);
  const cv = $("#parallaxPlot"), g = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  g.strokeStyle = "#23304a"; g.strokeRect(30, 8, W - 38, H - 30);
  g.fillStyle = "#8b98b3"; g.font = "10px system-ui";
  g.fillText("shift (px)", 2, 12); g.fillText("distance (AU, log)", W / 2 - 40, H - 4);
  const X = (a) => 30 + (W - 38) * (Math.log(a) - Math.log(30)) / (Math.log(1500) - Math.log(30));
  const Y = (p) => 8 + (H - 30) * (1 - Math.log10(p) / 4);
  g.strokeStyle = "#c08bff"; g.beginPath();
  for (let a = 30; a <= 1500; a *= 1.05) { const p = 2 * AU_ARCSEC / a / PIX_ARCSEC; a === 30 ? g.moveTo(X(a), Y(p)) : g.lineTo(X(a), Y(p)); }
  g.stroke();
  g.strokeStyle = "#ffb547"; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(30, Y(1)); g.lineTo(W - 8, Y(1)); g.stroke(); g.setLineDash([]);
  g.fillStyle = "#ffb547"; g.fillText("1 pixel", W - 48, Y(1) - 3);
  g.fillStyle = "#fff"; g.beginPath(); g.arc(X(d), Y(shift / PIX_ARCSEC), 4, 0, 7); g.fill();
}

async function loadMetrics() {
  try {
    const m = await api("/api/metrics");
    const box = $("#metricBox");
    const c = m.metrics?.cnn, b = m.metrics?.baseline_snr, r = m.recovery, k = m.metrics?.known_all_fields;
    if (!c) { box.textContent = "Model metrics not available yet."; return; }
    const cells = [
      [c.auroc_known?.toFixed(3) ?? "–", `AUROC on ${k?.n_known ?? ""} real known asteroids (never used in training)`],
      [c.recall_at_fpr1_known != null ? `${(c.recall_at_fpr1_known * 100).toFixed(0)}%` : "–", "known asteroids kept at 1% false alarms"],
      [b?.auroc_known?.toFixed(3) ?? "–", "AUROC with brightness (S/N) alone"],
      [r?.mag50_pipeline ? `AB ${r.mag50_pipeline.toFixed(1)}` : "–", "50% detection limit (injected movers)"],
    ];
    box.classList.remove("muted");
    box.innerHTML = cells.map(([v, k]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join("");
    $("#rocImg").src = "/models/roc.png";
    $("#recImg").src = "/models/recovery.png";
  } catch { $("#metricBox").textContent = "Model metrics not available yet."; }
}

init();
