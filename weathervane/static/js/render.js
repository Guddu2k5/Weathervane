import { html, raw, setHTML, esc, $, clamp } from "./util.js";
import {
  fmtTemp, fmtTempDeg, fmtDelta, tempUnit, fmtWind, windUnit, fmtPressure, pressureUnit,
  fmtPrecip, precipUnit, fmtVisibility, distUnit, fmtPct, fmtDuration, fmtSecondsDelta, convTemp,
} from "./units.js";
import { fmtClock, fmtHour, fmtWhen, weekdayName, fmtDay, fmtLongDate, fmtRelativeMinutes, parseLocal } from "./timefmt.js";
import { icon } from "./icons.js";
import { mountHourlyChart, aqiGauge, aqiHours, sunArc, moonSvg, compassSvg, stripes, trendChart } from "./charts.js";

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const absDeg = (dc, u, d = 0) => fmtDelta(Math.abs(dc), u, d);
let disposeChart = null;

/* ------------------------------------------------------------------ hero */
export function rainSentence(r, nowStr, hour12) {
  if (!r) return "";
  const kind = r.kind || "rain";
  if (r.state === "wet-now") {
    return r.end ? `${cap(kind)} until ${fmtWhen(r.end, nowStr, hour12)}.` : `${cap(kind)} continues through the next 24 hours.`;
  }
  if (r.state === "wet-later") {
    return r.end ? `${cap(kind)} likely from ${fmtWhen(r.start, nowStr, hour12)} to ${fmtWhen(r.end, nowStr, hour12)}.` : `${cap(kind)} likely from ${fmtWhen(r.start, nowStr, hour12)}.`;
  }
  return isNum(r.peak_prob) && r.peak_prob >= 30 ? `Mostly dry, though there is up to a ${r.peak_prob}% chance of rain.` : "No rain expected in the next 24 hours.";
}

export function anomalySentence(day, u) {
  if (!day || !isNum(day.anomaly_c)) return "";
  const parts = [];
  if (Math.abs(day.anomaly_c) >= 1 && Math.abs(day.z) >= 0.8) {
    parts.push(`About ${absDeg(day.anomaly_c, u)} ${day.anomaly_c > 0 ? "warmer" : "cooler"} than usual for this time of year.`);
  }
  if (day.unusual) parts.push("A rare combination of conditions for the season.");
  return parts.join(" ");
}

export function renderHero(wx, place, ctx, insights) {
  const c = wx.current, t = wx.today || {};
  $("#place-name").textContent = place.name;
  $("#place-sub").textContent = `${place.sub ? place.sub + ". " : ""}${fmtLongDate(c.time)}, ${fmtClock(c.time, ctx.hour12)} local time`;
  $("#temp-now").textContent = fmtTemp(c.temp, ctx.u);
  setHTML($("#cond-icon"), raw(icon(c.icon, { size: 48 })));
  $("#cond-text").textContent = c.condition;
  const anomaly = insights ? anomalySentence(insights.days?.[0], ctx.u) : "";
  $("#hero-line").textContent = [`Feels like ${fmtTempDeg(c.feels_like, ctx.u)}.`, rainSentence(wx.guidance.rain, c.time, ctx.hour12), anomaly].filter(Boolean).join(" ");

  const w = c.wind;
  setHTML($("#hero-facts"), html`
    <div class="fact"><dt>High and low</dt><dd class="num">${fmtTempDeg(t.high, ctx.u)} <small>/ ${fmtTempDeg(t.low, ctx.u)}</small></dd></div>
    <div class="fact"><dt>Wind</dt><dd class="num">${fmtWind(w.speed, ctx.u)} <small>${windUnit(ctx.u)} ${w.compass || ""}</small></dd></div>
    <div class="fact"><dt>Humidity</dt><dd class="num">${fmtPct(c.humidity)}</dd></div>
    <div class="fact"><dt>Chance of rain today</dt><dd class="num">${isNum(t.precip_prob) ? t.precip_prob + "%" : "--"}</dd></div>
    <div class="fact"><dt>UV index</dt><dd class="num">${isNum(c.uv) ? Math.round(c.uv) : "--"} <small>${c.uv_label || ""}</small></dd></div>`);
}

