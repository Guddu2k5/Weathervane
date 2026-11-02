import { $, $$, html, raw, setHTML, debounce, storage, store, clamp } from "./util.js";
import { api, ApiError } from "./api.js";
import { DEFAULT_UNITS, PRESETS, systemHour12, sanitizeUnits } from "./units.js";
import { createScene } from "./scene.js";
import { initMap, showOnMap } from "./map.js";
import * as R from "./render.js";

/* ------------------------------------------------------------------ state */
const state = { place: null, wx: null, insights: null, saved: [], snapshot: [], recents: [] };
const units = sanitizeUnits(storage("wv.units", {}));
const ctx = { u: units, hour12: false, expanded: new Set() };
const refreshHour12 = () => { ctx.hour12 = units.hour12 === null || units.hour12 === undefined ? systemHour12() : !!units.hour12; };
refreshHour12();

const scene = createScene($("#sky-canvas"));
let token = 0, controller = null, insightsCtl = null, mapReady = false, lastLoad = 0, demoMode = false;
const key = (p) => `${(+p.lat).toFixed(2)},${(+p.lon).toFixed(2)}`;

/* ---------------------------------------------------------------- helpers */
function toast(msg) {
  const el = $("#toast");
  clearTimeout(toast.t); clearTimeout(toast.c);
  el.textContent = msg; el.classList.add("show");
  toast.t = setTimeout(() => { el.classList.remove("show"); toast.c = setTimeout(() => { el.textContent = ""; }, 320); }, 3200);
}
const isBusy = () => $("#app").getAttribute("aria-busy") === "true";
// Staggered fade-up each time a new place finishes loading (styles live in styles.css under "Motion").
function playEnter() {
  const app = $("#app");
  app.classList.remove("enter"); void app.offsetWidth; app.classList.add("enter");
  clearTimeout(playEnter.t); playEnter.t = setTimeout(() => app.classList.remove("enter"), 1700);
}
function showStatus(title, message, retry) {
  const el = $("#status");
  setHTML(el, html`<h2>${title}</h2><p>${message}</p>${retry ? html`<button class="primary-btn" type="button" id="retry">Try again</button>` : ""}`);
  el.hidden = false;
  if (retry) $("#retry").addEventListener("click", retry);
}
const subOf = (r) => [r.admin1, r.country].filter((v, i, a) => v && v !== r.name && a.indexOf(v) === i).join(", ");
const toPlace = (r) => ({ name: r.name, sub: subOf(r), lat: r.lat, lon: r.lon });
const isDayNow = () => { const h = new Date().getHours(); return h >= 6 && h < 19; };

function setBanner(id, content) {
  let el = document.getElementById(id);
  if (!content) { el && el.remove(); return; }
  if (!el) { el = document.createElement("div"); el.id = id; el.className = "banner"; $("#banners").appendChild(el); }
  setHTML(el, content);
}

/* ------------------------------------------------------------------ render */
function renderAll() {
  if (!state.wx) return;
  const { wx, place, insights } = state;
  R.renderHero(wx, place, ctx, insights);
  R.renderUpdated(wx);
  R.renderAlerts(wx, ctx);
  R.renderHourly(wx, ctx);
  R.renderDaily(wx, ctx, insights);
  R.renderGuidance(wx, ctx);
  insights ? R.renderInsights(insights, wx, ctx) : R.renderInsightsLoading();
  insights ? R.renderClimate(insights, ctx) : R.renderClimateLoading();
  R.renderAir(wx, ctx);
  R.renderSun(wx, ctx);
  R.renderWind(wx, ctx);
  R.renderConditions(wx, ctx);
  R.renderSaved(state.saved, state.snapshot, ctx);
  syncSaveButton();
}

// When ML insights arrive, update only the cards that use them, so an open tooltip,
// the hourly strip's scroll position and expanded days are left untouched.
function renderInsightCards() {
  const { wx, place, insights } = state;
  if (!wx || !insights) return;
  R.renderHero(wx, place, ctx, insights);
  R.renderDaily(wx, ctx, insights);
  R.renderInsights(insights, wx, ctx);
  R.renderClimate(insights, ctx);
}

function applyScene(wx) {
  const c = wx.current;
  const mm = Math.max(c.precip || 0, wx.hourly[0]?.precip || 0);
  scene.set({ scene: c.scene, isDay: c.is_day, wind: c.wind.speed || 0, dir: c.wind.dir ?? 270, intensity: clamp(mm / 5, 0.1, 1) });
}

