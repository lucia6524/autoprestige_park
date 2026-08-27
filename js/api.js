/**
 * AutoPrestige API Client
 */
const API_BASE = (() => {
  const configuredBase = localStorage.getItem('api_base');
  if (configuredBase) return configuredBase.replace(/\/$/, '') + '/api';

  const isLocal = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  return isLocal ? 'http://127.0.0.1:8000/api' : 'https://autoprestige-api.onrender.com/api';
})();

const API = {
  getToken() {
    return localStorage.getItem('ap_token');
  },
  setAuth(token, user) {
    localStorage.setItem('ap_token', token);
    localStorage.setItem('ap_user', JSON.stringify(user));
  },
  clearAuth() {
    localStorage.removeItem('ap_token');
    localStorage.removeItem('ap_user');
  },
  getUser() {
    try {
      return JSON.parse(localStorage.getItem('ap_user') || 'null');
    } catch {
      return null;
    }
  },
  isLoggedIn() {
    return !!this.getToken();
  },

  async request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const token = this.getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch (netErr) {
      throw new Error(
        'Impossible de contacter le serveur (API). Démarrez le backend : cd backend && python run.py (port 8000).'
      );
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail || data.message || `Erreur ${res.status}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  },

  // Auth — multi-step registration
  registerStep1(first_name, last_name) {
    return this.request('/auth/register/step1', {
      method: 'POST',
      body: JSON.stringify({ first_name, last_name }),
    });
  },
  registerStep2(session_key, email, phone) {
    return this.request(`/auth/register/step2?session_key=${encodeURIComponent(session_key)}`, {
      method: 'POST',
      body: JSON.stringify({ email, phone }),
    });
  },
  registerStep3(session_key, monthly_salary) {
    return this.request(`/auth/register/step3?session_key=${encodeURIComponent(session_key)}`, {
      method: 'POST',
      body: JSON.stringify({ monthly_salary }),
    });
  },
  registerVerify(email, code) {
    return this.request('/auth/register/verify', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    });
  },
  registerSetPassword(email, password) {
    return this.request('/auth/register/set-password', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },
  loginRequestCode(email) {
    return this.request(`/auth/login/request-code?email=${encodeURIComponent(email)}`, {
      method: 'POST',
    });
  },
  login(email, codeOrPassword, isPassword = false) {
    const body = isPassword
      ? { email, password: codeOrPassword }
      : { email, code: codeOrPassword };
    return this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  loginWithPassword(email, password) {
    return this.login(email, password, true);
  },
  me() {
    return this.request('/auth/me');
  },

  updateProfile(profile) {
    return this.request('/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(profile),
    });
  },

  getSiteSettings() {
    return this.request('/site-settings');
  },

  getVehicles() {
    return this.request('/vehicles?limit=200');
  },

  getVehicle(id) {
    return this.request(`/vehicles/${id}`);
  },

  saveDeliveryDetails(orderId, details) {
    return this.request(`/orders/${orderId}/delivery-details`, {
      method: 'PATCH',
      body: JSON.stringify(details),
    });
  },

  // Cart
  getCart() {
    return this.request('/cart');
  },
  addToCart(vehicle) {
    return this.request('/cart/add', {
      method: 'POST',
      body: JSON.stringify({
        vehicle_id: vehicle.id,
        brand: vehicle.brand,
        model: vehicle.model,
        year: vehicle.year,
        price: vehicle.price,
        monthly: vehicle.monthly || 0,
        image: vehicle.image || '',
      }),
    });
  },
  removeFromCart(itemId) {
    return this.request(`/cart/${itemId}`, { method: 'DELETE' });
  },

  // Orders
  getOrders() {
    return this.request('/orders');
  },
  getOrder(id) {
    return this.request(`/orders/${id}`);
  },
  checkout(cartItemId, paymentType, months) {
    return this.request('/orders/checkout', {
      method: 'POST',
      body: JSON.stringify({
        cart_item_id: cartItemId,
        payment_type: paymentType,
        months: months || null,
      }),
    });
  },
  payInstallment(orderId, installmentId) {
    return this.request(`/orders/${orderId}/pay-installment`, {
      method: 'POST',
      body: JSON.stringify({ installment_id: installmentId }),
    });
  },
};

window.API = API;


// Update header auth links based on login state
API.updateHeaderAuth = function() {
  const el = document.getElementById('header-auth');
  if (!el) return;
  if (this.isLoggedIn()) {
    const u = this.getUser() || {};
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || 'Mon compte';
    el.innerHTML = `
      <div class="header-auth-user">
        <a href="compte.html">${name}</a>
        <a href="#" id="header-logout" style="color:#dc2626;font-weight:500;">Déconnexion</a>
      </div>`;
    const btn = document.getElementById('header-logout');
    if (btn) btn.addEventListener('click', (e) => {
      e.preventDefault();
      API.clearAuth();
      window.location.href = 'index.html';
    });
  }
};

document.addEventListener('DOMContentLoaded', () => {
  if (window.API) API.updateHeaderAuth();
});