export function renderUpdated(wx) {
  $("#updated").textContent = wx.meta?.generated ? `Updated ${fmtRelativeMinutes(wx.meta.generated)}` : "";
}

/* ---------------------------------------------------------------- alerts */
export function renderAlerts(wx, ctx) {
  const el = $("#alerts");
  if (!wx.alerts.length) { el.hidden = true; el.innerHTML = ""; return; }
  const badge = { advisory: "Advisory", warning: "Warning", danger: "Danger" };
  const now = wx.current.time;
  setHTML(el, html`${wx.alerts.map((a) => html`
    <div class="alert" data-sev="${a.severity}">
      <span class="alert-badge">${badge[a.severity]}</span>
      <div class="alert-body"><strong>${a.title}</strong><span>${convertAlertTemps(a.detail, ctx.u)}</span>
        ${a.start ? html`<em>${fmtWhen(a.start, now, ctx.hour12)}${a.end && a.end !== a.start ? html` to ${fmtWhen(a.end, now, ctx.hour12)}` : ""}</em>` : ""}</div>
    </div>`)}<p class="alerts-note">Generated from forecast data. For official warnings, check your national weather service.</p>`);
  el.hidden = false;
}
// Alert text is written in metric; convert the few quantities it contains.
function convertAlertTemps(text, u) {
  let out = text.replace(/(-?\d+)\u00b0C/g, (_, n) => `${fmtTemp(+n, u)}${tempUnit(u)}`);
  if (u.wind !== "kmh") out = out.replace(/(\d+) km\/h/g, (_, n) => `${fmtWind(+n, u)} ${windUnit(u)}`);
  if (u.precip === "in") out = out.replace(/(\d+) mm/g, (_, n) => `${fmtPrecip(+n, u)} in`);
  return out;
}

/* --------------------------------------------------------------- hourly */
export function renderHourly(wx, ctx) {
  if (disposeChart) disposeChart();
  disposeChart = mountHourlyChart($("#hourly-chart"), wx.hourly, ctx);
  const now = wx.hourly[0].time;
  const strip = $("#hourly-strip"), keepScroll = strip.scrollLeft;
  setHTML(strip, html`${wx.hourly.map((h, i) => {
    const p = parseLocal(h.time);
    const label = i === 0 ? "Now" : p.h === 0 ? weekdayName(h.time.slice(0, 10), now, { short: true }) : fmtHour(h.time, ctx.hour12);
    return html`<div class="hr"><div class="${p.h === 0 && i ? "hr-day" : "hr-time"}">${label}</div>${raw(icon(h.icon, { size: 34 }))}<div class="hr-temp num">${fmtTempDeg(h.temp, ctx.u)}</div><div class="hr-rain num">${isNum(h.precip_prob) && h.precip_prob >= 10 ? h.precip_prob + "%" : ""}</div></div>`;
  })}`);
  strip.scrollLeft = keepScroll;
}

/* ---------------------------------------------------------------- daily */
export function renderDaily(wx, ctx, insights) {
  const days = wx.daily, now = wx.current.time;
  const lows = days.map((d) => d.low).filter(isNum), highs = days.map((d) => d.high).filter(isNum);
  const lo = Math.min(...lows), hi = Math.max(...highs), span = Math.max(1, hi - lo);
  const byDate = Object.fromEntries((insights?.days || []).map((d) => [d.date, d]));
  const nowTemp = wx.current.temp;

  setHTML($("#daily-list"), html`${days.map((d, i) => {
    const width = Math.max(4, ((d.high - d.low) / span) * 100), left = Math.min(((d.low - lo) / span) * 100, 100 - width);
    const open = ctx.expanded.has(d.date);
    const ins = byDate[d.date];
    return html`<div class="day">
      <button class="day-row" type="button" aria-expanded="${String(open)}" data-date="${d.date}" aria-controls="dd-${d.date}">
        <span class="day-name">${weekdayName(d.date, now)}<small>${fmtDay(d.date)}</small></span>
        ${raw(icon(d.icon, { size: 30, cls: "ico" }))}
        <span class="day-rain num">${isNum(d.precip_prob) && d.precip_prob >= 10 ? d.precip_prob + "%" : ""}</span>
        <span class="day-lo num">${fmtTempDeg(d.low, ctx.u)}</span>
        <span class="range" aria-hidden="true"><i style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%"></i>${i === 0 && isNum(nowTemp) ? raw(`<b style="left:${clamp(((nowTemp - lo) / span) * 100, 0, 100).toFixed(1)}%"></b>`) : ""}</span>
        <span class="day-hi num">${fmtTempDeg(d.high, ctx.u)}</span>
        <svg class="chev" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <div class="day-detail${open ? " open" : ""}" id="dd-${d.date}"><div class="day-detail-clip"><div class="day-detail-body">${dayDetail(d, ins, ctx)}</div></div></div></div>`;
  })}`);
}

