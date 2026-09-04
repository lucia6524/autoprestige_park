// ===== PERFORMANCE UTILITIES =====
function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

function throttle(fn, limit) {
  let inThrottle = false;
  return function (...args) {
    if (!inThrottle) {
      fn.apply(this, args);
      inThrottle = true;
      setTimeout(() => { inThrottle = false; }, limit);
    }
  };
}

// ===== VEHICLE DATA =====
// Le catalogue est servi par l'API (GET /api/vehicles) avec repli local
// (js/vehicles-data.js) et cache localStorage pour un affichage instantané.

const VEHICLES_CACHE_KEY = "autoprestige_vehicles_v1";
const VEHICLES_CACHE_TTL = 30 * 60 * 1000; // 30 minutes

let vehicles = window.FALLBACK_VEHICLES || [];

function readVehiclesCache() {
  try {
    const raw = localStorage.getItem(VEHICLES_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.ts || !Array.isArray(parsed.data)) return null;
    if (Date.now() - parsed.ts > VEHICLES_CACHE_TTL) return null;
    return parsed.data;
  } catch {
    return null;
  }
}

function writeVehiclesCache(data) {
  try {
    localStorage.setItem(VEHICLES_CACHE_KEY, JSON.stringify({ ts: Date.now(), data }));
  } catch {
    // Quota dépassé : le cache est optionnel, on ignore.
  }
}

// Normalise un véhicule (API → format attendu par le frontend)
function normalizeVehicle(v) {
  let images = v.images;
  if (typeof images === "string") {
    try { images = JSON.parse(images); } catch (_) { images = []; }
  }
  return { ...v, images: Array.isArray(images) ? images : [] };
}

// Remise automatique de 2 000 € sur les véhicules d'occasion.
function applyUsedVehicleDiscount() {
  vehicles.forEach((vehicle) => {
    if (vehicle.type === "occasion" && !vehicle.discountApplied) {
      vehicle.price = Math.max(0, Number(vehicle.price) - 2000);
      vehicle.discountApplied = true;
    }
  });
}

const brandLogos = {
  "BMW": "https://logo.clearbit.com/bmw.com",
  "Mercedes-Benz": "https://logo.clearbit.com/mercedes-benz.com",
  "Audi": "https://logo.clearbit.com/audi.com",
  "Porsche": "https://logo.clearbit.com/porsche.com",
  "Volkswagen": "https://logo.clearbit.com/vw.com",
  "Tesla": "https://logo.clearbit.com/tesla.com",
  "Peugeot": "https://logo.clearbit.com/peugeot.com",
  "SEAT": "https://logo.clearbit.com/seat.com",
  "Honda": "https://logo.clearbit.com/honda.com",
  "Volvo": "https://logo.clearbit.com/volvo.com",
  "Citroen": "https://logo.clearbit.com/citroen.com",
  "Toyota": "https://logo.clearbit.com/toyota.com",
  "Renault": "https://logo.clearbit.com/renault.com",
  "Ford": "https://logo.clearbit.com/ford.com",
  "Bentley": "https://logo.clearbit.com/bentleymotors.com",
  "Hyundai": "https://logo.clearbit.com/hyundai.com",
  "Jaguar": "https://logo.clearbit.com/jaguar.com",
  "Kia": "https://logo.clearbit.com/kia.com",
  "Land Rover": "https://logo.clearbit.com/landrover.com",
  "Mini": "https://logo.clearbit.com/mini.com",
  "Nissan": "https://logo.clearbit.com/nissan.com",
  "Opel": "https://logo.clearbit.com/opel.com",
  "Skoda": "https://logo.clearbit.com/skoda-auto.com"
};

// ===== DOM ELEMENTS =====
const vehiclesGrid = document.getElementById("vehicles-grid");
const filterBtns = document.querySelectorAll(".filter-btn");
const mobileToggle = document.querySelector(".mobile-toggle");
const nav = document.querySelector(".nav");
const header = document.querySelector(".header");
const contactForm = document.getElementById("contact-form");

