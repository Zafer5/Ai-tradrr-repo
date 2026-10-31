// Basit servis çalışanı: uygulama kabuğunu önbelleğe alır; veriler her zaman canlı çekilir.
const C = "akt-v1";
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(["/static/app.js", "/static/style.css", "/static/icon.svg"]))));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith("/static/")) e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
