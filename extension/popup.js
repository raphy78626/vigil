function updateUI(s) {
  document.getElementById('dot').className = `dot ${s.enabled ? 'on' : 'off'}`;
  document.getElementById('status-text').textContent = s.enabled ? 'Capturing' : 'Paused';
  document.getElementById('event-count').textContent = s.eventsToday || 0;
  document.getElementById('session-id').textContent = (s.sessionId || '').slice(0, 6);

  const mins = Math.floor((Date.now() - (s.startedAt || Date.now())) / 60000);
  document.getElementById('uptime').textContent = mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h${mins % 60}m`;

  if (s.allowlistedDomains?.length) {
    document.getElementById('domain-input').value = s.allowlistedDomains.join(', ');
  }
  if (s.backendUrl) {
    document.getElementById('backend-input').value = s.backendUrl;
  }
}

chrome.runtime.sendMessage({ type: 'GET_STATE' }, updateUI);

document.getElementById('toggle-btn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (s) => {
    chrome.runtime.sendMessage({ type: 'TOGGLE_CAPTURE', enabled: !s.enabled }, (ns) => {
      updateUI({ ...s, enabled: ns.enabled });
    });
  });
});

document.getElementById('domain-input').addEventListener('change', (e) => {
  const domains = e.target.value.split(',').map(d => d.trim()).filter(Boolean);
  chrome.runtime.sendMessage({ type: 'UPDATE_ALLOWLIST', domains });
});

document.getElementById('backend-input').addEventListener('change', (e) => {
  chrome.runtime.sendMessage({ type: 'SET_BACKEND_URL', url: e.target.value.trim() });
});

document.getElementById('flush-btn').addEventListener('click', () => {
  const btn = document.getElementById('flush-btn');
  const msg = document.getElementById('flush-msg');
  btn.disabled = true;
  btn.textContent = 'Flushing...';
  msg.textContent = '';
  msg.className = 'flush-msg';

  chrome.runtime.sendMessage({ type: 'FLUSH_TO_BACKEND' }, (result) => {
    btn.disabled = false;
    btn.textContent = 'Flush to Backend';
    if (result?.ok) {
      msg.textContent = `Sent ${result.count} events to backend`;
      msg.className = 'flush-msg ok';
      chrome.runtime.sendMessage({ type: 'GET_STATE' }, updateUI);
    } else {
      msg.textContent = result?.error || 'Flush failed';
      msg.className = 'flush-msg err';
    }
  });
});

document.getElementById('export-btn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'EXPORT_EVENTS' }, (events) => {
    if (!events || !events.length) {
      alert('No events captured yet. Browse a website first!');
      return;
    }
    const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `testai-events-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
});

document.getElementById('clear-btn').addEventListener('click', () => {
  if (confirm('Clear all captured events?')) {
    chrome.runtime.sendMessage({ type: 'CLEAR_EVENTS' }, () => {
      document.getElementById('event-count').textContent = '0';
    });
  }
});
