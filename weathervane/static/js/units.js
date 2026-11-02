// All data arrives in metric; conversion and formatting happen here.
const MINUS = "\u2212";

export const DEFAULT_UNITS = { temp: "c", wind: "kmh", pressure: "hpa", precip: "mm", dist: "km", hour12: null };
export const PRESETS = {
  metric: { temp: "c", wind: "kmh", pressure: "hpa", precip: "mm", dist: "km" },
  imperial: { temp: "f", wind: "mph", pressure: "inhg", precip: "in", dist: "mi" },
};

const ALLOWED = { temp: ["c", "f"], wind: ["kmh", "mph", "ms", "kn"], pressure: ["hpa", "inhg", "mmhg"], precip: ["mm", "in"], dist: ["km", "mi"] };
// Settings come from localStorage, which can hold anything. Keep only known-good values.
export function sanitizeUnits(raw) {
  const out = { ...DEFAULT_UNITS };
  if (raw && typeof raw === "object") {
    for (const [k, ok] of Object.entries(ALLOWED)) if (ok.includes(raw[k])) out[k] = raw[k];
    if (typeof raw.hour12 === "boolean") out.hour12 = raw.hour12;
  }
  return out;
}

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const signed = (n, digits) => {
  const r = Number(n.toFixed(digits));
  const s = Math.abs(r).toFixed(digits);
  return r < 0 ? MINUS + s : s;
};

export const convTemp = (c, u) => (u.temp === "f" ? c * 9 / 5 + 32 : c);
export function fmtTemp(c, u, digits = 0) { return isNum(c) ? signed(convTemp(c, u), digits) : "--"; }
export function fmtTempDeg(c, u, digits = 0) { return isNum(c) ? fmtTemp(c, u, digits) + "\u00b0" : "--"; }
// A temperature *difference* converts without the +32 offset.
export function fmtDelta(dc, u, digits = 0) {
  if (!isNum(dc)) return "--";
  const v = u.temp === "f" ? dc * 9 / 5 : dc;
  return signed(v, digits) + "\u00b0";
}
export const tempUnit = (u) => (u.temp === "f" ? "\u00b0F" : "\u00b0C");

const WIND = { kmh: [1, "km/h"], mph: [0.621371, "mph"], ms: [0.277778, "m/s"], kn: [0.539957, "kn"] };
export function fmtWind(kmh, u, digits = 0) { return isNum(kmh) ? (kmh * WIND[u.wind][0]).toFixed(digits) : "--"; }
export const windUnit = (u) => WIND[u.wind][1];

const PRESSURE = { hpa: [1, "hPa", 0], inhg: [0.02953, "inHg", 2], mmhg: [0.750062, "mmHg", 0] };
export function fmtPressure(hpa, u) { const [k, , d] = PRESSURE[u.pressure]; return isNum(hpa) ? (hpa * k).toFixed(d) : "--"; }
export const pressureUnit = (u) => PRESSURE[u.pressure][1];

export function fmtPrecip(mm, u) {
  if (!isNum(mm)) return "--";
  return u.precip === "in" ? (mm / 25.4).toFixed(mm === 0 ? 0 : 2) : (mm >= 10 ? mm.toFixed(0) : mm.toFixed(1));
}
export const precipUnit = (u) => (u.precip === "in" ? "in" : "mm");

export function fmtVisibility(m, u) {
  if (!isNum(m)) return "--";
  if (u.dist === "mi") { const mi = m / 1609.344; return (mi >= 10 ? mi.toFixed(0) : mi.toFixed(1)); }
  const km = m / 1000; return km >= 10 ? km.toFixed(0) : km.toFixed(1);
}
export const distUnit = (u) => (u.dist === "mi" ? "mi" : "km");

export const fmtPct = (v) => (isNum(v) ? `${Math.round(v)}%` : "--");
export function fmtDuration(seconds) {
  if (!isNum(seconds)) return "--";
  const h = Math.floor(seconds / 3600), m = Math.round((seconds % 3600) / 60);
  return m === 60 ? `${h + 1}h 0m` : `${h}h ${m}m`;
}
export function fmtSecondsDelta(s) {
  if (!isNum(s)) return "";
  const a = Math.abs(s), mins = Math.floor(a / 60), secs = a % 60;
  const txt = mins ? `${mins}m ${String(secs).padStart(2, "0")}s` : `${secs}s`;
  if (a < 5) return "about the same length tomorrow";
  return `${txt} ${s > 0 ? "longer" : "shorter"} tomorrow`;
}
export function systemHour12() {
  try { return !!new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions().hour12; } catch { return false; }
}
