/**
 * Vigil Service Worker
 *
 * Manages capture state, aggregates events from content scripts,
 * and handles storage + export scheduling.
 */

interface CaptureState {
  enabled: boolean;
  allowlistedDomains: string[];
  eventsToday: number;
  sessionId: string;
}

const state: CaptureState = {
  enabled: true,
  allowlistedDomains: [],
  eventsToday: 0,
  sessionId: crypto.randomUUID(),
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['enabled', 'allowlistedDomains'], (result) => {
    state.enabled = result.enabled ?? true;
    state.allowlistedDomains = result.allowlistedDomains ?? [];
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CAPTURED_EVENT') {
    handleCapturedEvent(message.payload, sender.tab);
    sendResponse({ ok: true });
  } else if (message.type === 'GET_STATE') {
    sendResponse({ ...state });
  } else if (message.type === 'TOGGLE_CAPTURE') {
    state.enabled = message.enabled;
    chrome.storage.local.set({ enabled: state.enabled });
    sendResponse({ enabled: state.enabled });
  } else if (message.type === 'UPDATE_ALLOWLIST') {
    state.allowlistedDomains = message.domains;
    chrome.storage.local.set({ allowlistedDomains: state.allowlistedDomains });
    sendResponse({ ok: true });
  } else if (message.type === 'EXPORT_EVENTS') {
    exportDailyEvents().then((data) => sendResponse(data));
    return true;
  }
});

function handleCapturedEvent(event: any, tab: chrome.tabs.Tab | undefined) {
  if (!state.enabled) return;

  const url = new URL(event.url || tab?.url || '');
  if (state.allowlistedDomains.length > 0 && !state.allowlistedDomains.includes(url.hostname)) {
    return;
  }

  const enrichedEvent = {
    ...event,
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    tabId: tab?.id ?? 0,
    sessionId: state.sessionId,
    pageTitle: tab?.title ?? '',
  };

  storeEvent(enrichedEvent);
  state.eventsToday++;

  chrome.action.setBadgeText({ text: String(state.eventsToday) });
  chrome.action.setBadgeBackgroundColor({ color: '#6366f1' });
}

function storeEvent(event: any): void {
  const dbRequest = indexedDB.open('vigil', 1);

  dbRequest.onupgradeneeded = () => {
    const db = dbRequest.result;
    if (!db.objectStoreNames.contains('events')) {
      const store = db.createObjectStore('events', { keyPath: 'id' });
      store.createIndex('timestamp', 'timestamp');
      store.createIndex('sessionId', 'sessionId');
    }
  };

  dbRequest.onsuccess = () => {
    const db = dbRequest.result;
    const tx = db.transaction('events', 'readwrite');
    tx.objectStore('events').add(event);
  };
}

async function exportDailyEvents(): Promise<any[]> {
  return new Promise((resolve) => {
    const dbRequest = indexedDB.open('vigil', 1);
    dbRequest.onsuccess = () => {
      const db = dbRequest.result;
      const tx = db.transaction('events', 'readonly');
      const store = tx.objectStore('events');
      const getAll = store.getAll();
      getAll.onsuccess = () => resolve(getAll.result);
      getAll.onerror = () => resolve([]);
    };
    dbRequest.onerror = () => resolve([]);
  });
}
