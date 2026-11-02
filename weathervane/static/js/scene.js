// The living sky: a gradient (CSS) plus a canvas layer that reacts to live data.
// Rain and snow slant with the real wind; storms flash; clear nights twinkle.
import { clamp } from "./util.js";

const reduceMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function createScene(canvas) {
  const ctx = canvas.getContext("2d");
  let w = 0, h = 0, dpr = 1;
  let mode = { scene: "clear", isDay: true, wind: 0, dir: 270, intensity: 0.5 };
  let parts = [], raf = 0, last = 0, flash = 0, nextFlash = 0, bolt = null, shoot = null, nextShoot = 0;
  let fadeTimer = 0, resizeFrame = 0, ready = false;

  function size() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function resize() {
    size();
    build();
    if (reduceMotion()) frame(16, true);
  }
  // Mobile browsers fire "resize" whenever the address bar slides away while scrolling. Rebuilding the
  // particles each time made rain and stars visibly reshuffle, so only rebuild on a real size change.
  function onResize() {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      const realChange = window.innerWidth !== w || Math.abs(window.innerHeight - h) > 160;
      if (realChange) resize(); else { size(); if (reduceMotion()) frame(16, true); }
    });
  }

  // Horizontal lean of falling particles: positive = drifting right.
  const lean = () => Math.sin(((mode.dir + 180) * Math.PI) / 180) * clamp(mode.wind, 0, 60) / 60 * 0.6;

  function build() {
    const { scene, isDay, intensity } = mode;
    const area = (w * h) / (1280 * 720);
    parts = [];
    if (scene === "rain" || scene === "storm") {
      const n = Math.round((90 + intensity * 170 + (scene === "storm" ? 80 : 0)) * Math.max(0.5, area));
      for (let i = 0; i < n; i++) parts.push({ x: Math.random() * (w + 200) - 100, y: Math.random() * h, l: 12 + Math.random() * 18, v: 0.9 + Math.random() * 0.7, a: 0.25 + Math.random() * 0.35 });
    } else if (scene === "snow") {
      const n = Math.round((70 + intensity * 150) * Math.max(0.5, area));
      for (let i = 0; i < n; i++) parts.push({ x: Math.random() * w, y: Math.random() * h, r: 1 + Math.random() * 2.6, v: 0.25 + Math.random() * 0.5, ph: Math.random() * 6.28, a: 0.5 + Math.random() * 0.45 });
    } else if (!isDay && (scene === "clear" || scene === "cloudy")) {
      const n = scene === "clear" ? 170 : 60;
      for (let i = 0; i < n; i++) parts.push({ x: Math.random() * w, y: Math.random() * h * 0.75, r: Math.random() * 1.3 + 0.2, ph: Math.random() * 6.28, sp: 0.5 + Math.random() * 1.5 });
    }
    if (scene === "cloudy" || scene === "fog" || scene === "rain" || scene === "storm" || scene === "snow" || (scene === "clear" && isDay)) {
      const count = scene === "fog" ? 6 : scene === "clear" ? 3 : 5;
      for (let i = 0; i < count; i++) parts.push({ cloud: true, x: Math.random() * w, y: scene === "fog" ? h * (0.35 + Math.random() * 0.6) : h * (0.04 + Math.random() * 0.4), rx: w * (0.18 + Math.random() * 0.25), ry: h * (scene === "fog" ? 0.13 : 0.09), v: 0.006 + Math.random() * 0.012, a: scene === "fog" ? 0.2 : scene === "clear" ? 0.12 : 0.16 });
    }
  }

  function drawOrb() {
    const { scene, isDay } = mode;
    if (scene === "clear" || (scene === "cloudy" && mode.intensity < 0.5)) {
      const x = w * 0.78, y = h * 0.2, r = Math.min(w, h) * (isDay ? 0.34 : 0.2);
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      if (isDay) { g.addColorStop(0, "rgba(255,244,214,.9)"); g.addColorStop(0.08, "rgba(255,226,150,.5)"); g.addColorStop(1, "rgba(255,226,150,0)"); }
      else { g.addColorStop(0, "rgba(235,242,255,.85)"); g.addColorStop(0.1, "rgba(200,215,255,.3)"); g.addColorStop(1, "rgba(200,215,255,0)"); }
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    }
  }

  function frame(dt, still = false) {
    ctx.clearRect(0, 0, w, h);
    drawOrb();
    const k = dt / 16.7, lx = lean(), { scene, isDay } = mode;
    const tint = isDay ? "255,255,255" : "190,205,225";

    for (const p of parts) {
      if (p.cloud) {
        if (!still) { p.x += p.v * dt * (1 + mode.wind / 25); if (p.x - p.rx > w) p.x = -p.rx; }
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.rx);
        const dark = scene === "storm" ? "30,36,58" : scene === "rain" ? "70,86,102" : isDay ? tint : "70,85,105";
        g.addColorStop(0, `rgba(${dark},${p.a})`); g.addColorStop(1, `rgba(${dark},0)`);
        ctx.save(); ctx.translate(p.x, p.y); ctx.scale(1, p.ry / p.rx); ctx.translate(-p.x, -p.y);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, p.rx, 0, 6.283); ctx.fill(); ctx.restore();
      } else if (scene === "rain" || scene === "storm") {
        if (!still) { p.y += 16 * p.v * k; p.x += 16 * p.v * k * lx; if (p.y > h + 20) { p.y = -20; p.x = Math.random() * (w + 200) - 100; } }
        ctx.strokeStyle = `rgba(190,220,245,${p.a})`; ctx.lineWidth = 1.1;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.l * lx, p.y - p.l * 0.96); ctx.stroke();
      } else if (scene === "snow") {
        if (!still) { p.ph += 0.01 * k; p.y += 1.4 * p.v * k; p.x += (Math.sin(p.ph) * 0.35 + lx * 2) * k; if (p.y > h + 6) { p.y = -6; p.x = Math.random() * w; } if (p.x > w + 6) p.x = -6; if (p.x < -6) p.x = w + 6; }
        ctx.fillStyle = `rgba(255,255,255,${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      } else if (!isDay) {
        if (!still) p.ph += 0.02 * p.sp * k;
        ctx.fillStyle = `rgba(255,255,255,${0.35 + 0.45 * Math.abs(Math.sin(p.ph))})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      }
    }

    if (still) return;
    const now = performance.now();
    if (scene === "storm") {
      if (now > nextFlash) { flash = 1; nextFlash = now + 4000 + Math.random() * 7000; bolt = makeBolt(); }
      if (flash > 0) {
        ctx.fillStyle = `rgba(210,220,255,${flash * 0.28})`; ctx.fillRect(0, 0, w, h);
        if (bolt && flash > 0.35) drawBolt(flash);
        flash -= 0.045 * k; if (flash <= 0) bolt = null;
      }
    }
    if (scene === "clear" && !isDay) {
      if (!shoot && now > nextShoot) { shoot = { x: Math.random() * w * 0.7 + w * 0.1, y: Math.random() * h * 0.3, life: 1 }; nextShoot = now + 9000 + Math.random() * 14000; }
      if (shoot) {
        const x2 = shoot.x - 90 * (1 - shoot.life) * 3, y2 = shoot.y + 40 * (1 - shoot.life) * 3;
        ctx.strokeStyle = `rgba(255,255,255,${shoot.life})`; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x2 + 60, y2 - 26); ctx.stroke();
        shoot.life -= 0.03 * k; if (shoot.life <= 0) shoot = null;
      }
    }
  }

  function makeBolt() {
    let x = w * (0.2 + Math.random() * 0.6), y = 0; const pts = [[x, y]];
    while (y < h * 0.55) { x += (Math.random() - 0.5) * 70; y += 25 + Math.random() * 35; pts.push([x, y]); }
    return pts;
  }
  function drawBolt(a) {
    ctx.strokeStyle = `rgba(235,240,255,${a})`; ctx.lineWidth = 2.2; ctx.shadowColor = "rgba(180,200,255,.9)"; ctx.shadowBlur = 18;
    ctx.beginPath(); bolt.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); ctx.shadowBlur = 0;
  }

  function loop(t) {
    raf = requestAnimationFrame(loop);
    const dt = Math.min(50, t - (last || t)); last = t;
    frame(dt);
  }
  function start() { cancelAnimationFrame(raf); last = 0; if (reduceMotion()) frame(16, true); else raf = requestAnimationFrame(loop); }

  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancelAnimationFrame(raf); else start(); });

  return {
    set({ scene = "clear", isDay = true, wind = 0, dir = 270, intensity = 0.5 }) {
      const next = { scene, isDay, wind, dir, intensity: clamp(intensity, 0, 1) };
      document.body.dataset.scene = `${scene}-${isDay ? "day" : "night"}`;
      const changed = !ready || next.scene !== mode.scene || next.isDay !== mode.isDay || Math.abs(next.intensity - mode.intensity) > 0.12;
      if (!changed) {
        // Same sky (e.g. a routine refresh): just let wind and direction drift, keep every particle where it is.
        clearTimeout(fadeTimer); canvas.style.opacity = "1"; mode = next; return;
      }
      const apply = () => {
        mode = next; bolt = null; flash = 0; shoot = null;
        nextFlash = performance.now() + 1500; nextShoot = performance.now() + 3000;
        resize(); canvas.style.opacity = "1"; start();
      };
      clearTimeout(fadeTimer);
      if (!ready || reduceMotion()) { ready = true; apply(); return; }
      // Fade the old sky out, swap, fade the new one in. The gradient behind transitions on its own.
      canvas.style.opacity = "0";
      fadeTimer = setTimeout(apply, 400);
    },
    init() { resize(); start(); },
  };
}