/* -------------------------------------------------------------- loading */
async function loadPlace(place, { silent = false } = {}) {
  const my = ++token, prev = state.place;
  if (controller) controller.abort();
  controller = new AbortController();
  const { signal } = controller;
  state.place = place;

  $("#welcome").hidden = true; $("#status").hidden = true; $("#app").hidden = false;
  if (!silent) {
    // A background refresh must not abort an in-flight insights request or dim the page.
    if (insightsCtl) insightsCtl.abort();
    $("#app").setAttribute("aria-busy", "true");
    $("#place-name").textContent = place.name; $("#place-sub").textContent = place.sub || "";
  }

  let wx;
  try {
    wx = await api.weather(place.lat, place.lon, { signal });
  } catch (err) {
    if (err.name === "AbortError" || my !== token) return;
    $("#app").removeAttribute("aria-busy");
    if (silent && state.wx) { toast("Couldn't refresh the forecast. Showing the last update."); return; }
    if (state.wx && prev) {
      // The new place failed to load, so the old forecast is still on screen: put its name back instead of
      // showing the old weather under the new place's name.
      state.place = prev;
      R.renderHero(state.wx, prev, ctx, state.insights); syncSaveButton();
    }
    $("#app").hidden = !state.wx;
    showStatus("We couldn't load that forecast", err instanceof ApiError ? err.message : "Something went wrong.", () => loadPlace(place));
    return;
  }
  if (my !== token) return;

  state.wx = wx; lastLoad = Date.now();
  if (!silent) { state.insights = null; ctx.expanded = new Set(); }
  $("#app").removeAttribute("aria-busy");
  setBanner("demo-banner", wx.meta?.demo ? demoBanner() : null);
  demoMode = !!wx.meta?.demo;
  if (demoMode) bindDemoScene();
  applyScene(wx);
  renderAll();

  if (!silent) {
    $("#hourly-strip").scrollLeft = 0; playEnter();
    document.title = `${place.name} ${Math.round(wx.current.temp)}\u00b0 \u2013 Weathervane`;
    history.replaceState(null, "", `?lat=${place.lat}&lon=${place.lon}&name=${encodeURIComponent(place.name)}&sub=${encodeURIComponent(place.sub || "")}`);
    pushRecent(place);
    if (!mapReady) { mapReady = initMap($("#map"), pickOnMap); if (!mapReady) { $("#map-fallback").hidden = false; $("#map").hidden = true; } }
    if (mapReady) showOnMap(place.lat, place.lon);
    loadInsights(place, my);
  }
  refreshSnapshot();
}

async function loadInsights(place, my) {
  if (insightsCtl) insightsCtl.abort();
  insightsCtl = new AbortController();
  try {
    const ins = await api.insights(place.lat, place.lon, { signal: insightsCtl.signal });
    if (my !== token) return;
    state.insights = ins; renderInsightCards();
  } catch (err) {
    if (err.name === "AbortError" || my !== token) return;
    state.insights = { days: [], trend: null, notes: [err.message], method: {} };
    R.renderInsights(state.insights, state.wx, ctx); R.renderClimate(state.insights, ctx);
  }
}

async function refreshSnapshot() {
  if (!state.saved.length) { state.snapshot = []; return; }
  try { state.snapshot = (await api.snapshot(state.saved)).items; R.renderSaved(state.saved, state.snapshot, ctx); } catch { /* chips still work without temps */ }
}

/* ------------------------------------------------------- reverse geocoding */
async function resolveName(lat, lon, my) {
  try {
    const { place } = await api.reverse(lat, lon);
    if (my !== token || !place?.resolved || !state.wx) return;
    const name = place.name, sub = [place.admin1, place.country].filter((v, i, a) => v && v !== name && a.indexOf(v) === i).join(", ");
    state.place = { ...state.place, name, sub };
    $("#place-name").textContent = name; $("#place-sub").textContent = ""; renderAll();
    document.title = `${name} ${Math.round(state.wx.current.temp)}\u00b0 \u2013 Weathervane`;
    history.replaceState(null, "", `?lat=${lat}&lon=${lon}&name=${encodeURIComponent(name)}&sub=${encodeURIComponent(sub)}`);
  } catch { /* keep the coordinate label */ }
}
async function pickCoordinates(lat, lon, label) {
  lat = +lat.toFixed(4); lon = +lon.toFixed(4);
  await loadPlace({ name: label, sub: `${lat.toFixed(2)}, ${lon.toFixed(2)}`, lat, lon });
  resolveName(lat, lon, token);
}
const pickOnMap = (lat, lon) => pickCoordinates(lat, lon, "Pinned location");

