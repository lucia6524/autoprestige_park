/**
 * Autohaus API Client
 */
const API_BASE = (() => {
  const configuredBase = localStorage.getItem('api_base');
  if (configuredBase) return configuredBase.replace(/\/$/, '') + '/api';

  const isLocal = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  return isLocal ? 'http://127.0.0.1:8000/api' : 'https://autoprestige-api.onrender.com/api';
})();

// Escape HTML to prevent XSS attacks
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

const API = {
  friendlyError(error, fallback = 'Une erreur est survenue. Veuillez réessayer.') {
    const message = error?.message || '';
    if (!message || /Failed to fetch|NetworkError|Impossible de contacter/i.test(message)) {
      return 'Le service est momentanément indisponible. Veuillez réessayer dans quelques instants.';
    }
    if (/503|service email|SMTP|Resend/i.test(message)) {
      return 'L’envoi est momentanément indisponible. Veuillez réessayer dans quelques instants.';
    }
    if (/401|Authentification|Token invalide|expiré/i.test(message)) {
      return 'Votre session a expiré. Veuillez vous reconnecter.';
    }
    if (/403|Accès réservé/i.test(message)) {
      return 'Vous n’êtes pas autorisé à effectuer cette action.';
    }
    return message || fallback;
  },

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
        'Le service est momentanément indisponible. Veuillez réessayer dans quelques instants.'
      );
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail || data.message || '';
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

  sendContactMessage(contactMessage) {
    return this.request('/contact/message', {
      method: 'POST',
      body: JSON.stringify(contactMessage),
    });
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

  // Reviews (témoignages clients)
  submitReview(review) {
    return this.request('/reviews', {
      method: 'POST',
      body: JSON.stringify(review),
    });
  },
  getReviews() {
    return this.request('/reviews');
  },
  getReviewStats() {
    return this.request('/reviews/stats');
  },

  // Sell requests (demande d'estimation avec photos)
  submitSellRequest(data) {
    return this.request('/sell-requests', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

window.API = API;

// ===== Optimisation des images du catalogue =====
// Trois niveaux, du plus rapide au plus simple :
//  1. Table locale (js/vehicles-thumbs.js) : copies WebP générées par
//     backend/optimize_catalog_images.py → gain de poids immédiat.
//  2. Transformations Supabase (?width=&quality=) : activées automatiquement
//     si le projet passe sur un plan qui les supporte (auto-détecté).
//  3. URL d'origine : repli transparent dans tous les autres cas.
function supaThumb(url, width, quality) {
  if (typeof url !== 'string' || !url) return url;
  const w = Math.min(Math.max(parseInt(width, 10) || 600, 1), 2500);
  const q = Math.min(Math.max(parseInt(quality, 10) || 65, 20), 100);
  // 1) Copie WebP locale si disponible (générée côté backend)
  const localMap = window.VEHICLE_THUMBS;
  if (localMap && localMap[url]) return localMap[url];
  // 2) Transformations Supabase — uniquement si le projet les supporte
  //    (fenêtre.__SUPA_TRANSFORMS_OK, posée par la sonde auto de main.js)
  if (window.__SUPA_TRANSFORMS_OK === true) {
    const marker = '/storage/v1/object/public/';
    const idx = url.indexOf(marker);
    if (idx !== -1) {
      return (
        url.slice(0, idx) +
        '/storage/v1/render/image/public/' +
        url.slice(idx + marker.length) +
        '?width=' + w + '&quality=' + q
      );
    }
  }
  // 3) URL d'origine
  return url;
}

// Réinjecte l'URL d'origine si la version transformée échoue à charger.
function attachImgFallback(img, originalUrl) {
  if (!img || typeof originalUrl !== 'string' || !originalUrl) return;
  img.addEventListener('error', function () {
    if (img.dataset.fallbackApplied) return;
    img.dataset.fallbackApplied = '1';
    img.src = originalUrl;
  }, { once: true });
}
window.supaThumb = supaThumb;
window.attachImgFallback = attachImgFallback;


// Update header auth links based on login state
API.updateHeaderAuth = function() {
  const el = document.getElementById('header-auth');
  if (!el) return;
  if (this.isLoggedIn()) {
    const u = this.getUser() || {};
    const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || 'Mon compte';
    const safeName = escapeHtml(name);
    el.innerHTML = `
      <div class="header-auth-user">
        <a href="compte.html">${safeName}</a>
        <a href="#" id="header-logout" style="color:#dc2626;font-weight:500;">${(window.I18N && I18N.t('nav.logout') !== 'nav.logout') ? I18N.t('nav.logout') : 'Déconnexion'}</a>
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
