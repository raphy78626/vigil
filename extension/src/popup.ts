function updateUI(state: any) {
  const dot = document.getElementById('status-dot')!;
  const text = document.getElementById('status-text')!;
  const count = document.getElementById('events-count')!;
  const sessionEl = document.getElementById('session-id')!;

  dot.className = `status-dot ${state.enabled ? 'on' : 'off'}`;
  text.textContent = state.enabled ? 'Capturing' : 'Paused';
  count.textContent = String(state.eventsToday || 0);
  sessionEl.textContent = (state.sessionId || '').slice(0, 8);

  const domainInput = document.getElementById('domain-input') as HTMLInputElement;
  if (state.allowlistedDomains?.length) {
    domainInput.value = state.allowlistedDomains.join(', ');
  }
}

chrome.runtime.sendMessage({ type: 'GET_STATE' }, updateUI);

document.getElementById('toggle-btn')!.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
    chrome.runtime.sendMessage({ type: 'TOGGLE_CAPTURE', enabled: !state.enabled }, (newState) => {
      updateUI(newState);
    });
  });
});

document.getElementById('domain-input')!.addEventListener('change', (e) => {
  const input = e.target as HTMLInputElement;
  const domains = input.value
    .split(',')
    .map(d => d.trim())
    .filter(d => d.length > 0);
  chrome.runtime.sendMessage({ type: 'UPDATE_ALLOWLIST', domains });
});

document.getElementById('export-btn')!.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'EXPORT_EVENTS' }, (events) => {
    const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `testai-events-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
});
