// Flat, consistent weather icons on a 64x64 grid. No external assets.
const SUN = "#ffd166", MOON = "#e6edfb", CLOUD = "#eef4f8", CLOUD_SHADE = "#b4c4d2", DARK = "#8a9bb0", DROP = "#79c4ff", BOLT = "#ffd166";

const sun = (cx = 32, cy = 32, r = 11, rays = true) => {
  let g = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${SUN}"/>`;
  if (rays) {
    for (let i = 0; i < 8; i++) {
      const a = (i * Math.PI) / 4, r1 = r + 4, r2 = r + 9;
      g += `<line x1="${(cx + Math.cos(a) * r1).toFixed(1)}" y1="${(cy + Math.sin(a) * r1).toFixed(1)}" x2="${(cx + Math.cos(a) * r2).toFixed(1)}" y2="${(cy + Math.sin(a) * r2).toFixed(1)}" stroke="${SUN}" stroke-width="3" stroke-linecap="round"/>`;
    }
  }
  return g;
};
const moon = (cx = 32, cy = 32, r = 14) =>
  `<path d="M${cx + 5} ${cy - r + 1}a${r} ${r} 0 1 0 ${r - 1} ${r + 6}a${r - 3} ${r - 3} 0 0 1 -${r - 1} -${r + 6}z" fill="${MOON}"/>`;
const cloud = (fill = CLOUD, shade = CLOUD_SHADE, dx = 0, dy = 0, s = 1) =>
  `<g transform="translate(${dx} ${dy}) scale(${s})"><g fill="${shade}"><circle cx="21" cy="40" r="9"/><circle cx="46" cy="40" r="9"/><rect x="21" y="38" width="25" height="11"/></g>` +
  `<g fill="${fill}"><circle cx="21" cy="38" r="9"/><circle cx="33" cy="30" r="13"/><circle cx="46" cy="38" r="9"/><rect x="21" y="36" width="25" height="11" rx="1"/></g></g>`;
const drops = (n, y = 50, color = DROP, long = false) => {
  const xs = n === 2 ? [27, 40] : n === 3 ? [22, 33, 44] : [33];
  return xs.map((x, i) => `<line x1="${x}" y1="${y + (i % 2) * 3}" x2="${x - 3}" y2="${y + (long ? 11 : 7) + (i % 2) * 3}" stroke="${color}" stroke-width="3" stroke-linecap="round"/>`).join("");
};
const flakes = (n) => [22, 33, 44].slice(0, n).map((x, i) => `<circle cx="${x}" cy="${53 + (i % 2) * 3}" r="2.6" fill="#fff"/>`).join("");
const bolt = () => `<path d="M35 42l-8 12h6l-3 9 11-14h-6l4-7z" fill="${BOLT}" stroke="#e5a93a" stroke-width=".8" stroke-linejoin="round"/>`;
const fog = () => [46, 53, 60].map((y, i) => `<line x1="${14 + i * 3}" y1="${y}" x2="${50 - (i % 2) * 6}" y2="${y}" stroke="#d3dde6" stroke-width="3" stroke-linecap="round"/>`).join("");

const ICONS = {
  "clear-day": () => sun(32, 32, 11),
  "clear-night": () => moon(),
  "mostly-clear-day": () => sun(28, 28, 10) + cloud("#f6fafc", CLOUD_SHADE, 8, 8, .62),
  "mostly-clear-night": () => moon(26, 26, 12) + cloud("#dfe8f0", "#9fb0c2", 10, 10, .55),
  "partly-day": () => sun(25, 24, 10) + cloud(CLOUD, CLOUD_SHADE, 4, 4, .9),
  "partly-night": () => moon(24, 24, 12) + cloud(CLOUD, CLOUD_SHADE, 4, 4, .9),
  overcast: () => cloud("#c5d1db", "#8798aa", 0, -4, 1) + cloud(CLOUD, CLOUD_SHADE, 4, 4, .85),
  fog: () => cloud(CLOUD, CLOUD_SHADE, 0, -8, .95) + fog(),
  drizzle: () => cloud(CLOUD, CLOUD_SHADE, 0, -6) + drops(3, 49, DROP),
  rain: () => cloud("#d6e0e9", "#9aabbc", 0, -6) + drops(3, 48),
  "rain-heavy": () => cloud("#aebccb", "#7b8da1", 0, -8) + drops(3, 46, DROP, true) + drops(2, 55, DROP, true),
  "showers-day": () => sun(22, 20, 8) + cloud("#d6e0e9", "#9aabbc", 4, -2, .9) + drops(2, 48),
  "showers-night": () => moon(22, 20, 10) + cloud("#d6e0e9", "#9aabbc", 4, -2, .9) + drops(2, 48),
  sleet: () => cloud("#d6e0e9", "#9aabbc", 0, -6) + drops(2, 48) + `<circle cx="44" cy="55" r="2.6" fill="#fff"/>`,
  snow: () => cloud("#dfe8f0", "#a6b6c6", 0, -6) + flakes(3),
  "snow-heavy": () => cloud("#b6c3d0", "#8193a6", 0, -8) + flakes(3) + `<circle cx="27" cy="60" r="2.2" fill="#fff"/><circle cx="39" cy="61" r="2.2" fill="#fff"/>`,
  thunder: () => cloud("#8d9db2", "#5e7089", 0, -8) + bolt(),
};

export function icon(name, { size = 32, cls = "" } = {}) {
  const draw = ICONS[name] || ICONS.overcast;
  return `<svg class="ico ${cls}" viewBox="0 0 64 64" width="${size}" height="${size}" role="img" aria-hidden="true" focusable="false">${draw()}</svg>`;
}
