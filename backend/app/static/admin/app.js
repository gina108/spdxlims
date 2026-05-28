const api = '/api';
let token = localStorage.getItem('lims_token') || '';

const byId = (id) => document.getElementById(id);
const authHeaders = () => ({ Authorization: `Bearer ${token}` });

function showApp(loggedIn) {
  byId('login-card').classList.toggle('hidden', loggedIn);
  byId('app').classList.toggle('hidden', !loggedIn);
}

async function fetchJson(path, opts = {}) {
  const res = await fetch(`${api}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function refreshSnapshot() {
  if (!token) return;
  const me = await fetchJson('/auth/me', { headers: authHeaders() });
  byId('whoami').textContent = `${me.full_name} (${me.role})`;
  byId('providers-out').textContent = JSON.stringify(await fetchJson('/providers', { headers: authHeaders() }), null, 2);
  byId('items-out').textContent = JSON.stringify(await fetchJson('/inventory/items', { headers: authHeaders() }), null, 2);
}

byId('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = new URLSearchParams();
  body.append('username', byId('email').value.trim());
  body.append('password', byId('password').value);
  try {
    const res = await fetch(`${api}/auth/login`, { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');
    token = data.access_token;
    localStorage.setItem('lims_token', token);
    byId('login-msg').textContent = 'Login successful';
    showApp(true);
    await refreshSnapshot();
  } catch (err) {
    byId('login-msg').textContent = err.message;
  }
});

byId('provider-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    provider_type: byId('provider_type').value,
    legal_name: byId('legal_name').value,
    email: byId('provider_email').value || null,
  };
  await fetchJson('/providers', { method: 'POST', headers: authHeaders(), body: JSON.stringify(payload) });
  await refreshSnapshot();
});

byId('item-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    sku: byId('sku').value,
    name: byId('item_name').value,
    category: byId('category').value,
    unit: byId('unit').value,
  };
  await fetchJson('/inventory/items', { method: 'POST', headers: authHeaders(), body: JSON.stringify(payload) });
  await refreshSnapshot();
});

byId('month-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    period_start: byId('period_start').value,
    period_end: byId('period_end').value,
  };
  const out = await fetchJson('/month-close/open', { method: 'POST', headers: authHeaders(), body: JSON.stringify(payload) });
  byId('month-out').textContent = JSON.stringify(out, null, 2);
});

byId('logout').addEventListener('click', () => {
  localStorage.removeItem('lims_token');
  token = '';
  showApp(false);
  byId('whoami').textContent = '';
});

(async function init() {
  if (!token) {
    showApp(false);
    return;
  }
  try {
    showApp(true);
    await refreshSnapshot();
  } catch {
    localStorage.removeItem('lims_token');
    token = '';
    showApp(false);
  }
})();
