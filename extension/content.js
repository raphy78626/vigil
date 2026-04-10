/*
 * Vigil Content Script — Production Grade
 *
 * Captures DOM interactions with the richest possible selector metadata:
 *   - data-testid / data-test / data-cy / data-qa / data-automation-id
 *   - ARIA: role, aria-label, aria-labelledby, aria-describedby
 *   - Associated <label> text (via for= or wrapping label)
 *   - placeholder, name, title, href
 *   - Stable CSS (classes preferred over positional nth-child)
 *   - Walks up to nearest interactive ancestor for icon/SVG clicks
 *
 * Noise filtering:
 *   - Blocks ad/tracking/analytics iframe domains at the source
 *   - Skips tiny iframes (< 50px in either dimension)
 *   - Enriches events with frame context for backend filtering
 *
 * PII is redacted before any data leaves the page.
 */

(() => {
  /* ------------------------------------------------------------------ */
  /* Noise gate — bail immediately if this is an ad/tracking iframe      */
  /* ------------------------------------------------------------------ */

  const _NOISE_DOMAINS = [
    'googlesyndication.com', 'doubleclick.net', 'google-analytics.com',
    'googletagmanager.com', 'googleadservices.com', 'google.com/recaptcha',
    'facebook.net', 'fbcdn.net', 'connect.facebook.net',
    'analytics.', 'tracking.', 'pixel.', 'beacon.',
    'ads.', 'ad.', 'adservice.', 'adserver.',
    'hotjar.com', 'fullstory.com', 'segment.com', 'mixpanel.com',
    'amplitude.com', 'sentry.io', 'newrelic.com', 'datadoghq.com',
    'intercom.io', 'intercomcdn.com', 'drift.com', 'crisp.chat',
    'onetrust.com', 'cookielaw.org', 'trustarc.com',
    'cdn.jsdelivr.net', 'cdnjs.cloudflare.com',
    'youtube.com/embed', 'player.vimeo.com',
    'imasdk.googleapis.com', 'tpc.googlesyndication.com',
  ];

  const _hostname = window.location.hostname;
  const _href = window.location.href;
  const _isNoiseDomain = _NOISE_DOMAINS.some(d => _hostname.includes(d) || _href.includes(d));

  if (_isNoiseDomain) return;

  const _isTopFrame = (window.self === window.top);

  if (!_isTopFrame) {
    try {
      const w = window.innerWidth || 0;
      const h = window.innerHeight || 0;
      if (w < 50 || h < 50) return;
    } catch (_) {
      return;
    }
  }
  /* ------------------------------------------------------------------ */
  /* PII redaction                                                       */
  /* ------------------------------------------------------------------ */

  const PII_PATTERNS = [
    [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, '[EMAIL]'],
    [/\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g, '[PHONE]'],
    [/\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g, '[CARD]'],
    [/\b\d{3}[-]?\d{2}[-]?\d{4}\b/g, '[SSN]'],
  ];

  function redactPII(value) {
    if (!value) return value;
    let r = value;
    for (const [pattern, replacement] of PII_PATTERNS) {
      r = r.replace(pattern, replacement);
    }
    return r;
  }

  /* ------------------------------------------------------------------ */
  /* Test-ID attributes (checked in priority order)                      */
  /* ------------------------------------------------------------------ */

  const TEST_ATTRS = [
    'data-testid',
    'data-test',
    'data-test-id',
    'data-cy',
    'data-qa',
    'data-automation-id',
    'data-e2e',
  ];

  function getTestId(el) {
    for (const attr of TEST_ATTRS) {
      const val = el.getAttribute(attr);
      if (val) return { id: val, attr };
    }
    return null;
  }

  /* ------------------------------------------------------------------ */
  /* Walk up to nearest interactive/semantic ancestor                    */
  /* ------------------------------------------------------------------ */

  const INTERACTIVE_TAGS = new Set([
    'a', 'button', 'input', 'select', 'textarea', 'details', 'summary',
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button', 'link', 'menuitem', 'tab', 'option', 'checkbox', 'radio',
    'switch', 'combobox', 'textbox', 'searchbox', 'listbox',
  ]);

  function nearestInteractive(el) {
    let node = el;
    const maxDepth = 5;
    let depth = 0;
    while (node && node !== document.body && depth < maxDepth) {
      const tag = (node.tagName || '').toLowerCase();
      if (INTERACTIVE_TAGS.has(tag)) return node;
      const role = node.getAttribute('role');
      if (role && INTERACTIVE_ROLES.has(role)) return node;
      if (node.onclick || node.hasAttribute('tabindex')) return node;
      node = node.parentElement;
      depth++;
    }
    return el;
  }

  /* ------------------------------------------------------------------ */
  /* Stable CSS selector generation                                      */
  /* ------------------------------------------------------------------ */

  const GENERATED_CLASS_RE = /^[a-z]{1,4}[A-Z][A-Za-z0-9]{2,}$/;
  const HASH_CLASS_RE = /^[a-zA-Z_][a-zA-Z0-9_]*[-_][a-zA-Z0-9]{5,8}$/;
  const STYLED_COMP_RE = /^[a-z][a-zA-Z0-9]{4,7}$/;
  const REACT_DYNAMIC_ID_RE = /^:?[a-z0-9]+:$/;

  function isStableClass(cls) {
    if (!cls || cls.length < 2) return false;
    if (GENERATED_CLASS_RE.test(cls)) return false;
    if (HASH_CLASS_RE.test(cls)) return false;
    if (/^\d/.test(cls)) return false;
    if (STYLED_COMP_RE.test(cls) && /[A-Z]/.test(cls)) return false;
    return true;
  }

  function getUniqueSelector(el) {
    if (!el || !el.tagName) return '';

    const tid = getTestId(el);
    if (tid) return `[${tid.attr}="${tid.id}"]`;

    // Skip React dynamic IDs — they change on every page load
    if (el.id && !REACT_DYNAMIC_ID_RE.test(el.id)) {
      return `#${el.id}`;
    }

    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel && ariaLabel.length <= 80) return `[aria-label="${ariaLabel}"]`;

    const tag = el.tagName.toLowerCase();

    // data-* attributes (non-React, non-styled) as stable selectors
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-') && !attr.name.startsWith('data-react')
          && !attr.name.startsWith('data-styled') && !attr.name.startsWith('data-emotion')
          && attr.value && attr.value.length < 60 && attr.value.length > 0) {
        const sel = `[${attr.name}="${attr.value}"]`;
        try { if (document.querySelectorAll(sel).length === 1) return sel; } catch (_) {}
      }
    }

    const stableClasses = Array.from(el.classList || []).filter(isStableClass);
    if (stableClasses.length > 0) {
      const sel = `${tag}.${stableClasses[0]}`;
      try { if (document.querySelectorAll(sel).length === 1) return sel; } catch (_) {}
    }

    const name = el.getAttribute('name');
    if (name) {
      const sel = `${tag}[name="${name}"]`;
      try { if (document.querySelectorAll(sel).length === 1) return sel; } catch (_) {}
    }

    const parent = el.parentElement;
    if (!parent || parent === document.documentElement) return tag;

    const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
    if (siblings.length === 1) {
      return `${getUniqueSelector(parent)} > ${tag}`;
    }
    const index = siblings.indexOf(el) + 1;
    return `${getUniqueSelector(parent)} > ${tag}:nth-child(${index})`;
  }

  /* ------------------------------------------------------------------ */
  /* Associated <label> text                                             */
  /* ------------------------------------------------------------------ */

  function getLabelText(el) {
    if (el.id) {
      const label = document.querySelector(`label[for="${el.id}"]`);
      if (label) return label.textContent.trim().slice(0, 80);
    }
    const wrapping = el.closest('label');
    if (wrapping) {
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll('input, select, textarea').forEach(c => c.remove());
      const t = clone.textContent.trim();
      if (t) return t.slice(0, 80);
    }
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map(id => {
        const ref = document.getElementById(id);
        return ref ? ref.textContent.trim() : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ').slice(0, 80);
    }
    return null;
  }

  /* ------------------------------------------------------------------ */
  /* Meaningful data-* attributes                                        */
  /* ------------------------------------------------------------------ */

  const _SKIP_DATA = new Set([
    'data-reactid', 'data-reactroot', 'data-react-checksum',
    'data-styled', 'data-styled-version', 'data-emotion',
    'data-v-', 'data-server-rendered',
  ]);

  function getDataAttributes(el) {
    if (!el || !el.attributes) return null;
    const result = {};
    let count = 0;
    for (const attr of el.attributes) {
      if (!attr.name.startsWith('data-')) continue;
      if (_SKIP_DATA.has(attr.name)) continue;
      if (Array.from(_SKIP_DATA).some(s => attr.name.startsWith(s))) continue;
      if (attr.value && attr.value.length < 200) {
        result[attr.name] = attr.value;
        count++;
        if (count >= 10) break;
      }
    }
    return count > 0 ? result : null;
  }

  /* ------------------------------------------------------------------ */
  /* Walk up to find nearest href                                        */
  /* ------------------------------------------------------------------ */

  function getClosestHref(el) {
    let node = el;
    let depth = 0;
    while (node && node !== document.body && depth < 8) {
      if (node.tagName && node.tagName.toLowerCase() === 'a' && node.href) {
        return node.getAttribute('href');
      }
      node = node.parentElement;
      depth++;
    }
    return null;
  }

  /* ------------------------------------------------------------------ */
  /* Direct text (own text nodes only, not descendants)                   */
  /* ------------------------------------------------------------------ */

  function getDirectText(el) {
    if (!el) return null;
    let text = '';
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent;
      }
    }
    const trimmed = text.trim();
    return trimmed ? trimmed.slice(0, 120) : null;
  }

  /* ------------------------------------------------------------------ */
  /* Image context for thumbnail clicks                                  */
  /* ------------------------------------------------------------------ */

  function getImageContext(el) {
    let img = null;
    if (el.tagName && el.tagName.toLowerCase() === 'img') {
      img = el;
    } else {
      img = el.querySelector('img');
    }
    if (!img) return null;
    return {
      src: (img.getAttribute('src') || '').slice(0, 300),
      alt: img.getAttribute('alt') || null,
      width: img.naturalWidth || img.width || null,
      height: img.naturalHeight || img.height || null,
    };
  }

  /* ------------------------------------------------------------------ */
  /* Rich element info                                                   */
  /* ------------------------------------------------------------------ */

  function getElementInfo(el) {
    if (!el || !el.tagName) return null;
    const tag = el.tagName.toLowerCase();
    const rawText = (el.textContent || '').trim();
    const fullText = rawText.length > 200 ? rawText.slice(0, 200) : rawText;
    const directText = getDirectText(el);
    const inputType = el.type || null;

    const tid = getTestId(el);
    const role = el.getAttribute('role')
      || (tag === 'button' ? 'button' : null)
      || (tag === 'a' ? 'link' : null)
      || null;

    const href = getClosestHref(el);
    const dataAttrs = getDataAttributes(el);
    const imgCtx = getImageContext(el);

    return {
      tagName: tag,
      selectors: {
        css: getUniqueSelector(el),
        text: directText || fullText || null,
        fullText: fullText || null,
        ariaLabel: el.getAttribute('aria-label') || null,
        ariaDescribedBy: el.getAttribute('aria-describedby') || null,
        testId: tid ? tid.id : null,
        testIdAttr: tid ? tid.attr : null,
        id: el.id || null,
        className: el.className ? String(el.className).slice(0, 200) : null,
        name: el.getAttribute('name') || null,
        placeholder: el.getAttribute('placeholder') || null,
        role: role,
        label: getLabelText(el),
        title: el.getAttribute('title') || null,
        href: href,
        dataAttributes: dataAttrs,
      },
      inputType,
      value: null,
      image: imgCtx,
    };
  }

  /* ------------------------------------------------------------------ */
  /* Send to background                                                  */
  /* ------------------------------------------------------------------ */

  function send(type, detail) {
    try {
      chrome.runtime.sendMessage({
        type: 'CAPTURED_EVENT',
        payload: {
          type,
          url: window.location.href,
          pageTitle: document.title,
          timestamp: Date.now(),
          isTopFrame: _isTopFrame,
          viewport: { width: window.innerWidth, height: window.innerHeight },
          scrollPosition: { x: window.scrollX, y: window.scrollY },
          ...detail,
        },
      });
    } catch (_) {
      // Extension context invalidated
    }
  }

  /* ------------------------------------------------------------------ */
  /* CLICK — walk up to interactive ancestor                             */
  /* ------------------------------------------------------------------ */

  function _isVisible(el) {
    if (!el.getBoundingClientRect) return true;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
  }

  const _TRANSIENT_SELECTORS = [
    '#inline-preview-player', '.ytp-popup', '.ytp-tooltip',
    '.yt-bubble-hint-renderer', '[class*="preview-overlay"]',
    '[class*="hover-overlay"]',
  ];

  function _isInsideTransientOverlay(el) {
    for (const sel of _TRANSIENT_SELECTORS) {
      try { if (el.closest(sel)) return true; } catch (_) {}
    }
    return false;
  }

  function getAncestorContext(el) {
    const ancestors = [];
    let node = el.parentElement;
    let depth = 0;
    while (node && node !== document.body && depth < 6) {
      const tag = node.tagName.toLowerCase();
      const entry = { tagName: tag };
      const da = getDataAttributes(node);
      if (da) entry.dataAttributes = da;
      if (node.id) entry.id = node.id;
      const al = node.getAttribute('aria-label');
      if (al) entry.ariaLabel = al;
      if (tag === 'a' && node.href) entry.href = node.getAttribute('href');
      const r = node.getAttribute('role');
      if (r) entry.role = r;
      if (Object.keys(entry).length > 1) ancestors.push(entry);
      node = node.parentElement;
      depth++;
    }
    return ancestors.length > 0 ? ancestors : null;
  }

  document.addEventListener('click', (e) => {
    const rawTarget = e.target;
    if (!rawTarget || !rawTarget.tagName) return;
    if (!_isVisible(rawTarget)) return;

    if (_isInsideTransientOverlay(rawTarget)) return;

    const rawTag = rawTarget.tagName.toLowerCase();
    if (rawTag === 'video') return;

    const interactive = nearestInteractive(rawTarget);
    const info = getElementInfo(interactive);
    if (!info) return;
    info.coordinates = { x: e.clientX, y: e.clientY };

    if (rawTarget !== interactive) {
      const rawTag = rawTarget.tagName.toLowerCase();
      info.rawTarget = {
        tagName: rawTag,
        id: rawTarget.id || null,
        className: rawTarget.className ? String(rawTarget.className).slice(0, 120) : null,
        ariaLabel: rawTarget.getAttribute('aria-label') || null,
        src: (rawTag === 'img' || rawTag === 'svg') ? (rawTarget.getAttribute('src') || null) : null,
        alt: rawTag === 'img' ? (rawTarget.getAttribute('alt') || null) : null,
      };
    }

    info.ancestors = getAncestorContext(interactive);

    send('click', { element: info });
  }, true);

  /* ------------------------------------------------------------------ */
  /* INPUT — debounced (800ms to capture full typed value)               */
  /* ------------------------------------------------------------------ */

  let inputTimer = null;
  document.addEventListener('input', (e) => {
    const target = e.target;
    if (!target || target.value === undefined) return;

    clearTimeout(inputTimer);
    inputTimer = setTimeout(() => {
      const info = getElementInfo(target);
      if (!info) return;

      if (target.type === 'password') {
        info.value = '[REDACTED]';
      } else {
        info.value = redactPII(target.value.slice(0, 200));
      }
      send('input', { element: info });
    }, 800);
  }, true);

  /* ------------------------------------------------------------------ */
  /* CHANGE — select, checkbox, radio                                    */
  /* ------------------------------------------------------------------ */

  document.addEventListener('change', (e) => {
    const target = e.target;
    if (!target) return;

    const tag = (target.tagName || '').toLowerCase();
    if (tag !== 'select' && target.type !== 'checkbox' && target.type !== 'radio') return;

    const info = getElementInfo(target);
    if (!info) return;

    if (tag === 'select') {
      info.value = target.options[target.selectedIndex]?.text || target.value;
    } else if (target.type === 'checkbox' || target.type === 'radio') {
      info.value = String(target.checked);
    }

    send('change', { element: info });
  }, true);

  /* ------------------------------------------------------------------ */
  /* SUBMIT                                                              */
  /* ------------------------------------------------------------------ */

  document.addEventListener('submit', (e) => {
    const target = e.target;
    if (!target) return;
    send('submit', { element: getElementInfo(target) });
  }, true);

  /* ------------------------------------------------------------------ */
  /* NAVIGATION (SPA detection + History API interception)               */
  /* ------------------------------------------------------------------ */

  let lastUrl = window.location.href;

  function checkNavigation(trigger) {
    const current = window.location.href;
    if (current !== lastUrl) {
      const from = lastUrl;
      lastUrl = current;
      send('navigation', {
        navigation: { fromUrl: from, toUrl: current, trigger },
      });
    }
  }

  const _origPushState = history.pushState;
  const _origReplaceState = history.replaceState;

  history.pushState = function (...args) {
    _origPushState.apply(this, args);
    checkNavigation('pushState');
  };
  history.replaceState = function (...args) {
    _origReplaceState.apply(this, args);
    checkNavigation('replaceState');
  };

  let _navCheckTimer = null;
  const observer = new MutationObserver(() => {
    clearTimeout(_navCheckTimer);
    _navCheckTimer = setTimeout(() => checkNavigation('spa'), 300);
  });
  observer.observe(document.documentElement, { childList: true, subtree: false });

  window.addEventListener('popstate', () => checkNavigation('popstate'));
  window.addEventListener('hashchange', () => checkNavigation('hashchange'));

  /* ------------------------------------------------------------------ */
  /* SCROLL — debounced, captures position + delta                       */
  /* ------------------------------------------------------------------ */

  let scrollTimer = null;
  let lastScrollY = window.scrollY;
  let lastScrollX = window.scrollX;

  window.addEventListener('scroll', () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const deltaY = window.scrollY - lastScrollY;
      const deltaX = window.scrollX - lastScrollX;
      if (Math.abs(deltaY) < 20 && Math.abs(deltaX) < 20) return;
      send('scroll', {
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        deltaX,
        deltaY,
        target: 'window',
      });
      lastScrollY = window.scrollY;
      lastScrollX = window.scrollX;
    }, 400);
  }, { passive: true });

  /* ------------------------------------------------------------------ */
  /* DOUBLE-CLICK                                                        */
  /* ------------------------------------------------------------------ */

  document.addEventListener('dblclick', (e) => {
    let target = e.target;
    if (!target || !target.tagName) return;
    target = nearestInteractive(target);
    const info = getElementInfo(target);
    if (!info) return;
    info.coordinates = { x: e.clientX, y: e.clientY };
    send('dblclick', { element: info });
  }, true);

  /* ------------------------------------------------------------------ */
  /* CONTEXT MENU (right-click)                                          */
  /* ------------------------------------------------------------------ */

  document.addEventListener('contextmenu', (e) => {
    let target = e.target;
    if (!target || !target.tagName) return;
    target = nearestInteractive(target);
    const info = getElementInfo(target);
    if (!info) return;
    info.coordinates = { x: e.clientX, y: e.clientY };
    send('contextmenu', { element: info });
  }, true);

  /* ------------------------------------------------------------------ */
  /* DRAG & DROP                                                         */
  /* ------------------------------------------------------------------ */

  let dragSource = null;
  let dragSourceInfo = null;

  document.addEventListener('dragstart', (e) => {
    const target = e.target;
    if (!target || !target.tagName) return;
    dragSource = target;
    dragSourceInfo = getElementInfo(target);
    if (dragSourceInfo) {
      dragSourceInfo.coordinates = { x: e.clientX, y: e.clientY };
    }
  }, true);

  document.addEventListener('drop', (e) => {
    const target = e.target;
    if (!target || !target.tagName || !dragSourceInfo) return;
    const dropInfo = getElementInfo(target);
    if (!dropInfo) return;
    dropInfo.coordinates = { x: e.clientX, y: e.clientY };
    send('drag', {
      source: dragSourceInfo,
      target: dropInfo,
    });
    dragSource = null;
    dragSourceInfo = null;
  }, true);

  /* ------------------------------------------------------------------ */
  /* KEYBOARD — action keys, modifier combos, navigation keys            */
  /* ------------------------------------------------------------------ */

  const _ACTION_KEYS = new Set([
    'Enter', 'Escape', 'Tab', 'Backspace', 'Delete',
    ' ', 'Space',
    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'Home', 'End', 'PageUp', 'PageDown',
    'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
  ]);

  document.addEventListener('keydown', (e) => {
    if (['Control', 'Meta', 'Alt', 'Shift'].includes(e.key)) return;

    const hasModifier = e.ctrlKey || e.metaKey || e.altKey;
    const isActionKey = _ACTION_KEYS.has(e.key);

    if (!hasModifier && !isActionKey) return;

    const modifiers = [];
    if (e.ctrlKey) modifiers.push('Ctrl');
    if (e.metaKey) modifiers.push('Cmd');
    if (e.altKey) modifiers.push('Alt');
    if (e.shiftKey) modifiers.push('Shift');

    const combo = modifiers.length > 0
      ? modifiers.concat(e.key).join('+')
      : e.key;

    const target = e.target;
    const targetInfo = target && target.tagName ? {
      tagName: target.tagName.toLowerCase(),
      id: target.id || null,
      role: target.getAttribute('role') || null,
      type: target.type || null,
    } : null;

    send(hasModifier ? 'keycombo' : 'keypress', {
      key: e.key,
      code: e.code,
      combo: combo,
      ctrlKey: e.ctrlKey,
      metaKey: e.metaKey,
      altKey: e.altKey,
      shiftKey: e.shiftKey,
      targetElement: targetInfo,
    });
  }, true);

  /* ------------------------------------------------------------------ */
  /* FOCUS — track which element receives focus                          */
  /* ------------------------------------------------------------------ */

  const _FOCUSABLE = new Set(['input', 'textarea', 'select']);

  document.addEventListener('focusin', (e) => {
    const target = e.target;
    if (!target || !target.tagName) return;
    const tag = target.tagName.toLowerCase();
    if (!_FOCUSABLE.has(tag) && !target.isContentEditable) return;

    const info = getElementInfo(target);
    if (!info) return;
    send('focus', { element: info });
  }, true);

  /* ------------------------------------------------------------------ */
  /* COPY / PASTE — capture clipboard interactions                       */
  /* ------------------------------------------------------------------ */

  document.addEventListener('paste', (e) => {
    const target = e.target;
    if (!target || !target.tagName) return;
    const info = getElementInfo(target);
    if (!info) return;
    send('paste', { element: info });
  }, true);

  document.addEventListener('copy', (e) => {
    const sel = window.getSelection();
    const selectedText = sel ? sel.toString().trim().slice(0, 200) : null;
    send('copy', {
      selectedText: selectedText ? redactPII(selectedText) : null,
    });
  }, true);

  /* ------------------------------------------------------------------ */
  /* HOVER (mouseover) — throttled, interactive elements only           */
  /* ------------------------------------------------------------------ */

  const _HOVER_INTERACTIVE_TAGS = new Set(['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL', 'SUMMARY']);
  const _HOVER_INTERACTIVE_ROLES = new Set(['button', 'link', 'menuitem', 'tab', 'option', 'combobox', 'listitem', 'treeitem']);
  let _lastHoverId = null;
  let _lastHoverTime = 0;
  const _HOVER_DWELL_MS = 800; // only emit hover if cursor stays 800ms
  const _HOVER_COOLDOWN_MS = 2000; // don't re-emit same element within 2s

  document.addEventListener('mouseover', (e) => {
    let target = e.target;
    if (!target || !target.tagName) return;

    // Walk up to interactive ancestor (same logic as click)
    let el = target;
    for (let i = 0; i < 4 && el; i++) {
      if (_HOVER_INTERACTIVE_TAGS.has(el.tagName)) break;
      const role = el.getAttribute && el.getAttribute('role');
      if (role && _HOVER_INTERACTIVE_ROLES.has(role)) break;
      const parent = el.parentElement;
      if (!parent || parent === document.body) break;
      el = parent;
    }

    const tag = el.tagName;
    const isInteractive = _HOVER_INTERACTIVE_TAGS.has(tag) ||
      (['DIV', 'SPAN', 'LI', 'TD'].includes(tag) && (
        el.getAttribute('role') ||
        el.getAttribute('aria-label') ||
        el.getAttribute('data-testid') ||
        el.onclick
      ));
    if (!isInteractive) return;

    const now = Date.now();
    const info = getElementInfo(el);
    if (!info) return;

    const hoverId = info.selectors.css + '|' + (info.selectors.text || '');
    if (hoverId === _lastHoverId && (now - _lastHoverTime) < _HOVER_COOLDOWN_MS) return;

    // Use a short dwell timer — only capture if the user actually pauses
    clearTimeout(el._vigilHoverTimer);
    el._vigilHoverTimer = setTimeout(() => {
      _lastHoverId = hoverId;
      _lastHoverTime = Date.now();
      send('hover', { element: info });
    }, _HOVER_DWELL_MS);
  }, { passive: true });

  document.addEventListener('mouseout', (e) => {
    if (e.target && e.target._vigilHoverTimer) {
      clearTimeout(e.target._vigilHoverTimer);
    }
  }, { passive: true });

  /* ------------------------------------------------------------------ */
  /* PAGE LOAD                                                           */
  /* ------------------------------------------------------------------ */

  if (_isTopFrame) {
    const perfEntry = performance.getEntriesByType('navigation')[0];
  send('pageload', {
    navigation: {
      fromUrl: document.referrer || '',
      toUrl: window.location.href,
      trigger: 'pageload',
        navigationType: perfEntry ? perfEntry.type : 'unknown',
      },
      page: {
        readyState: document.readyState,
        docHeight: document.documentElement.scrollHeight,
        docWidth: document.documentElement.scrollWidth,
        lang: document.documentElement.lang || null,
      },
    });
  }

  /* ------------------------------------------------------------------ */
  /* PERFORMANCE TELEMETRY — Web Vitals (LCP, CLS, TTFB, INP)          */
  /* ------------------------------------------------------------------ */

  if (_isTopFrame) {
    let _lcpValue = 0;
    let _clsValue = 0;
    let _inpValue = 0;
    let _perfSent = false;

    try {
      const lcpObs = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        if (entries.length) _lcpValue = entries[entries.length - 1].startTime;
      });
      lcpObs.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (_) {}

    try {
      const clsObs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) _clsValue += entry.value;
        }
      });
      clsObs.observe({ type: 'layout-shift', buffered: true });
    } catch (_) {}

    try {
      const inpObs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const dur = entry.processingEnd - entry.startTime;
          if (dur > _inpValue) _inpValue = dur;
        }
      });
      inpObs.observe({ type: 'event', buffered: true, durationThreshold: 16 });
    } catch (_) {}

    const _sendPerfData = () => {
      if (_perfSent) return;
      _perfSent = true;

      const nav = performance.getEntriesByType('navigation')[0] || {};
      const resources = performance.getEntriesByType('resource') || [];
      const totalBytes = resources.reduce((sum, r) => sum + (r.transferSize || 0), 0);
      const slowest = [...resources]
        .sort((a, b) => b.duration - a.duration)
        .slice(0, 5)
        .map(r => ({
          name: r.name.slice(-80),
          duration_ms: Math.round(r.duration),
          size_kb: Math.round((r.transferSize || 0) / 1024),
        }));

      send('performance', {
        webVitals: {
          lcp_ms: Math.round(_lcpValue),
          cls: Math.round(_clsValue * 1000) / 1000,
          ttfb_ms: Math.round((nav.responseStart || 0) - (nav.requestStart || 0)),
          inp_ms: Math.round(_inpValue),
          dom_content_loaded_ms: Math.round((nav.domContentLoadedEventEnd || 0) - (nav.startTime || 0)),
          load_time_ms: Math.round((nav.loadEventEnd || 0) - (nav.startTime || 0)),
        },
        resources: {
          total_count: resources.length,
          total_transfer_kb: Math.round(totalBytes / 1024),
          slowest: slowest,
    },
  });
    };

    // Send performance data after page fully settles (load + 3s)
    if (document.readyState === 'complete') {
      setTimeout(_sendPerfData, 3000);
    } else {
      window.addEventListener('load', () => setTimeout(_sendPerfData, 3000));
    }
  }

  console.log('[Vigil] Content script active on', window.location.hostname);
})();
