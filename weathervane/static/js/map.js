// Interactive map (Leaflet). Fails soft: if the library or tiles are blocked, the rest of the app still works.
let map = null, marker = null;

export function initMap(el, onPick) {
  if (!window.L) { return false; }
  const L = window.L;
  map = L.map(el, { worldCopyJump: true, minZoom: 2, zoomControl: true, attributionControl: true }).setView([20, 10], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  map.on("click", (e) => onPick(e.latlng.lat, ((e.latlng.lng + 180) % 360 + 360) % 360 - 180));
  return true;
}

export function showOnMap(lat, lon) {
  if (!map || !window.L) return;
  const L = window.L;
  if (!marker) marker = L.circleMarker([lat, lon], { radius: 9, color: "#0f2b3d", weight: 3, fillColor: "#ffd58a", fillOpacity: 1 }).addTo(map);
  else marker.setLatLng([lat, lon]);
  map.setView([lat, lon], Math.max(map.getZoom(), 7), { animate: true });
  setTimeout(() => map.invalidateSize(), 50);
}
