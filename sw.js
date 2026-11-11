// Het weer: service worker: app offline beschikbaar, laatste weerbericht bewaard.
const VERSIE = "hetweer-v5";
const APP = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSIE).then(c => c.addAll(APP)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSIE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // GitHub API nooit cachen.
  if (url.hostname === "api.github.com") return;

  // Weer en eigen bestanden: eerst netwerk, bij geen verbinding de laatste versie.
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        if (resp.ok) {
          const kopie = resp.clone();
          caches.open(VERSIE).then(c => c.put(e.request, kopie));
        }
        return resp;
      })
      .catch(() => caches.match(e.request).then(r => r || caches.match("index.html")))
  );
});