function locate() {
  if (!navigator.geolocation) { toast("Your browser doesn't support location. Try searching instead."); return; }
  toast("Finding your location\u2026");
  navigator.geolocation.getCurrentPosition(
    (pos) => pickCoordinates(pos.coords.latitude, pos.coords.longitude, "Your location"),
    (err) => toast(err.code === 1 ? "Location permission was denied. You can search for a place instead." : "Couldn't determine your location. Try searching instead."),
    { enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 },
  );
}

/* ------------------------------------------------------------------ search */
const input = $("#q"), list = $("#suggestions");
const KIND = { country: "Country", region: "Region", district: "District", capital: "Capital", city: "City", town: "Town", neighbourhood: "Neighbourhood", coordinates: "Coordinates", place: "Place" };
let results = [], active = -1, searchCtl = null, lastQuery = "";

function openList(content) { setHTML(list, content); list.hidden = false; input.setAttribute("aria-expanded", "true"); }
function closeList() { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); active = -1; }
function highlight(i) {
  active = i;
  $$('[role="option"]', list).forEach((li, n) => li.setAttribute("aria-selected", String(n === i)));
  const li = $$('[role="option"]', list)[i];
  if (li) { input.setAttribute("aria-activedescendant", li.id); li.scrollIntoView({ block: "nearest" }); } else input.removeAttribute("aria-activedescendant");
}
function renderResults() {
  if (!results.length) { openList(html`<li class="sg-msg">No places found. Try a nearby city, a postal code, or coordinates like 12.97, 77.59.</li>`); return; }
  openList(html`${results.map((r, i) => html`<li role="option" id="sg-${i}" data-i="${i}" aria-selected="false">
    <span><span class="sg-name">${r.name}</span><br><span class="sg-sub">${subOf(r)}</span></span><span class="sg-kind">${KIND[r.kind] || "Place"}</span></li>`)}`);
}
function showRecents() {
  if (!state.recents.length) { closeList(); return; }
  results = state.recents.map((p) => ({ name: p.name, admin1: p.sub, country: null, lat: p.lat, lon: p.lon, kind: "place", recent: true }));
  openList(html`<li class="sg-head" role="presentation">Recent places</li>${results.map((r, i) => html`<li role="option" id="sg-${i}" data-i="${i}" aria-selected="false"><span><span class="sg-name">${r.name}</span><br><span class="sg-sub">${r.admin1}</span></span></li>`)}`);
}

const runSearch = debounce(async (q) => {
  if (searchCtl) searchCtl.abort();
  searchCtl = new AbortController();
  try {
    const data = await api.search(q, { signal: searchCtl.signal });
    if (q !== input.value.trim()) return;
    results = data.results; lastQuery = q; renderResults();
  } catch (err) {
    if (err.name === "AbortError") return;
    openList(html`<li class="sg-msg">${err.message}</li>`);
  }
}, 220);

function choose(r) {
  closeList(); input.value = ""; input.blur();
  loadPlace(r.recent ? { name: r.name, sub: r.admin1 || "", lat: r.lat, lon: r.lon } : toPlace(r));
}

input.addEventListener("input", () => {
  const q = input.value.trim();
  if (q.length < 2) { runSearch.cancel(); if (searchCtl) searchCtl.abort(); q.length === 0 ? showRecents() : closeList(); return; }
  openList(html`<li class="sg-msg">Searching\u2026</li>`); runSearch(q);
});
input.addEventListener("focus", () => { if (!input.value.trim()) showRecents(); });
input.addEventListener("keydown", (e) => {
  const n = $$('[role="option"]', list).length;
  if (e.key === "ArrowDown" && !list.hidden && n) { e.preventDefault(); highlight((active + 1) % n); }
  else if (e.key === "ArrowUp" && !list.hidden && n) { e.preventDefault(); highlight((active - 1 + n) % n); }
  else if (e.key === "Escape") { closeList(); }
  else if (e.key === "Enter" && active >= 0 && results[active]) { e.preventDefault(); choose(results[active]); }
});
list.addEventListener("mousedown", (e) => { // mousedown so the input doesn't blur first
  const li = e.target.closest('[role="option"]'); if (li) { e.preventDefault(); choose(results[+li.dataset.i]); }
});
document.addEventListener("click", (e) => { if (e.target.isConnected && !e.target.closest(".search")) closeList(); });

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (q.length < 2) { toast("Type at least 2 characters to search."); return; }
  if (results.length && lastQuery === q && !results[0].recent) { choose(results[0]); return; }
  try {
    const data = await api.search(q);
    if (data.results.length) choose(data.results[0]); else { results = []; renderResults(); }
  } catch (err) { openList(html`<li class="sg-msg">${err.message}</li>`); }
});
$("#locate").addEventListener("click", locate);
$("#welcome-locate").addEventListener("click", locate);

