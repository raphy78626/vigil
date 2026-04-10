/*
 * Vigil Background Service Worker — Production Grade
 *
 * Responsibilities:
 *   - Aggregate events from content scripts
 *   - Store in IndexedDB with session tracking
 *   - Auto-rotate sessions after 30 min idle
 *   - Auto-flush to backend API when batch threshold met
 *   - Handle export / clear / toggle / allowlist
 */

const SESSION_IDLE_MS = 30 * 60 * 1000; // 30 min → new session

const state = {
  enabled: true,
  allowlistedDomains: [],
  eventsToday: 0,
  sessionId: crypto.randomUUID(),
  lastEventAt: Date.now(),
  startedAt: Date.now(),
  backendUrl: 'http://127.0.0.1:8000',
};


chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['enabled', 'allowlistedDomains', 'backendUrl'], (result) => {
    state.enabled = result.enabled ?? true;
    state.allowlistedDomains = result.allowlistedDomains ?? [];
    state.backendUrl = result.backendUrl ?? 'http://127.0.0.1:8000';
    chrome.storage.local.set({ backendUrl: state.backendUrl });
  });
  chrome.action.setBadgeBackgroundColor({ color: '#6366f1' });
});

/* ------------------------------------------------------------------ */
/* Message router                                                      */
/* ------------------------------------------------------------------ */

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case 'CAPTURED_EVENT':
      handleCapturedEvent(message.payload, sender.tab);
      sendResponse({ ok: true });
      break;

    case 'GET_STATE':
      sendResponse({ ...state });
      break;

    case 'TOGGLE_CAPTURE':
      state.enabled = message.enabled;
      chrome.storage.local.set({ enabled: state.enabled });
      chrome.action.setBadgeText({ text: state.enabled ? String(state.eventsToday) : 'OFF' });
      sendResponse({ enabled: state.enabled });
      break;

    case 'UPDATE_ALLOWLIST':
      state.allowlistedDomains = message.domains;
      chrome.storage.local.set({ allowlistedDomains: state.allowlistedDomains });
      sendResponse({ ok: true });
      break;

    case 'SET_BACKEND_URL':
      state.backendUrl = message.url || '';
      chrome.storage.local.set({ backendUrl: state.backendUrl });
      sendResponse({ ok: true });
      break;

    case 'EXPORT_EVENTS':
      exportAllEvents().then(data => sendResponse(data));
      return true;

    case 'CLEAR_EVENTS':
      clearAllEvents().then(() => {
        state.eventsToday = 0;
        chrome.action.setBadgeText({ text: '0' });
        sendResponse({ ok: true });
      });
      return true;

    case 'FLUSH_TO_BACKEND':
      flushToBackend().then(result => sendResponse(result));
      return true;
  }
});

/* ------------------------------------------------------------------ */
/* Event handling                                                      */
/* ------------------------------------------------------------------ */

const NOISE_DOMAIN_PATTERNS = [
  // Analytics / ad trackers
  'googlesyndication', 'doubleclick', 'google-analytics', 'googletagmanager',
  'googleadservices', 'imasdk.googleapis', 'adservice.google',
  'facebook.net', 'fbcdn.net', 'connect.facebook',
  'hotjar.com', 'fullstory.com', 'segment.com', 'mixpanel.com',
  'amplitude.com', 'sentry.io', 'newrelic.com', 'datadoghq.com',
  'intercom.io', 'intercomcdn.com', 'drift.com', 'crisp.chat',
  'onetrust.com', 'cookielaw.org', 'trustarc.com',
  // Vigil dashboard itself — prevent self-recording
  '127.0.0.1', 'localhost',
];

function _isDomainNoise(hostname) {
  return NOISE_DOMAIN_PATTERNS.some(p => hostname.includes(p));
}

function handleCapturedEvent(event, tab) {
  if (!state.enabled) return;

  try {
    const url = new URL(event.url || tab?.url || 'about:blank');

    if (['chrome:', 'chrome-extension:', 'about:', 'devtools:', 'data:'].includes(url.protocol)) {
      return;
    }

    if (_isDomainNoise(url.hostname)) return;

    const _effectiveAllowlist = state.allowlistedDomains.filter(
      d => d && d !== 'all' && d !== '*'
    );
    if (_effectiveAllowlist.length > 0) {
      if (!_effectiveAllowlist.some(d => url.hostname.includes(d))) {
        return;
      }
    }

    if (!event.isTopFrame && event.type === 'pageload') return;

    const now = Date.now();
    if (now - state.lastEventAt > SESSION_IDLE_MS) {
      state.sessionId = crypto.randomUUID();
      state.startedAt = now;
    }
    state.lastEventAt = now;

    const enrichedEvent = {
      ...event,
      id: crypto.randomUUID(),
      timestamp: now,
      isoTime: new Date(now).toISOString(),
      tabId: tab?.id ?? 0,
      sessionId: state.sessionId,
      pageTitle: tab?.title ?? event.pageTitle ?? '',
      domain: url.hostname,
    };

    storeEvent(enrichedEvent);
    state.eventsToday++;
    chrome.action.setBadgeText({ text: String(state.eventsToday) });
  } catch (e) {
    console.error('[Vigil] Error handling event:', e);
  }
}

/* ------------------------------------------------------------------ */
/* IndexedDB                                                           */
/* ------------------------------------------------------------------ */

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('vigil', 2);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains('events')) {
        const store = db.createObjectStore('events', { keyPath: 'id' });
        store.createIndex('timestamp', 'timestamp');
        store.createIndex('sessionId', 'sessionId');
        store.createIndex('type', 'type');
        store.createIndex('domain', 'domain');
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function storeEvent(event) {
  const db = await openDB();
  const tx = db.transaction('events', 'readwrite');
  tx.objectStore('events').add(event);
  db.close();
}

async function exportAllEvents() {
  const db = await openDB();
  return new Promise((resolve) => {
    const tx = db.transaction('events', 'readonly');
    const request = tx.objectStore('events').getAll();
    request.onsuccess = () => {
      db.close();
      resolve(request.result || []);
    };
    request.onerror = () => {
      db.close();
      resolve([]);
    };
  });
}

async function clearAllEvents() {
  const db = await openDB();
  const tx = db.transaction('events', 'readwrite');
  tx.objectStore('events').clear();
  db.close();
}

/* ------------------------------------------------------------------ */
/* Auto-flush to backend API                                           */
/* ------------------------------------------------------------------ */

async function flushToBackend() {
  if (!state.backendUrl) {
    return { ok: false, error: 'No backend URL configured' };
  }

  const events = await exportAllEvents();
  if (!events.length) return { ok: true, count: 0 };

  try {
    const resp = await fetch(`${state.backendUrl}/api/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events }),
    });

    if (resp.ok) {
      await clearAllEvents();
      state.eventsToday = 0;
      chrome.action.setBadgeText({ text: '0' });
      return { ok: true, count: events.length };
    }
    return { ok: false, error: `HTTP ${resp.status}` };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}
