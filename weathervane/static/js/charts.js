// Hand-built SVG charts (no chart library, nothing to download).
import { esc, clamp } from "./util.js";
import { convTemp, fmtTempDeg, fmtWind, windUnit, tempUnit } from "./units.js";
import { fmtHour, fmtClock, weekdayName, parseLocal, fmtDay } from "./timefmt.js";

const num = (v) => typeof v === "number" && Number.isFinite(v);

// Monotone cubic interpolation: smooth, and never overshoots the data.
function smoothPath(pts) {
  const n = pts.length;
  if (n < 2) return "";
  const dx = [], dy = [], m = [], t = [];
  for (let i = 0; i < n - 1; i++) { dx.push(pts[i + 1][0] - pts[i][0]); dy.push(pts[i + 1][1] - pts[i][1]); m.push(dy[i] / dx[i]); }
  t.push(m[0]);
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
    if (s > 9) { const k = 3 / Math.sqrt(s); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += `C${(pts[i][0] + h).toFixed(1)},${(pts[i][1] + t[i] * h).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)},${(pts[i + 1][1] - t[i + 1] * h).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}

/* ---------------------------- Hourly chart ----------------------------- */
export function mountHourlyChart(container, hours, ctx) {
  const tip = document.createElement("div");
  tip.className = "chart-tip"; tip.hidden = true;
  let observer;

  function draw() {
    const W = Math.max(320, Math.round(container.clientWidth || 640));
    const H = clamp(Math.round(W * 0.3), 210, 280);
    const L = 40, R = 14, T = 16, B = 62;
    const plotW = W - L - R, plotB = H - B;
    const n = hours.length;
    if (n < 2) { container.textContent = ""; return; }

    const temps = hours.map((h) => (num(h.temp) ? convTemp(h.temp, ctx.u) : null));
    const valid = temps.filter(num);
    if (!valid.length) { container.textContent = "No temperature data."; return; }
    let lo = Math.floor(Math.min(...valid) - 1), hi = Math.ceil(Math.max(...valid) + 1);
    if (hi - lo < 6) { hi += 3; lo -= 3; }
    const x = (i) => L + (i * plotW) / (n - 1);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (plotB - T);

    // Night bands
    let bands = "", start = null;
    hours.forEach((h, i) => {
      if (!h.is_day && start === null) start = i;
      if ((h.is_day || i === n - 1) && start !== null) { bands += `<rect x="${x(start).toFixed(1)}" y="${T}" width="${(x(i) - x(start)).toFixed(1)}" height="${H - T - 24}" fill="rgba(0,10,30,.22)"/>`; start = null; }
    });

    // Gridlines
    let grid = "";
    for (let k = 0; k <= 3; k++) {
      const v = lo + ((hi - lo) * k) / 3, yy = y(v);
      grid += `<line x1="${L}" x2="${W - R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="rgba(242,248,246,.14)"/><text x="${L - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="rgba(242,248,246,.62)" font-size="12">${Math.round(v)}\u00b0</text>`;
    }

    // Temperature line and area
    const pts = temps.map((v, i) => (num(v) ? [x(i), y(v)] : null)).filter(Boolean);
    const line = smoothPath(pts);
    const area = line + `L${pts[pts.length - 1][0].toFixed(1)},${plotB}L${pts[0][0].toFixed(1)},${plotB}Z`;

    // Rain-chance bars
    const bw = Math.max(3, plotW / n - 2);
    const rain = hours.map((h, i) => {
      const p = num(h.precip_prob) ? h.precip_prob : 0; if (p < 5) return "";
      const bh = (p / 100) * 30;
      return `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${(H - 26 - bh).toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="1.5" fill="#8fd3ff" opacity="${(0.35 + p / 160).toFixed(2)}"/>`;
    }).join("");

    // X labels
    const stepH = W < 560 ? 12 : 6;
    let xl = "";
    hours.forEach((h, i) => {
      const p = parseLocal(h.time);
      if (!p || p.h % stepH !== 0 || i === 0 && p.h % stepH !== 0) return;
      const label = p.h === 0 ? weekdayName(h.time.slice(0, 10), hours[0].time, { short: true }) : fmtHour(h.time, ctx.hour12);
      const bold = p.h === 0;
      xl += `<text x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="middle" fill="${bold ? "#9fe7d8" : "rgba(242,248,246,.66)"}" font-size="12" ${bold ? 'font-weight="500"' : ""}>${esc(label)}</text>`;
    });
    const nowX = x(0);

    container.innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Temperature and chance of rain for the next 48 hours">` +
      `<defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd58a" stop-opacity=".42"/><stop offset="1" stop-color="#ffd58a" stop-opacity="0"/></linearGradient></defs>` +
      bands + grid + `<path d="${area}" fill="url(#tg)"/>` + rain +
      `<path d="${line}" fill="none" stroke="#ffe3ac" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>` +
      `<line x1="${nowX}" x2="${nowX}" y1="${T}" y2="${plotB}" stroke="rgba(159,231,216,.6)" stroke-dasharray="3 4"/>` +
      `<text x="${L - 8}" y="${H - 24 - 8}" text-anchor="end" fill="#8fd3ff" font-size="11">rain</text>` + xl +
      `<g id="hv" visibility="hidden"><line id="hv-line" y1="${T}" y2="${H - 24}" stroke="rgba(242,248,246,.55)"/><circle id="hv-dot" r="5" fill="#ffe3ac" stroke="#0f2b3d" stroke-width="2"/></g>` +
      `<rect id="hv-hit" x="${L}" y="0" width="${plotW}" height="${H}" fill="transparent"/></svg>`;
    container.appendChild(tip);

    const svg = container.querySelector("svg"), hv = svg.querySelector("#hv"), hl = svg.querySelector("#hv-line"), dot = svg.querySelector("#hv-dot");
    const show = (evt) => {
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * W;
      const i = clamp(Math.round(((px - L) / plotW) * (n - 1)), 0, n - 1), h = hours[i];
      if (!num(temps[i])) return;
      hv.setAttribute("visibility", "visible");
      hl.setAttribute("x1", x(i)); hl.setAttribute("x2", x(i));
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(temps[i]));
      const day = weekdayName(h.time.slice(0, 10), hours[0].time, { short: true });
      tip.innerHTML = `<span>${esc(day)} ${esc(fmtClock(h.time, ctx.hour12, { minutes: false }))}</span><b>${esc(fmtTempDeg(h.temp, ctx.u))}</b><span>${esc(h.condition)}</span>` +
        `<span>Rain chance ${num(h.precip_prob) ? h.precip_prob + "%" : "--"}</span><span>Wind ${esc(fmtWind(h.wind, ctx.u))} ${esc(windUnit(ctx.u))}</span>`;
      tip.hidden = false;
      const left = clamp((x(i) / W) * r.width, 76, r.width - 76);
      tip.style.left = `${left}px`; tip.style.top = `${(y(temps[i]) / H) * r.height - 12}px`;
    };
    const hide = () => { hv.setAttribute("visibility", "hidden"); tip.hidden = true; };
    const hit = svg.querySelector("#hv-hit");
    let touchTimer = 0;
    const showAndHold = (e) => { clearTimeout(touchTimer); show(e); };
    hit.addEventListener("pointermove", showAndHold); hit.addEventListener("pointerdown", showAndHold);
    // On touch screens the finger lifts right after a tap, so keep the readout up for a moment instead of flashing it.
    hit.addEventListener("pointerleave", (e) => { if (e.pointerType === "touch") { clearTimeout(touchTimer); touchTimer = setTimeout(hide, 2600); } else hide(); });
  }

  draw();
  if ("ResizeObserver" in window) {
    let lastW = container.clientWidth;
    observer = new ResizeObserver(() => { if (Math.abs(container.clientWidth - lastW) > 8) { lastW = container.clientWidth; draw(); } });
    observer.observe(container);
  }
  return () => observer && observer.disconnect();
}

