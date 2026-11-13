/* Yellow service worker: cache-first for assets, network-first for HTML. */
const CACHE = "yellow-{{ cache_id }}";
const PRECACHE = ["./", "index.html", "style.css", "app.js", "manifest.json", "icon.svg", "icon-192.png", "icon-512.png"].concat({{ pages | tojson }});

self.addEventListener("install", (event) => {
  event.waitUntil(
    // "reload" skips the HTTP cache (Pages sends max-age=600), so a new worker never precaches stale files.
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" })))).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function store(request, response) {
  if (response && response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  const isHtml = request.mode === "navigate" || (request.headers.get("accept") || "").includes("text/html");
  if (isHtml) {
    event.respondWith(
      fetch(request)
        .then((response) => store(request, response))
        // Offline and not cached: redirect to the cached home page. Serving its body at this URL
        // would break its relative links (e.g. under tech/).
        .catch(() => caches.match(request).then((hit) => hit || (request.mode === "navigate"
          ? Response.redirect(new URL("./", self.registration.scope).href, 302)
          : Response.error())))
    );
  } else {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => store(request, response)))
    );
  }
});