// Advanced filter elements
const searchInput = document.getElementById("search-input");
const filterBrand = document.getElementById("filter-brand");
const filterFuel = document.getElementById("filter-fuel");
const filterType = document.getElementById("filter-type");
const filterPromo = document.getElementById("filter-promo");
const sortBy = document.getElementById("sort-by");
const resultsCount = document.getElementById("results-count");
const resetFiltersBtn = document.getElementById("reset-filters");

// ===== POPULATE BRAND FILTER =====
function populateBrands() {
  if (!filterBrand) return;
  const brands = [...new Set(vehicles.map(v => v.brand))].sort();
  brands.forEach(brand => {
    const opt = document.createElement("option");
    opt.value = brand;
    opt.textContent = brand;
    filterBrand.appendChild(opt);
  });
}

// ===== RENDER VEHICLES =====
function renderVehicles(list = null) {
  if (!vehiclesGrid) return;

  const filtered = list !== null ? list : applyFilters();

  if (resultsCount) {
    const t = (k, f) => (window.I18N && I18N.t(k) !== k) ? I18N.t(k) : f;
    const word = filtered.length > 1 ? t("vehicles.results_plural", "véhicules") : t("vehicles.results", "véhicule");
    resultsCount.textContent = `${filtered.length} ${word}`;
  }

  if (filtered.length === 0) {
    const t = (k, f) => (window.I18N && I18N.t(k) !== k) ? I18N.t(k) : f;
    vehiclesGrid.innerHTML = `
      <div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--text-secondary);">
        <p style="font-size:1.2rem;margin-bottom:8px;">${t("vehicles.no_results", "Aucun véhicule trouvé")}</p>
        <p>${t("vehicles.no_results_hint", "Essayez de modifier vos filtres.")}</p>
      </div>`;
    return;
  }

  // Batch DOM update with requestAnimationFrame for smoother rendering
  requestAnimationFrame(() => {
    vehiclesGrid.innerHTML = filtered.map(v => `
      <article class="vehicle-card" data-id="${v.id}" onclick="window.location.href='vehicule.html?id=${v.id}'" style="cursor:pointer;">
        <div class="vehicle-image">
          <div class="skeleton-overlay"></div>
          <img src="${v.image}" alt="${v.brand} ${v.model}" loading="lazy" decoding="async"
            onload="this.classList.add('visible');this.previousElementSibling.classList.add('loaded');"
            onerror="this.classList.add('visible');this.previousElementSibling.classList.add('loaded');">
          <div class="vehicle-badges">
            ${v.featured ? `<span class="badge badge-featured">${(window.I18N && I18N.t("vehicles.badge_featured") !== "vehicles.badge_featured") ? I18N.t("vehicles.badge_featured") : "★ À la une"}</span>` : ''}
            ${v.promo ? `<span class="badge badge-promo">${(window.I18N && I18N.t("vehicles.badge_promo") !== "vehicles.badge_promo") ? I18N.t("vehicles.badge_promo") : "Promo"}</span>` : ''}
            <span class="badge badge-category">${v.body_category || v.category}</span>
          </div>
        </div>
        <div class="vehicle-body">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            ${brandLogos[v.brand] ? `<img src="${brandLogos[v.brand]}" alt="${v.brand}" style="height:22px;width:auto;object-fit:contain;filter:var(--logo-filter);opacity:0.9;" loading="lazy" decoding="async" onerror="this.style.display='none'">` : ''}
            <h3 class="vehicle-title" style="margin:0;">${v.brand} ${v.model}</h3>
          </div>
          <div class="vehicle-specs">
            ${v.year} · ${v.fuel} · ${v.transmission}
            ${v.mileage === 0 ? ' · 0 km' : ' · ' + v.mileage.toLocaleString('fr-FR') + ' km'}
          </div>
          <div class="vehicle-price">
            <div>
              <div class="price-main">${v.price.toLocaleString('fr-FR')} €</div>
              <div class="price-month">ou ${v.monthly} €/mois</div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;">
              <a href="vehicule.html?id=${v.id}" class="btn btn-outline-sm" onclick="event.stopPropagation();">Voir →</a>
              <button type="button" class="btn btn-primary-sm" onclick="event.stopPropagation(); addVehicleFromCatalog(${v.id}, this);">Panier</button>
            </div>
          </div>
        </div>
      </article>
    `).join("");
  });
}