function dayDetail(d, ins, ctx) {
  const kv = (k, v) => html`<dl class="kv"><dt>${k}</dt><dd class="num">${v}</dd></dl>`;
  let note = "";
  if (ins && isNum(ins.anomaly_c)) {
    const cls = ins.anomaly_c > 0.9 ? "warm" : ins.anomaly_c < -0.9 ? "cool" : "";
    note = html`<p class="day-note"><span class="tag ${cls}">${ins.label}</span> Normal here is ${fmtTempDeg(ins.normal_high, ctx.u)} / ${fmtTempDeg(ins.normal_low, ctx.u)} (1991 to 2020).
      Record for this date: ${fmtTempDeg(ins.record_high?.value, ctx.u)} in ${ins.record_high?.year ?? "--"}.${ins.unusual ? html` <b>${ins.unusual}.</b>` : ""}
      ${ins.agreement ? html` Forecast models agree: <b>${ins.agreement.label.toLowerCase()}</b> (highs ${fmtTempDeg(ins.agreement.high_range[0], ctx.u)} to ${fmtTempDeg(ins.agreement.high_range[1], ctx.u)}).` : ""}</p>`;
  } else if (ins?.agreement) {
    note = html`<p class="day-note">Forecast models agree: <b>${ins.agreement.label.toLowerCase()}</b> (highs ${fmtTempDeg(ins.agreement.high_range[0], ctx.u)} to ${fmtTempDeg(ins.agreement.high_range[1], ctx.u)}).</p>`;
  }
  return html`
    ${kv("Feels like", html`${fmtTempDeg(d.feels_high, ctx.u)} / ${fmtTempDeg(d.feels_low, ctx.u)}`)}
    ${kv("Conditions", d.condition)}
    ${kv("Rain", html`${fmtPrecip(d.precip_sum, ctx.u)} ${precipUnit(ctx.u)}${isNum(d.precip_hours) ? html` <small>${d.precip_hours} h</small>` : ""}`)}
    ${kv("Wind", html`${fmtWind(d.wind_max, ctx.u)} ${windUnit(ctx.u)} <small>${d.wind_compass || ""}</small>`)}
    ${kv("Gusts", html`${fmtWind(d.gust_max, ctx.u)} ${windUnit(ctx.u)}`)}
    ${kv("UV index", html`${isNum(d.uv_max) ? Math.round(d.uv_max) : "--"} <small>${d.uv_label || ""}</small>`)}
    ${kv("Sunrise", d.sunrise ? fmtClock(d.sunrise, ctx.hour12) : "--")}
    ${kv("Sunset", d.sunset ? fmtClock(d.sunset, ctx.hour12) : "--")}
    ${note}`;
}

/* ------------------------------------------------------------- guidance */
export function renderGuidance(wx, ctx) {
  const g = wx.guidance, now = wx.current.time, o = g.outdoor;
  const rain = g.rain;
  setHTML($("#guidance"), html`
    <div class="g-block"><p class="g-title">Rain</p>
      <p class="g-main">${rainSentence(rain, now, ctx.hour12)} <small class="num">${rain.total_mm > 0 ? `${fmtPrecip(rain.total_mm, ctx.u)} ${precipUnit(ctx.u)} in the next 24 hours` : ""}</small></p></div>
    <div class="g-block"><p class="g-title">Best time to be outside</p>
      ${o ? html`<p class="g-main">${fmtClock(o.start, ctx.hour12, { minutes: false })} to ${fmtClock(o.end, ctx.hour12, { minutes: false })}
        <small class="score"><span class="score-bar"><i style="width:${o.score}%"></i></span>${o.label}, ${o.score}/100</small></p>` : html`<p class="g-main"><small>No daylight hours in the next day.</small></p>`}
      <p class="muted">Scored on comfort, rain, wind, UV and air quality.</p></div>
    <div class="g-block"><p class="g-title">What to wear</p>
      <ul class="wear">${(g.outfit.length ? g.outfit : ["Dress for the temperature shown above"]).map((t) => html`<li>${t}</li>`)}</ul></div>`);
}

