const CACHE_NAME = 'octo-memory-v4';

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll([
      '/', '/index.html', '/manifest.json', '/sw.js', '/crypto.js'
    ]))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match('/index.html'));
    })
  );
});

self.addEventListener('sync', event => {
  if (event.tag === 'memory-sync') {
    event.waitUntil(syncMemory());
  }
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow('/'));
});

async function syncMemory() {
  try {
    const db = await new Promise((resolve, reject) => {
      const req = indexedDB.open('octopus-memory', 1);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });

    const tx = db.transaction('items', 'readonly');
    const store = tx.objectStore('items');
    const all = await new Promise((resolve, reject) => {
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });

    let synced = 0;
    for (const item of all) {
      try {
        const res = await fetch('/api/v1/memory/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(item)
        });
        if (res.ok) synced++;
      } catch (e) {
        console.log('Sync pending for', item.id);
      }
    }

    const clients = await self.clients.matchAll();
    clients.forEach(client => {
      client.postMessage({ type: 'SYNC_COMPLETE', synced });
    });
  } catch (e) {
    console.error('Sync failed:', e);
  }
}