/* --------------------------------------------------------- recents & saved */
function pushRecent(p) {
  state.recents = [{ name: p.name, sub: p.sub, lat: p.lat, lon: p.lon }, ...state.recents.filter((r) => key(r) !== key(p))].slice(0, 6);
  store("wv.recent", state.recents);
}
function syncSaveButton() {
  const on = state.place && state.saved.some((s) => key(s) === key(state.place));
  const b = $("#save-btn"); b.setAttribute("aria-pressed", String(!!on));
  b.setAttribute("aria-label", on ? "Remove this place from saved places" : "Save this place");
  b.title = on ? "Saved. Click to remove" : "Save this place";
}
$("#save-btn").addEventListener("click", () => {
  const p = state.place; if (!p) return;
  const i = state.saved.findIndex((s) => key(s) === key(p));
  if (i >= 0) { state.saved.splice(i, 1); toast("Removed from saved places."); }
  else if (state.saved.length >= 12) { toast("You can save up to 12 places."); return; }
  else { state.saved.push({ name: p.name, sub: p.sub, lat: p.lat, lon: p.lon }); toast("Saved."); }
  store("wv.saved", state.saved); R.renderSaved(state.saved, state.snapshot, ctx); syncSaveButton(); refreshSnapshot();
});
$("#saved-chips").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-remove]"), go = e.target.closest("[data-i]");
  if (rm) { state.saved.splice(+rm.dataset.remove, 1); store("wv.saved", state.saved); R.renderSaved(state.saved, state.snapshot, ctx); syncSaveButton(); }
  else if (go) { const p = state.saved[+go.dataset.i]; if (p) { window.scrollTo({ top: 0, behavior: "smooth" }); loadPlace(p); } }
});
$("#share-btn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(location.href); toast("Link copied."); } catch { toast("Copy the address from your browser's address bar."); }
});