/* ------------------------------------------------------------- insights */
export function renderInsightsLoading() {
  setHTML($("#insights"), html`<div class="skeleton" aria-label="Loading climate comparison"><i></i><i></i><i></i></div>`);
}

export function renderInsights(ins, wx, ctx) {
  const el = $("#insights");
  if (!ins || !ins.days?.length) {
    setHTML(el, html`<p class="ai-sub">${ins?.notes?.[0] || "Climate comparison is unavailable right now."}</p>`);
    return;
  }
  const today = ins.days.find((d) => isNum(d.anomaly_c)) || null;
  const now = wx.current.time;
  const lead = today ? today.label : "Model comparison";
  const sub = today
    ? html`Today's average temperature is ${absDeg(today.anomaly_c, ctx.u, 1)} ${today.anomaly_c >= 0 ? "above" : "below"} the 1991 to 2020 normal for this date, warmer than ${today.percentile}% of past years.`
    : "";
  const rows = ins.days.slice(0, 7).map((d) => {
    const a = d.agreement;
    return html`<div class="ai-item"><b>${weekdayName(d.date, now, { short: true })}</b>
      <span>${isNum(d.anomaly_c) ? html`${d.anomaly_c >= 0 ? "+" : "\u2212"}${absDeg(d.anomaly_c, ctx.u, 1).replace("\u2212", "")} vs normal${d.unusual ? html`, <b>${d.unusual.toLowerCase()}</b>` : ""}` : ""}${a ? html`${isNum(d.anomaly_c) ? ", " : ""}model agreement ${a.label.toLowerCase()}` : ""}</span></div>`;
  });
  setHTML(el, html`
    <p class="ai-lead">${lead}</p>
    <p class="ai-sub">${sub}</p>
    <div class="ai-list">${rows}</div>
    <details class="how"><summary>How this works</summary>
      <p>${ins.method.anomaly}. ${ins.method.agreement}. Agreement is a transparent heuristic based on how far the models' daily highs and rain calls differ; it is not a calibrated probability.</p></details>`);
}

/* ------------------------------------------------------------------ air */
export function renderAir(wx, ctx) {
  const a = wx.air, el = $("#air");
  if (!a) { setHTML(el, html`<p class="sub">Air quality data is not available for this location.</p>`); return; }
  const lvl = a.level ?? 0;
  setHTML(el, html`
    <div class="aqi-top"><div class="aqi-gauge">${raw(aqiGauge(a.us_aqi ?? 0, lvl))}</div>
      <div><div class="aqi-num num">${a.us_aqi ?? "--"}</div><div class="aqi-cat">${a.category || ""}</div>
      <div class="muted">US AQI${isNum(a.eu_aqi) ? html`. European index ${a.eu_aqi}, ${(a.eu_category || "").toLowerCase()}` : ""}</div></div></div>
    <p class="aqi-advice">${a.advice || ""}</p>
    <div class="poll">${a.pollutants.map((p) => html`<div class="poll-row"><span>${p.label}</span>
      <span class="bar"><i class="${p.ratio > 2 ? "vhi" : p.ratio > 1 ? "hi" : ""}" style="width:${clamp(p.ratio * 50, 3, 100)}%"></i></span><span class="num">${p.value}</span></div>`)}</div>
    <p class="aq-note">${a.dominant ? `Main pollutant: ${a.dominant}. ` : ""}Bars are measured against WHO 24-hour guidelines; the midpoint is the guideline. Values in \u00b5g/m\u00b3.</p>
    <div class="aq-hours">${raw(aqiHours(a.hourly, ctx.hour12))}</div>`);
}