async function addVehicleFromCatalog(vehicleId, button) {
  if (!window.API || !API.isLoggedIn()) {
    if (confirm("Vous devez être connecté pour ajouter ce véhicule au panier.\n\nAller à la page de connexion ?")) {
      window.location.href = "connexion.html";
    }
    return;
  }

  const vehicle = vehicles.find((item) => item.id === vehicleId);
  if (!vehicle) return;

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Ajout…";
  try {
    await API.addToCart(vehicle);
    button.textContent = "✓ Ajouté";
    window.location.href = "compte.html";
  } catch (error) {
    button.disabled = false;
    button.textContent = originalText;
    alert(API.friendlyError(error));
  }
}

// ===== APPLY ALL FILTERS =====
function applyFilters() {
  let filtered = [...vehicles];

  // Search
  if (searchInput && searchInput.value.trim()) {
    const q = searchInput.value.trim().toLowerCase();
    filtered = filtered.filter(v =>
      v.brand.toLowerCase().includes(q) ||
      v.model.toLowerCase().includes(q) ||
      `${v.brand} ${v.model}`.toLowerCase().includes(q)
    );
  }

  // Brand
  if (filterBrand && filterBrand.value !== "all") {
    filtered = filtered.filter(v => v.brand === filterBrand.value);
  }

  // Fuel
  if (filterFuel && filterFuel.value !== "all") {
    filtered = filtered.filter(v => v.fuel === filterFuel.value);
  }

  // Type (neuf / occasion)
  if (filterType && filterType.value !== "all") {
    filtered = filtered.filter(v => v.type === filterType.value);
  }

  // Promo only
  if (filterPromo && filterPromo.checked) {
    filtered = filtered.filter(v => v.promo);
  }

  // Sorting
  if (sortBy && sortBy.value !== "default") {
    switch (sortBy.value) {
      case "brand-asc":
        filtered.sort((a, b) => a.brand.localeCompare(b.brand, "fr"));
        break;
      case "brand-desc":
        filtered.sort((a, b) => b.brand.localeCompare(a.brand, "fr"));
        break;
      case "price-asc":
        filtered.sort((a, b) => a.price - b.price);
        break;
      case "price-desc":
        filtered.sort((a, b) => b.price - a.price);
        break;
      case "year-desc":
        filtered.sort((a, b) => b.year - a.year);
        break;
      case "year-asc":
        filtered.sort((a, b) => a.year - b.year);
        break;
    }
  }

  return filtered;
}

// ===== BIND FILTER EVENTS =====
function bindFilterEvents() {
  if (searchInput) searchInput.addEventListener("input", debounce(() => renderVehicles(), 250));
  if (filterBrand) filterBrand.addEventListener("change", () => renderVehicles());
  if (filterFuel) filterFuel.addEventListener("change", () => renderVehicles());
  if (filterType) filterType.addEventListener("change", () => renderVehicles());
  if (filterPromo) filterPromo.addEventListener("change", () => renderVehicles());
  if (sortBy) sortBy.addEventListener("change", () => renderVehicles());

  if (resetFiltersBtn) {
    resetFiltersBtn.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      if (filterBrand) filterBrand.value = "all";
      if (filterFuel) filterFuel.value = "all";
      if (filterType) filterType.value = "all";
      if (sortBy) sortBy.value = "default";
      if (filterPromo) filterPromo.checked = false;
      renderVehicles();
    });
  }

  // Legacy simple filter buttons (homepage)
  if (filterBtns.length) {
    filterBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        filterBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const f = btn.dataset.filter;
        let list = vehicles;
        if (f === "neuf") list = vehicles.filter(v => v.type === "neuf");
        else if (f === "occasion") list = vehicles.filter(v => v.type === "occasion");
        else if (f === "promo") list = vehicles.filter(v => v.promo);
        renderVehicles(list);
      });
    });
  }
}

