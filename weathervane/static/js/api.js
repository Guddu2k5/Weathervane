// Thin client for the Weathervane JSON API.
export class ApiError extends Error {
  constructor(message, { code = "error", status = 0 } = {}) { super(message); this.code = code; this.status = status; }
}

async function request(path, params = {}, { signal, timeoutMs = 45000 } = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const ctl = new AbortController();
  const onAbort = () => ctl.abort();
  if (signal) { if (signal.aborted) ctl.abort(); else signal.addEventListener("abort", onAbort, { once: true }); }
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, timeoutMs);
  try {
    const res = await fetch(url, { signal: ctl.signal, headers: { Accept: "application/json" } });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error page */ }
    if (!res.ok) {
      const e = data && data.error;
      throw new ApiError(e?.message || `The server returned an error (${res.status}).`, { code: e?.code, status: res.status });
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === "AbortError") {
      if (timedOut) throw new ApiError("The request took too long. Please try again.", { code: "timeout" });
      throw err; // caller cancelled on purpose
    }
    throw new ApiError("Can't reach the Weathervane server. Make sure it is running (python run.py), then retry.", { code: "offline" });
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onAbort);
  }
}

export const api = {
  health: (o) => request("/api/health", {}, o),
  search: (q, o) => request("/api/search", { q, count: 8 }, o),
  reverse: (lat, lon, o) => request("/api/reverse", { lat, lon }, o),
  weather: (lat, lon, o) => request("/api/weather", { lat, lon }, o),
  insights: (lat, lon, o) => request("/api/insights", { lat, lon }, { timeoutMs: 120000, ...o }),
  snapshot: (places, o) => request("/api/snapshot", { places: places.map((p) => `${p.lat},${p.lon}`).join(";") }, o),
};