/* ------------------------------------------------------------ sun, moon */
export function renderSun(wx, ctx) {
  const s = wx.sun, m = wx.moon;
  const polar = s.polar === "day" ? "Polar day: the sun stays up around the clock." : s.polar === "night" ? "Polar night: the sun does not rise today." : "";
  const gold = (r) => (r ? `${fmtClock(r[0], ctx.hour12)} to ${fmtClock(r[1], ctx.hour12)}` : "--");
  setHTML($("#sun"), html`
    <div class="sun-arc">${raw(sunArc(s, ctx.hour12))}</div>
    ${polar ? html`<p class="sub">${polar}</p>` : html`
    <div class="big num">${fmtDuration(s.daylight_seconds)}<small>of daylight</small></div>
    <p class="sub">${fmtSecondsDelta(s.daylight_change_seconds)}</p>
    <div class="pair"><dl class="kv"><dt>Golden hour, morning</dt><dd class="num">${gold(s.golden_morning)}</dd></dl>
    <dl class="kv"><dt>Golden hour, evening</dt><dd class="num">${gold(s.golden_evening)}</dd></dl></div>`}
    <div class="moon-row">${raw(moonSvg(m.phase, m.mirrored))}
      <div><b>${m.name}</b><p class="sub num">${Math.round(m.illumination * 100)}% lit. Full moon about ${fmtDay(m.next_full)}.</p></div></div>`);
}

/* ----------------------------------------------------------------- wind */
export function renderWind(wx, ctx) {
  const w = wx.current.wind;
  setHTML($("#wind"), html`
    <div class="compass">${raw(compassSvg(w.dir))}</div>
    <div class="big num">${fmtWind(w.speed, ctx.u)}<small>${windUnit(ctx.u)} from ${w.compass || "--"}</small></div>
    <p class="sub">${w.beaufort ? `${w.beaufort.label} (Beaufort ${w.beaufort.force}). ` : ""}Gusts up to ${fmtWind(w.gust, ctx.u)} ${windUnit(ctx.u)}.</p>`);
}

/* ----------------------------------------------------------- conditions */
export function renderConditions(wx, ctx) {
  const c = wx.current, r = wx.guidance.rain;
  const uv = isNum(c.uv) ? c.uv : null;
  setHTML($("#conditions"), html`
    <div class="cond"><p class="cond-label">Humidity</p><p class="cond-val num">${fmtPct(c.humidity)}</p><p class="cond-note">Dew point ${fmtTempDeg(c.dew_point, ctx.u)}${c.dew_comfort ? `, ${c.dew_comfort.toLowerCase()}` : ""}</p></div>
    <div class="cond"><p class="cond-label">Pressure</p><p class="cond-val num">${fmtPressure(c.pressure, ctx.u)}<small>${pressureUnit(ctx.u)}</small></p><p class="cond-note">${c.pressure_trend || "Trend unavailable"}</p></div>
    <div class="cond"><p class="cond-label">Visibility</p><p class="cond-val num">${fmtVisibility(c.visibility, ctx.u)}<small>${distUnit(ctx.u)}</small></p><p class="cond-note">${visibilityNote(c.visibility)}</p></div>
    <div class="cond"><p class="cond-label">Cloud cover</p><p class="cond-val num">${fmtPct(c.cloud)}</p><p class="cond-note">${cloudNote(c.cloud)}</p></div>
    <div class="cond"><p class="cond-label">UV index</p><p class="cond-val num">${uv === null ? "--" : uv.toFixed(0)}<small>${c.uv_label || ""}</small></p>
      <div class="uvbar" aria-hidden="true">${uv === null ? "" : raw(`<b style="left:${clamp((uv / 12) * 100, 0, 100)}%"></b>`)}</div></div>
    <div class="cond"><p class="cond-label">Rain, next 24 hours</p><p class="cond-val num">${fmtPrecip(r.total_mm, ctx.u)}<small>${precipUnit(ctx.u)}</small></p><p class="cond-note">${isNum(r.peak_prob) ? `Peak chance ${r.peak_prob}%` : ""}</p></div>`);
}
const visibilityNote = (m) => (!isNum(m) ? "" : m < 1000 ? "Poor" : m < 4000 ? "Reduced" : m < 10000 ? "Moderate" : "Clear");
const cloudNote = (p) => (!isNum(p) ? "" : p < 15 ? "Clear skies" : p < 45 ? "Mostly clear" : p < 75 ? "Partly cloudy" : p < 95 ? "Mostly cloudy" : "Overcast");