// ===== MOBILE MENU =====
if (mobileToggle && nav) {
  mobileToggle.addEventListener("click", () => {
    nav.classList.toggle("open");
    mobileToggle.textContent = nav.classList.contains("open") ? "✕" : "☰";
  });
}

// Close menu on link click
document.querySelectorAll(".nav > a, .dropdown a").forEach(link => {
  link.addEventListener("click", () => {
    if (nav) nav.classList.remove("open");
    if (mobileToggle) mobileToggle.textContent = "☰";
  });
});

// Mobile: toggle Plus dropdown
document.querySelectorAll(".nav-item > a").forEach(trigger => {
  trigger.addEventListener("click", (e) => {
    if (window.innerWidth <= 768) {
      e.preventDefault();
      trigger.parentElement.classList.toggle("open");
    }
  });
});

// ===== STICKY HEADER =====
window.addEventListener("scroll", throttle(() => {
  if (window.scrollY > 50) {
    header.classList.add("scrolled");
  } else {
    header.classList.remove("scrolled");
  }
}, 100));

// ===== COUNTER ANIMATION =====
function animateCounters() {
  const counters = document.querySelectorAll(".stat-item strong");
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const target = parseInt(el.dataset.target);
        const suffix = el.dataset.suffix || "";
        let current = 0;
        const increment = target / 60;
        const timer = setInterval(() => {
          current += increment;
          if (current >= target) {
            el.textContent = target.toLocaleString("fr-FR") + suffix;
            clearInterval(timer);
          } else {
            el.textContent = Math.floor(current).toLocaleString("fr-FR") + suffix;
          }
        }, 25);
        observer.unobserve(el);
      }
    });
  }, { threshold: 0.5 });

  counters.forEach(c => observer.observe(c));
}

// ===== INIT =====
async function loadPublicVehicles() {
  const isCatalogPage = Boolean(vehiclesGrid);

  // 1) Cache localStorage : rendu instantané, sans attendre le réseau
  if (isCatalogPage) {
    const cached = readVehiclesCache();
    if (cached && cached.length) vehicles = cached.map(normalizeVehicle);
  }

  // 2) Rendu immédiat (fallback local ou cache)
  applyUsedVehicleDiscount();
  populateBrands();
  bindFilterEvents();
  renderVehicles();
  animateCounters();

  // 3) Rafraîchissement silencieux depuis l'API + mise en cache (pages catalogue uniquement)
  if (!isCatalogPage) return;
  try {
    if (window.API && typeof API.getVehicles === "function") {
      const managedVehicles = (await API.getVehicles()).map(normalizeVehicle);
      if (Array.isArray(managedVehicles) && managedVehicles.length) {
        vehicles = managedVehicles;
        writeVehiclesCache(managedVehicles);
        // Même remise que les données locales, pour des prix cohérents
        // (la page détail applique aussi cette remise aux données API)
        applyUsedVehicleDiscount();
        renderVehicles();
      }
    }
  } catch (error) {
    console.warn("Catalogue API indisponible, utilisation du catalogue local.", error);
  }
}

document.addEventListener("DOMContentLoaded", loadPublicVehicles);

// ===== FAQ CHAT WIDGET =====
const faqAnswers = {
  "garantie": "Tous nos véhicules d'occasion sont vendus avec une garantie minimum de 12 mois. Des extensions jusqu'à 36 mois sont disponibles.",
  "livraison": "Oui, nous livrons dans toute la France et dans la plupart des pays européens. Le transport est sécurisé et assuré.",
  "financement": "Oui. Nous proposons crédit classique, LOA et LLD avec plusieurs partenaires bancaires. Utilisez notre simulateur sur la page Financement.",
  "reprise": "Oui, estimation gratuite de votre véhicule actuel. Offre sous 24h, sans engagement.",
  "horaires": "Lundi – Vendredi : 09:00 – 19:00. Samedi : 10:00 – 17:00. Dimanche : fermé.",
  "contact": "Vous pouvez nous joindre au +33 1 42 86 82 00, par email contact@autoprestige.fr ou via WhatsApp.",
  "default": "Merci pour votre question ! Un conseiller peut vous répondre plus précisément. Écrivez-nous sur WhatsApp ou utilisez le formulaire de contact."
};