/* ------------------------------ Air quality ----------------------------- */
export const AQI_COLORS = ["#8fe3a8", "#ffe08a", "#ffb36b", "#ff8b8b", "#d79bff", "#c2476a"];
const AQI_BOUNDS = [0, 50, 100, 150, 200, 300, 500];

export function aqiGauge(aqi, level) {
  const cx = 100, cy = 92, r = 74, seg = Math.PI / 6;
  let arcs = "";
  for (let i = 0; i < 6; i++) {
    const a0 = Math.PI - i * seg - 0.012, a1 = Math.PI - (i + 1) * seg + 0.012;
    const p = (a) => [(cx + r * Math.cos(a)).toFixed(1), (cy - r * Math.sin(a)).toFixed(1)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    arcs += `<path d="M${x0} ${y0}A${r} ${r} 0 0 1 ${x1} ${y1}" fill="none" stroke="${AQI_COLORS[i]}" stroke-width="14" stroke-linecap="butt" opacity="${i === level ? 1 : 0.62}"/>`;
  }
  const lv = clamp(level ?? 0, 0, 5);
  const frac = clamp((aqi - AQI_BOUNDS[lv]) / (AQI_BOUNDS[lv + 1] - AQI_BOUNDS[lv]), 0, 1);
  const ang = Math.PI - (lv + frac) * seg;
  const nx = cx + (r - 16) * Math.cos(ang), ny = cy - (r - 16) * Math.sin(ang);
  return `<svg viewBox="0 0 200 104" role="img" aria-label="Air quality index ${esc(aqi)}">${arcs}<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="#f2f8f6" stroke-width="3" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="6" fill="#f2f8f6"/></svg>`;
}

export function aqiHours(hourly, ctxHour12) {
  const vals = hourly.filter((h) => num(h.us_aqi));
  if (vals.length < 2) return "";
  const W = 300, H = 56, max = Math.max(100, ...vals.map((h) => h.us_aqi)), bw = W / vals.length;
  const level = (a) => AQI_BOUNDS.findIndex((b, i) => a <= AQI_BOUNDS[i + 1]);
  const bars = vals.map((h, i) => {
    const bh = Math.max(3, (h.us_aqi / max) * (H - 16));
    return `<rect x="${(i * bw + 1).toFixed(1)}" y="${(H - 14 - bh).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${bh.toFixed(1)}" rx="1.5" fill="${AQI_COLORS[clamp(level(h.us_aqi), 0, 5)]}"/>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Air quality for the next 24 hours">${bars}` +
    `<text x="0" y="${H - 1}" font-size="10" fill="rgba(242,248,246,.6)">${esc(fmtHour(vals[0].time, ctxHour12))}</text>` +
    `<text x="${W}" y="${H - 1}" font-size="10" text-anchor="end" fill="rgba(242,248,246,.6)">${esc(fmtHour(vals[vals.length - 1].time, ctxHour12))}</text></svg>`;
}

/* ------------------------------- Sun and moon ---------------------------- */
export function sunArc(sun, hour12) {
  const cx = 120, cy = 96, r = 84;
  const p = sun.progress;
  const up = p != null && p >= 0 && p <= 1;
  const pc = clamp(p ?? 0, 0, 1), th = Math.PI * (1 - pc);
  const dx = cx + r * Math.cos(th), dy = cy - r * Math.sin(th);
  const arc = `M${cx - r} ${cy}A${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  const label = (t, anchor, xx) => `<text x="${xx}" y="${cy + 20}" text-anchor="${anchor}" fill="rgba(242,248,246,.82)" font-size="13">${esc(t)}</text>`;
  return `<svg viewBox="0 0 240 124" role="img" aria-label="Sun position between sunrise and sunset">` +
    `<line x1="14" x2="226" y1="${cy}" y2="${cy}" stroke="rgba(242,248,246,.3)"/>` +
    `<path d="${arc}" fill="none" stroke="rgba(242,248,246,.22)" stroke-width="2" stroke-dasharray="3 5"/>` +
    (up ? `<path d="${arc}" pathLength="100" fill="none" stroke="#ffd58a" stroke-width="3" stroke-linecap="round" stroke-dasharray="${(pc * 100).toFixed(1)} 100"/>` : "") +
    `<circle cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="${up ? 9 : 6}" fill="${up ? "#ffd166" : "#c9d6e6"}" ${up ? 'stroke="rgba(255,209,102,.4)" stroke-width="6"' : 'opacity=".8"'}/>` +
    (sun.sunrise ? label(fmtClock(sun.sunrise, hour12), "middle", cx - r) : "") +
    (sun.sunset ? label(fmtClock(sun.sunset, hour12), "middle", cx + r) : "") + `</svg>`;
}

export function moonSvg(phase, mirrored) {
  const r = 24, k = Math.cos(2 * Math.PI * phase);
  const waxing = phase < 0.5;
  const rx = (Math.abs(k) * r).toFixed(2);
  const lit = `M0 ${-r}A${r} ${r} 0 0 1 0 ${r}A${rx} ${r} 0 0 ${k > 0 ? 0 : 1} 0 ${-r}Z`;
  const flip = waxing === mirrored; // waxing in the north is lit on the right; mirrored in the south
  return `<svg viewBox="-30 -30 60 60" role="img" aria-label="Moon phase"><circle r="${r}" fill="#1d2d3f" stroke="rgba(242,248,246,.25)"/>` +
    `<path d="${lit}" fill="#eef3fb" ${flip ? 'transform="scale(-1 1)"' : ""}/></svg>`;
}

/* -------------------------------- Wind compass ---------------------------- */
export function compassSvg(dir) {
  const cx = 100, cy = 100;
  let ticks = "";
  for (let i = 0; i < 16; i++) {
    const a = (i * 22.5 * Math.PI) / 180, major = i % 4 === 0, r1 = major ? 70 : 74, r2 = 80;
    ticks += `<line x1="${(cx + Math.sin(a) * r1).toFixed(1)}" y1="${(cy - Math.cos(a) * r1).toFixed(1)}" x2="${(cx + Math.sin(a) * r2).toFixed(1)}" y2="${(cy - Math.cos(a) * r2).toFixed(1)}" stroke="rgba(242,248,246,${major ? 0.7 : 0.3})" stroke-width="${major ? 2 : 1.2}"/>`;
  }
  const lab = (t, x, y) => `<text x="${x}" y="${y}" text-anchor="middle" fill="rgba(242,248,246,.8)" font-size="13" font-weight="500">${t}</text>`;
  const to = num(dir) ? (dir + 180) % 360 : null;
  const arrow = to === null ? "" :
    `<g transform="rotate(${to} ${cx} ${cy})"><line x1="${cx}" y1="${cy + 38}" x2="${cx}" y2="${cy - 34}" stroke="#9fe7d8" stroke-width="4" stroke-linecap="round"/><path d="M${cx} ${cy - 50}L${cx + 13} ${cy - 24}L${cx} ${cy - 30}L${cx - 13} ${cy - 24}Z" fill="#9fe7d8"/></g>`;
  return `<svg viewBox="0 0 200 200" role="img" aria-label="Wind direction compass"><circle cx="${cx}" cy="${cy}" r="82" fill="rgba(242,248,246,.05)" stroke="rgba(242,248,246,.2)"/>${ticks}` +
    lab("N", cx, 52) + lab("E", 160, cy + 5) + lab("S", cx, 158) + lab("W", 40, cy + 5) + arrow + `</svg>`;
}

/* ---------------------------- Climate: stripes + trend ---------------------- */
const lerp = (a, b, t) => a + (b - a) * t;
function mix(c1, c2, t) { return c1.map((v, i) => Math.round(lerp(v, c2[i], t))); }
const BLUE = [31, 95, 168], PALE_B = [222, 232, 241], PALE_R = [248, 222, 208], RED = [176, 23, 31];
export function anomalyColor(a, scale) {
  const t = clamp(a / scale, -1, 1);
  const c = t < 0 ? mix(PALE_B, BLUE, -t) : mix(PALE_R, RED, t);
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function stripes(series, baseline) {
  if (!series.length || !num(baseline)) return "";
  const dev = series.map((s) => s.mean - baseline);
  const scale = Math.max(0.6, ...dev.map(Math.abs));
  return `<div class="stripes" role="img" aria-label="Each stripe is one year, from cooler (blue) to warmer (red) than the 1991 to 2020 average">` +
    series.map((s, i) => `<i style="background:${anomalyColor(dev[i], scale)}" title="${s.year}: ${dev[i] >= 0 ? "+" : "\u2212"}${Math.abs(dev[i]).toFixed(1)}\u00b0C vs average"></i>`).join("") + `</div>`;
}

export function trendChart(trend, u, baseline) {
  const W = 560, H = 230, L = 44, R = 12, T = 12, B = 30;
  const pts = trend.series.map((s) => ({ ...s, v: convTemp(s.mean, u) }));
  const line = trend.line.map((p) => ({ year: p.year, v: convTemp(p.value, u) }));
  const vals = pts.map((p) => p.v).concat(line.map((p) => p.v));
  const lo = Math.floor(Math.min(...vals) * 2) / 2 - 0.5, hi = Math.ceil(Math.max(...vals) * 2) / 2 + 0.5;
  const y0 = trend.first_year, y1 = trend.last_year;
  const x = (yr) => L + ((yr - y0) / (y1 - y0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const scale = Math.max(0.6, ...trend.series.map((s) => Math.abs(s.mean - baseline)));
  let grid = "";
  for (let k = 0; k <= 3; k++) {
    const v = lo + ((hi - lo) * k) / 3;
    grid += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="rgba(242,248,246,.13)"/><text x="${L - 7}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" fill="rgba(242,248,246,.62)" font-size="12">${v.toFixed(1)}\u00b0</text>`;
  }
  let xt = "";
  for (let yr = Math.ceil(y0 / 5) * 5; yr <= y1; yr += 5) xt += `<text x="${x(yr).toFixed(1)}" y="${H - 8}" text-anchor="middle" fill="rgba(242,248,246,.62)" font-size="12">${yr}</text>`;
  const dots = pts.map((p) => `<circle cx="${x(p.year).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="4" fill="${anomalyColor(p.mean - baseline, scale)}" stroke="rgba(0,0,0,.35)" stroke-width=".8"><title>${p.year}: ${p.v.toFixed(1)}${tempUnit(u)}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Yearly average temperature with trend line">${grid}${xt}${dots}` +
    `<line x1="${x(line[0].year)}" y1="${y(line[0].v).toFixed(1)}" x2="${x(line[1].year)}" y2="${y(line[1].v).toFixed(1)}" stroke="#ffd58a" stroke-width="2.6" stroke-linecap="round"/></svg>`;
}