/* -------------------------------------------------------------- climate */
export function renderClimateLoading() {
  setHTML($("#climate"), html`<div class="skeleton"><i></i><i></i><i></i></div>`);
}

export function renderClimate(ins, ctx) {
  const el = $("#climate"), t = ins?.trend;
  if (!t) { setHTML(el, html`<p class="sub">${ins?.notes?.[0] || "Climate history is unavailable for this location right now."}</p>`); return; }
  const per = absDeg(t.slope_per_decade, ctx.u, 1), total = absDeg(t.total_change, ctx.u, 1);
  const lead = t.verdict === "warming" ? `Warming about ${per} per decade here.`
    : t.verdict === "cooling" ? `Cooling about ${per} per decade here.` : "No clear long-term trend here yet.";
  const detail = t.verdict === "inconclusive"
    ? `Year-to-year swings are larger than any steady change over ${t.n_years} years, so the data cannot separate a trend from natural variability. The trend estimate is ${t.slope_per_decade >= 0 ? "+" : "\u2212"}${per} per decade, with a 95% range of ${fmtDelta(t.ci_low_per_decade, ctx.u, 1)} to ${fmtDelta(t.ci_high_per_decade, ctx.u, 1)}.`
    : `From ${t.first_year} to ${t.last_year} the average yearly temperature here ${t.verdict === "warming" ? "rose" : "fell"} by about ${total} in total. The 95% confidence range for the trend is ${fmtDelta(t.ci_low_per_decade, ctx.u, 1)} to ${fmtDelta(t.ci_high_per_decade, ctx.u, 1)} per decade.`;
  const p = t.p_value < 0.001 ? "< 0.001" : t.p_value.toFixed(3);
  setHTML(el, html`<div class="climate-grid">
    <div><p class="climate-lead">${lead}</p><p class="climate-text">${detail}</p>
      <p class="climate-text">For comparison, the global average has warmed roughly ${absDeg(0.2, ctx.u, 1)} per decade since the 1980s (NOAA). A single place can differ a lot from the global figure.</p>
      <div class="stat-row">
        <div class="stat"><b class="num">${isNum(t.baseline_mean) ? fmtTempDeg(t.baseline_mean, ctx.u, 1) : "--"}</b><span>Average year, 1991 to 2020</span></div>
        <div class="stat"><b class="num">${t.n_years}</b><span>Years analysed</span></div>
        <div class="stat"><b class="num">${t.r2.toFixed(2)}</b><span>R\u00b2, p ${p}</span></div></div></div>
    <div><div>${raw(stripes(t.series, t.baseline_mean))}</div>
      <div class="stripes-cap"><span>${t.first_year}</span><span>Each stripe is one year, blue cooler to red warmer than average</span><span>${t.last_year}</span></div>
      <div class="climate-chart">${raw(trendChart(t, ctx.u, t.baseline_mean))}</div></div></div>`);
}

/* ---------------------------------------------------------- saved places */
export function renderSaved(saved, snapshot, ctx) {
  const wrap = $("#saved");
  if (!saved.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const key = (p) => `${(+p.lat).toFixed(2)},${(+p.lon).toFixed(2)}`;
  const snap = Object.fromEntries((snapshot || []).map((s) => [key(s), s]));
  setHTML($("#saved-chips"), html`${saved.map((p, i) => {
    const s = snap[key(p)];
    return html`<span class="chip"><button type="button" class="chip-go" data-i="${i}">${s?.icon ? raw(icon(s.icon, { size: 24 })) : ""}<span>${p.name}</span>${s && isNum(s.temp) ? html`<span class="chip-t num">${fmtTempDeg(s.temp, ctx.u)}</span>` : ""}</button>
      <button type="button" class="chip-x" data-remove="${i}" aria-label="Remove ${p.name} from saved places">\u00d7</button></span>`;
  })}`);
}