/* ------------------------------------------------------------------- units */
const UNIT_GROUPS = [
  ["wind", "Wind", [["kmh", "km/h"], ["mph", "mph"], ["ms", "m/s"], ["kn", "kn"]]],
  ["pressure", "Pressure", [["hpa", "hPa"], ["inhg", "inHg"], ["mmhg", "mmHg"]]],
  ["precip", "Rain", [["mm", "mm"], ["in", "in"]]],
  ["dist", "Visibility", [["km", "km"], ["mi", "mi"]]],
  ["hour12", "Clock", [[false, "24 h"], [true, "12 h"]]],
];
function renderUnitsPopover() {
  const cur = (k) => (k === "hour12" ? ctx.hour12 : units[k]);
  setHTML($("#units-pop"), html`
    <div class="pop-presets"><button type="button" data-preset="metric">Metric</button><button type="button" data-preset="imperial">Imperial</button></div>
    ${UNIT_GROUPS.map(([k, label, opts]) => html`<div class="pop-row"><span>${label}</span><div class="seg" role="group" aria-label="${label}">
      ${opts.map(([v, text]) => html`<button type="button" data-k="${k}" data-v="${String(v)}" aria-pressed="${String(cur(k) === v)}">${text}</button>`)}</div></div>`)}`);
}
function syncTempButtons() { $$(".controls [data-temp]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.temp === units.temp))); }
function unitsChanged() {
  // Re-rendering the popover replaces its buttons, which would drop keyboard focus; put it back afterwards.
  const f = document.activeElement, inPop = !!(f && f.closest && f.closest("#units-pop"));
  const sel = inPop ? (f.dataset.preset ? `[data-preset="${f.dataset.preset}"]` : `[data-k="${f.dataset.k}"][data-v="${f.dataset.v}"]`) : null;
  store("wv.units", units); refreshHour12(); syncTempButtons(); renderUnitsPopover();
  if (sel) $(sel, $("#units-pop"))?.focus({ preventScroll: true });
  if (state.wx) renderAll();
}
$$(".controls [data-temp]").forEach((b) => b.addEventListener("click", () => { units.temp = b.dataset.temp; unitsChanged(); }));
$("#units-pop").addEventListener("click", (e) => {
  const preset = e.target.closest("[data-preset]"), b = e.target.closest("[data-k]");
  if (preset) { Object.assign(units, PRESETS[preset.dataset.preset], { hour12: preset.dataset.preset === "imperial" ? true : false }); unitsChanged(); }
  else if (b) { const v = b.dataset.v; units[b.dataset.k] = b.dataset.k === "hour12" ? v === "true" : v; unitsChanged(); }
});
const popBtn = $("#units-btn"), pop = $("#units-pop");
function setPop(open) { pop.hidden = !open; popBtn.setAttribute("aria-expanded", String(open)); }
popBtn.addEventListener("click", () => setPop(pop.hidden));
document.addEventListener("click", (e) => { if (e.target.isConnected && !e.target.closest(".popover-wrap")) setPop(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { setPop(false); popBtn.focus({ preventScroll: true }); } });

/* ------------------------------------------------------------- day details */
$("#daily-list").addEventListener("click", (e) => {
  const row = e.target.closest(".day-row"); if (!row) return;
  const date = row.dataset.date, open = row.getAttribute("aria-expanded") !== "true";
  open ? ctx.expanded.add(date) : ctx.expanded.delete(date);
  row.setAttribute("aria-expanded", String(open));
  document.getElementById(`dd-${date}`).classList.toggle("open", open);
});

/* ------------------------------------------------------------- demo helpers */
function demoBanner() {
  return html`<span><strong>Demo mode.</strong> You are looking at synthetic data, not real weather.</span>
    <label>Preview sky <select id="demo-scene" aria-label="Preview sky">${["auto", "clear", "cloudy", "rain", "snow", "storm", "fog"].map((s) => html`<option value="${s === "auto" ? "" : s}">${s}</option>`)}</select></label>`;
}
function bindDemoScene() {
  const sel = $("#demo-scene"); if (!sel || sel.dataset.bound) return; sel.dataset.bound = "1";
  sel.addEventListener("change", async () => {
    await fetch(`/api/_demo/scene?name=${encodeURIComponent(sel.value)}`);
    if (state.place) { const keep = sel.value; await loadPlace(state.place); const s2 = $("#demo-scene"); if (s2) s2.value = keep; }
  });
}

/* -------------------------------------------------------------------- boot */
const asArray = (v) => (Array.isArray(v) ? v : []);
const QUICK = [
  { name: "Reykjavik", sub: "Iceland", lat: 64.1355, lon: -21.8954 }, { name: "Nairobi", sub: "Kenya", lat: -1.2833, lon: 36.8167 },
  { name: "Singapore", sub: "", lat: 1.2897, lon: 103.8501 }, { name: "Lima", sub: "Peru", lat: -12.0432, lon: -77.0282 },
  { name: "Auckland", sub: "New Zealand", lat: -36.8485, lon: 174.7635 }, { name: "Tokyo", sub: "Japan", lat: 35.6895, lon: 139.6917 },
];
function boot() {
  state.saved = asArray(storage("wv.saved", [])).filter((p) => p && isFinite(p.lat) && isFinite(p.lon)).slice(0, 12);
  state.recents = asArray(storage("wv.recent", [])).filter((p) => p && isFinite(p.lat) && isFinite(p.lon)).slice(0, 6);
  syncTempButtons(); renderUnitsPopover();
  scene.init(); scene.set({ scene: "clear", isDay: isDayNow(), intensity: 0.3 });

  setHTML($("#quick-picks"), html`${QUICK.map((p, i) => html`<button type="button" data-q="${i}">${p.name}</button>`)}`);
  $("#quick-picks").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) loadPlace(QUICK[+b.dataset.q]); });
  if (state.recents.length) {
    const r = $("#recents"); r.hidden = false;
    setHTML(r, html`<h2>Recently viewed</h2><div class="quick" id="recent-picks">${state.recents.map((p, i) => html`<button type="button" data-r="${i}">${p.name}</button>`)}</div>`);
    r.addEventListener("click", (e) => { const b = e.target.closest("[data-r]"); if (b) loadPlace(state.recents[+b.dataset.r]); });
  }

  api.health().then((h) => { if (h.demo) setBanner("demo-banner", demoBanner()), bindDemoScene(); })
    .catch((err) => setBanner("offline-banner", html`<span><strong>Server not reachable.</strong> ${err.message}</span>`));

  // Deep link, then last place viewed.
  const q = new URLSearchParams(location.search);
  const lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
  if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
    loadPlace({ name: (q.get("name") || "Selected location").slice(0, 80), sub: (q.get("sub") || "").slice(0, 120), lat, lon });
  } else if (state.recents.length) {
    loadPlace(state.recents[0]);
  }
}

// Keep the forecast fresh without nagging: refresh when the tab is visible and data is 10+ minutes old.
const isStale = () => !document.hidden && state.place && state.wx && !isBusy() && Date.now() - lastLoad > 600000;
setInterval(() => { if (isStale()) loadPlace(state.place, { silent: true }); else if (state.wx) R.renderUpdated(state.wx); }, 60000);
document.addEventListener("visibilitychange", () => { if (isStale()) loadPlace(state.place, { silent: true }); });

boot();