function matchFaq(text) {
  const t = text.toLowerCase();
  if (t.includes("garanti")) return faqAnswers.garantie;
  if (t.includes("livr") || t.includes("transport")) return faqAnswers.livraison;
  if (t.includes("financ") || t.includes("crédit") || t.includes("credit") || t.includes("loa")) return faqAnswers.financement;
  if (t.includes("reprise") || t.includes("reprendre") || t.includes("vendre")) return faqAnswers.reprise;
  if (t.includes("horaire") || t.includes("ouvert")) return faqAnswers.horaires;
  if (t.includes("contact") || t.includes("téléphone") || t.includes("telephone") || t.includes("email") || t.includes("whatsapp")) return faqAnswers.contact;
  if (t.includes("bonjour") || t.includes("salut") || t.includes("hello")) return "Bonjour ! 👋 Je suis l'assistant Auto-prestige. Posez-moi une question sur la garantie, la livraison, le financement ou la reprise.";
  return faqAnswers.default;
}

function initChatWidget() {
  if (document.querySelector(".chat-widget")) return;

  const widget = document.createElement("div");
  widget.className = "chat-widget";
  widget.innerHTML = `
    <div class="chat-panel">
      <div class="chat-header">
        <span>Assistant Auto-prestige</span>
        <button type="button" aria-label="Fermer" class="chat-close">✕</button>
      </div>
      <div class="chat-messages" id="chat-messages">
        <div class="chat-msg bot">Bonjour ! 👋 Posez une question ou choisissez une suggestion ci-dessous.</div>
      </div>
      <div class="chat-quick">
        <button type="button" data-q="Quelle garantie proposez-vous ?">Garantie</button>
        <button type="button" data-q="Livrez-vous partout en France ?">Livraison</button>
        <button type="button" data-q="Proposez-vous un financement ?">Financement</button>
        <button type="button" data-q="Puis-je faire reprendre mon véhicule ?">Reprise</button>
      </div>
      <div class="chat-input-row">
        <input type="text" id="chat-input" placeholder="Écrivez votre question...">
        <button type="button" id="chat-send">Envoyer</button>
      </div>
    </div>
    <button type="button" class="chat-toggle" aria-label="Ouvrir le chat">💬</button>
  `;
  document.body.appendChild(widget);

  const toggle = widget.querySelector(".chat-toggle");
  const closeBtn = widget.querySelector(".chat-close");
  const messages = widget.querySelector("#chat-messages");
  const input = widget.querySelector("#chat-input");
  const sendBtn = widget.querySelector("#chat-send");

  function addMsg(text, who) {
    const div = document.createElement("div");
    div.className = "chat-msg " + who;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function handleSend(text) {
    text = (text || "").trim();
    if (!text) return;
    addMsg(text, "user");
    input.value = "";
    setTimeout(() => addMsg(matchFaq(text), "bot"), 400);
  }

  toggle.addEventListener("click", () => widget.classList.toggle("open"));
  closeBtn.addEventListener("click", () => widget.classList.remove("open"));
  sendBtn.addEventListener("click", () => handleSend(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSend(input.value);
  });
  widget.querySelectorAll(".chat-quick button").forEach(btn => {
    btn.addEventListener("click", () => handleSend(btn.dataset.q));
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initChatWidget();
});

// ===== THEME TOGGLE (light / dark uniquement) =====
// La préférence est gérée surtout dans header.js.
// Ici on garde des helpers pour le reste du site.

function resolveThemePref(pref) {
  return (pref === "light") ? "light" : "dark";
}

function initTheme() {
  let pref = localStorage.getItem("theme");
  if (pref !== "light" && pref !== "dark") pref = "dark";
  const resolved = resolveThemePref(pref);
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.setAttribute("data-theme-pref", pref);
  localStorage.setItem("theme", pref);
  updateThemeButtons(pref, resolved);
}

function updateThemeButtons(pref, resolved) {
  pref = pref || localStorage.getItem("theme") || "dark";
  resolved = resolved || resolveThemePref(pref);
  document.querySelectorAll(".theme-toggle").forEach(btn => {
    if (resolved === "dark") {
      btn.textContent = "☀️";
      btn.title = "Mode sombre → cliquer pour clair";
    } else {
      btn.textContent = "🌙";
      btn.title = "Mode clair → cliquer pour sombre";
    }
  });
}

function toggleTheme() {
  // Alternance clair ↔ sombre uniquement
  const current = localStorage.getItem("theme") === "light" ? "light" : "dark";
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem("theme", next);
  const resolved = resolveThemePref(next);
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.setAttribute("data-theme-pref", next);
  updateThemeButtons(next, resolved);
}

function injectThemeToggle() {
  // Bouton fourni par header.js — ne pas doubler
  if (document.querySelector(".theme-toggle")) return;
  const actions = document.querySelector(".header-actions");
  if (!actions) return;
  const btn = document.createElement("button");
  btn.className = "theme-toggle";
  btn.type = "button";
  btn.addEventListener("click", toggleTheme);
  actions.insertBefore(btn, actions.firstChild);
  initTheme();
}

// Anti-flash : clair ou sombre uniquement (défaut sombre)
(function() {
  var pref = localStorage.getItem("theme");
  if (pref !== "light" && pref !== "dark") pref = "dark";
  document.documentElement.setAttribute("data-theme", pref);
})();

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  injectThemeToggle();
});

