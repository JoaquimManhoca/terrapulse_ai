/* TerraPulse AI service worker — offline shell for low-connectivity areas. */
const CACHE = "terrapulse-v9";
const PRECACHE = [
  "/",
  "/porque",
  "/historico",
  "/sobre",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon.svg",
  "/static/icons/icon-192.svg",
  "/static/icons/icon-512.svg"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(CACHE)
      .then(function (cache) {
        return Promise.all(
          PRECACHE.map(function (url) {
            return cache.add(url).catch(function () {
              /* one missing asset must not block the install */
            });
          })
        );
      })
      .then(function () {
        return self.skipWaiting();
      })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) {
              return key !== CACHE;
            })
            .map(function (key) {
              return caches.delete(key);
            })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

function putIfOk(request, response) {
  if (!response || !response.ok) return;
  const copy = response.clone();
  caches.open(CACHE).then(function (cache) {
    cache.put(request, copy);
  });
}

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  /* API: network first, last known answer when offline. */
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then(function (response) {
          putIfOk(request, response);
          return response;
        })
        .catch(function () {
          return caches.match(request).then(function (cached) {
            return (
              cached ||
              new Response(
                JSON.stringify({
                  error: {
                    code: "offline",
                    message: "Sem ligação. A mostrar a última decisão guardada."
                  }
                }),
                {
                  status: 503,
                  headers: { "Content-Type": "application/json; charset=utf-8" }
                }
              )
            );
          });
        })
    );
    return;
  }

  /* Static assets: serve cached immediately and refresh in the background. */
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        const network = fetch(request)
          .then(function (response) {
            putIfOk(request, response);
            return response;
          })
          .catch(function () {
            return cached;
          });
        return cached || network;
      })
    );
    return;
  }

  /* Pages: network first, cached page or app shell when offline. */
  event.respondWith(
    fetch(request)
      .then(function (response) {
        putIfOk(request, response);
        return response;
      })
      .catch(function () {
        return caches.match(request).then(function (cached) {
          return cached || caches.match("/");
        });
      })
  );
});
