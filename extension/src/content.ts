/**
 * Vigil Content Script
 *
 * Injected into every page. Observes DOM interactions and
 * sends structured events to the background service worker.
 */

const PII_PATTERNS: [RegExp, string][] = [
  [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, '[EMAIL]'],
  [/\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g, '[PHONE]'],
  [/\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g, '[CARD]'],
  [/\b\d{3}[-]?\d{2}[-]?\d{4}\b/g, '[SSN]'],
];

function redactPII(value: string): string {
  let redacted = value;
  for (const [pattern, replacement] of PII_PATTERNS) {
    redacted = redacted.replace(pattern, replacement);
  }
  return redacted;
}

function getUniqueSelector(el: Element): string {
  if (el.id) return `#${el.id}`;

  const testId = el.getAttribute('data-testid');
  if (testId) return `[data-testid="${testId}"]`;

  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel) return `[aria-label="${ariaLabel}"]`;

  const tag = el.tagName.toLowerCase();
  const parent = el.parentElement;
  if (!parent) return tag;

  const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
  if (siblings.length === 1) return `${getUniqueSelector(parent)} > ${tag}`;

  const index = siblings.indexOf(el) + 1;
  return `${getUniqueSelector(parent)} > ${tag}:nth-child(${index})`;
}

function getElementInfo(el: Element) {
  const tag = el.tagName.toLowerCase();
  return {
    tagName: tag,
    selectors: {
      css: getUniqueSelector(el),
      xpath: '',
      text: el.textContent?.trim().slice(0, 100) || null,
      ariaLabel: el.getAttribute('aria-label'),
      testId: el.getAttribute('data-testid'),
    },
    inputType: (el as HTMLInputElement).type || null,
    value: null as string | null,
    coordinates: null as { x: number; y: number } | null,
  };
}

function sendEvent(type: string, detail: any) {
  chrome.runtime.sendMessage({
    type: 'CAPTURED_EVENT',
    payload: {
      type,
      url: window.location.href,
      ...detail,
    },
  });
}

document.addEventListener('click', (e) => {
  const target = e.target as Element;
  if (!target) return;

  const info = getElementInfo(target);
  info.coordinates = { x: e.clientX, y: e.clientY };

  sendEvent('click', { element: info });
}, true);

document.addEventListener('input', (e) => {
  const target = e.target as HTMLInputElement;
  if (!target || !target.value) return;

  const info = getElementInfo(target);

  if (target.type === 'password') {
    info.value = '[REDACTED]';
  } else {
    info.value = redactPII(target.value);
  }

  sendEvent('input', { element: info });
}, true);

document.addEventListener('submit', (e) => {
  const target = e.target as Element;
  if (!target) return;

  sendEvent('submit', { element: getElementInfo(target) });
}, true);

let lastUrl = window.location.href;
const navigationObserver = new MutationObserver(() => {
  if (window.location.href !== lastUrl) {
    const from = lastUrl;
    lastUrl = window.location.href;
    sendEvent('navigation', {
      navigation: {
        fromUrl: from,
        toUrl: lastUrl,
        trigger: 'mutation',
      },
    });
  }
});
navigationObserver.observe(document.documentElement, { childList: true, subtree: true });

window.addEventListener('popstate', () => {
  const from = lastUrl;
  lastUrl = window.location.href;
  sendEvent('navigation', {
    navigation: { fromUrl: from, toUrl: lastUrl, trigger: 'popstate' },
  });
});

sendEvent('pageload', {
  navigation: {
    fromUrl: document.referrer,
    toUrl: window.location.href,
    trigger: 'pageload',
  },
});
