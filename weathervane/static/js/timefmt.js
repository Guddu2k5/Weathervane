// The API returns wall-clock strings for the *place* ("2026-10-10T14:00").
// Never pass them through Date with a timezone: parse the parts instead.
const WD = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MO = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(s || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: +(m[4] ?? 0), mi: +(m[5] ?? 0) } : null;
}
const dayNum = (p) => Date.UTC(p.y, p.mo - 1, p.d) / 86400000;
export const dayDiff = (a, b) => { const pa = parseLocal(a), pb = parseLocal(b); return pa && pb ? dayNum(pa) - dayNum(pb) : 0; };
export const weekdayIndex = (s) => { const p = parseLocal(s); return p ? new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay() : 0; };

export function fmtClock(s, hour12, { minutes = true } = {}) {
  const p = parseLocal(s); if (!p) return "--";
  const mm = String(p.mi).padStart(2, "0");
  if (!hour12) return `${String(p.h).padStart(2, "0")}:${mm}`;
  const h = p.h % 12 || 12, ap = p.h < 12 ? "am" : "pm";
  return minutes && p.mi ? `${h}:${mm} ${ap}` : `${h} ${ap}`;
}
export const fmtHour = (s, hour12) => (hour12 ? fmtClock(s, true, { minutes: false }) : fmtClock(s, false));

export function weekdayName(dateStr, nowStr, { short = false } = {}) {
  const diff = dayDiff(dateStr, nowStr);
  if (diff === 0) return "Today";
  if (diff === 1 && !short) return "Tomorrow";
  const n = WD[weekdayIndex(dateStr)];
  return short ? n.slice(0, 3) : n;
}
export function fmtDay(dateStr) { const p = parseLocal(dateStr); return p ? `${p.d} ${MO[p.mo - 1].slice(0, 3)}` : ""; }
export function fmtLongDate(s) { const p = parseLocal(s); return p ? `${WD[weekdayIndex(s)]} ${p.d} ${MO[p.mo - 1]}` : ""; }

// "3 pm", "tomorrow 3 am"
export function fmtWhen(s, nowS, hour12) {
  const diff = dayDiff(s, nowS);
  const t = fmtClock(s, hour12);
  if (diff === 0) return t;
  if (diff === 1) return `tomorrow ${t}`;
  return `${WD[weekdayIndex(s)].slice(0, 3)} ${t}`;
}
export function fmtRelativeMinutes(iso) {
  const mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (!Number.isFinite(mins) || mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  return `${Math.round(mins / 60)} h ago`;
}