document.addEventListener("headerReady", () => {
  initTheme();
});

// ===== SCROLL REVEAL =====
function initScrollReveal() {
  const els = document.querySelectorAll(".section-header, .service-card, .testimonial-card, .stat-item, .process-step, .contact-item");
  if (!els.length || !("IntersectionObserver" in window)) return;
  els.forEach(el => el.classList.add("reveal"));
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach(el => io.observe(el));
}

document.addEventListener("DOMContentLoaded", initScrollReveal);

// ===== COOKIE BANNER =====
function initCookieBanner() {
  if (localStorage.getItem("cookiesAccepted")) return;
  const bar = document.createElement("div");
  bar.className = "cookie-banner show";
  const t = (key, fallback) => (window.I18N && I18N.t(key) !== key) ? I18N.t(key) : fallback;
  bar.innerHTML = `
    <div class="cookie-inner">
      <p>${t('cookies.text', 'Nous utilisons des cookies pour le fonctionnement du site (thème, préférences) et améliorer votre expérience.')}
        <a href="mentions-legales.html#cookies" style="color:var(--accent-light);">${t('cookies.learn_more', 'En savoir plus')}</a></p>
      <div class="cookie-actions">
        <button type="button" class="btn btn-outline" id="cookie-refuse">${t('cookies.refuse', 'Refuser')}</button>
        <button type="button" class="btn btn-primary" id="cookie-accept">${t('cookies.accept', 'Accepter')}</button>
      </div>
    </div>`;
  document.body.appendChild(bar);
  document.getElementById("cookie-accept").onclick = () => {
    localStorage.setItem("cookiesAccepted", "yes");
    bar.remove();
  };
  document.getElementById("cookie-refuse").onclick = () => {
    localStorage.setItem("cookiesAccepted", "no");
    bar.remove();
  };
}

document.addEventListener("DOMContentLoaded", initCookieBanner);

// ===== REVIEW FORM =====
function initReviewForm() {
  const form = document.getElementById("review-form");
  if (!form) return;
  let rating = 5;
  const stars = form.querySelectorAll(".star-rating span");
  stars.forEach((star, i) => {
    star.addEventListener("click", () => {
      rating = i + 1;
      stars.forEach((s, j) => s.classList.toggle("active", j < rating));
    });
  });
  stars.forEach((s, j) => s.classList.toggle("active", j < rating));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    alert("Merci pour votre avis ! Il sera publié après modération.");
    form.reset();
    rating = 5;
    stars.forEach((s, j) => s.classList.toggle("active", j < rating));
  });
}

document.addEventListener("DOMContentLoaded", initReviewForm);

// Re-render vehicles when language changes
document.addEventListener("languageChanged", () => {
  if (typeof renderVehicles === "function") renderVehicles();
});

