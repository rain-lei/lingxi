"use strict";

// Browser identity survives page changes. A paired device and its token live
// only in this tab's session; no credential is placed in a URL or localStorage.
window.LingxiIdentity = (() => {
  const browserKey = "lingxi-browser-device-id";
  const sessionKey = "lingxi-paired-device";
  const valid = value => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value || "");
  let browserId, paired = null;
  let channel;
  try { channel = new BroadcastChannel('lingxi-updates'); } catch {}
  const updateKey = 'lingxi-data-update';
  const changed = message => {
    if (message?.deviceId === (paired?.id || browserId)) {
      window.dispatchEvent(new CustomEvent('lingxi:data-changed', { detail: { deviceId: message.deviceId } }));
    }
  };
  if (channel) channel.onmessage = event => changed(event.data);
  else window.addEventListener('storage', event => {
    if (event.key === updateKey && event.newValue) {
      try { changed(JSON.parse(event.newValue)); } catch {}
    }
  });
  function notify(deviceId) {
    if (!valid(deviceId)) return;
    // No chat content, personal data or credentials cross this channel.
    const message = { deviceId, nonce: Date.now() + Math.random() };
    if (channel) channel.postMessage(message);
    // Also notify tabs on browsers where BroadcastChannel is unavailable.
    try { localStorage.setItem(updateKey, JSON.stringify(message)); } catch {}
  }
  try { browserId = localStorage.getItem(browserKey); } catch {}
  if (!/^web-[A-Za-z0-9-]{8,60}$/.test(browserId || "")) {
    browserId = `web-${crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)}`;
    try { localStorage.setItem(browserKey, browserId); } catch {}
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(sessionKey));
    if (saved && valid(saved.id) && typeof saved.token === "string") paired = saved;
  } catch {}
  function select(id, token = "") {
    if (!valid(id)) throw new Error("设备编号无效");
    paired = id === browserId ? null : { id, token };
    try {
      if (paired) sessionStorage.setItem(sessionKey, JSON.stringify(paired));
      else sessionStorage.removeItem(sessionKey);
    } catch {}
  }
  async function request(url, options = {}) {
    const target = new URL(url, location.href);
    const headers = new Headers(options.headers);
    if (target.origin === location.origin && target.pathname.startsWith('/api/') && paired?.token && !headers.has('X-Device-Token')) {
      headers.set('X-Device-Token', paired.token);
    }
    const response = await fetch(url, { ...options, headers });
    const mutation = /^\/api\/(?:tasks\/update|feedback|memory\/delete|reset|companion\/(?:learning\/.+|settings|memory\/delete))$/;
    if (response.ok && target.origin === location.origin && options.method?.toUpperCase() === 'POST' && mutation.test(target.pathname)) {
      try {
        const deviceId = JSON.parse(options.body).device_id;
        // A successful header alone does not guarantee the response finished.
        response.clone().json().then(() => notify(deviceId)).catch(() => {});
      } catch {}
    }
    return response;
  }
  document.addEventListener('DOMContentLoaded', () => {
    const nav = document.querySelector('header nav, .rail-nav');
    if (!nav) return;
    const identity = document.createElement('a');
    identity.href = '/companion?pair=1#settings';
    identity.className = 'identity-label';
    const paint = () => {
      identity.textContent = paired ? `设备 · ${paired.id.slice(-8)}` : '浏览器体验';
      identity.title = paired ? `当前设备：${paired.id}，点击切换` : '当前为独立浏览器体验，点击绑定设备';
      identity.setAttribute('aria-label', identity.title);
    };
    paint();
    nav.append(identity);
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = (nav.classList.contains('rail-nav') ? 'rail-link' : 'ghost-button') + ' identity-reset';
    reset.textContent = '返回浏览器体验';
    reset.hidden = !paired;
    reset.onclick = () => { select(browserId); location.href = location.pathname; };
    nav.append(reset);
    window.addEventListener('lingxi:identity', () => { paint(); reset.hidden = !paired; });
  });
  return { get: () => paired?.id || browserId, token: () => paired?.token || '',
    browserId, select: (id, token) => { select(id, token); window.dispatchEvent(new Event('lingxi:identity')); }, fetch: request, notify };
})();
