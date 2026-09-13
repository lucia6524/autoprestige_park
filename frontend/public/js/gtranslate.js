/**
 * Filet de sécurité GTranslate (facultatif, zéro dépendance).
 *
 * La traduction du site est assurée par le widget GTranslate
 * (cdn.gtranslate.net, voir Layout.astro : window.gtranslateSettings +
 * dropdown.js). Ce script ne traduit RIEN : il couvre uniquement le cas où
 * le CDN GTranslate serait bloqué (réseau d'entreprise, extension, pays) —
 * le sélecteur <select class="gt_selector"> n'existe alors jamais alors que
 * le visiteur a demandé une langue étrangère. On lui propose de revenir au
 * français. Sans CDN bloqué, ce script est totalement inerte.
 */
(function () {
  'use strict';

  var STORAGE_KEY = '__GT_TRANSLATE_LANGS';
  var DEFAULT_LANG = 'fr';
  var CHECK_DELAY_MS = 6000; // le widget s'initialise après le DOM

  function targetLang() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var stored = JSON.parse(raw);
      return stored && typeof stored.tgtLang === 'string' ? stored.tgtLang : null;
    } catch (_) {
      return null;
    }
  }

  function backToFrench() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (_) { /* localStorage indisponible : tant pis */ }
    window.location.reload();
  }

  function showNotice(lang) {
    if (document.getElementById('gt-fallback-notice')) return;
    var bar = document.createElement('div');
    bar.id = 'gt-fallback-notice';
    bar.setAttribute('style',
      'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:2147483000;' +
      'max-width:92vw;display:flex;gap:12px;align-items:center;padding:10px 14px;' +
      'background:#111827;color:#f9fafb;border-radius:12px;font:500 0.9rem/1.4 system-ui,sans-serif;' +
      'box-shadow:0 8px 24px rgba(0,0,0,.35)');
    var text = document.createElement('span');
    text.textContent = 'Traduction ' + lang.toUpperCase() + ' indisponible (service bloqué).';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Revenir au français';
    btn.setAttribute('style',
      'border:none;border-radius:8px;padding:6px 12px;cursor:pointer;font-weight:700;' +
      'background:#f9fafb;color:#111827');
    btn.addEventListener('click', backToFrench);
    bar.appendChild(text);
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }

  window.setTimeout(function () {
    var lang = targetLang();
    if (!lang || lang === DEFAULT_LANG) return;
    // Le widget crée son <select class="gt_selector"> dans le wrapper configuré.
    if (!document.querySelector('.gt_selector') && !document.querySelector('.gt_switcher_wrapper')) {
      showNotice(lang);
    }
  }, CHECK_DELAY_MS);

  // --- Re-traduction du contenu chargé dynamiquement -----------------------
  // GTranslate ne traduit que le DOM présent au moment du clic ; le contenu
  // injecté ensuite par JS (cartes véhicules, avis…) reste en français.
  // Astuce : on relance doGTranslate('fr|<langue>') (même appel que le
  // sélecteur, sans rechargement) dès qu'un tel élément apparaît.
  // -------------------------------------------------------------------------
  var DYNAMIC_SELECTOR = '.vehicle-card, .testimonial-card';
  var RETRANSLATE_DELAY_MS = 500;

  function retranslate() {
    var tgt = targetLang();
    if (!tgt || tgt === DEFAULT_LANG) return;
    if (typeof window.doGTranslate !== 'function') return;
    try {
      window.doGTranslate(DEFAULT_LANG + '|' + tgt);
    } catch (e) { /* widget indisponible : on laisse le visiteur re-cliquer */ }
  }

  var retranslateTimer = null;
  function scheduleRetranslate() {
    if (retranslateTimer) clearTimeout(retranslateTimer);
    retranslateTimer = window.setTimeout(retranslate, RETRANSLATE_DELAY_MS);
  }

  function looksDynamic(node) {
    if (!node || node.nodeType !== 1) return false;
    return (
      (node.matches && node.matches(DYNAMIC_SELECTOR)) ||
      (node.querySelector && node.querySelector(DYNAMIC_SELECTOR) !== null)
    );
  }

  if (window.MutationObserver) {
    var observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i += 1) {
        for (var j = 0; j < mutations[i].addedNodes.length; j += 1) {
          if (looksDynamic(mutations[i].addedNodes[j])) { scheduleRetranslate(); return; }
        }
      }
    });
    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
    } else {
      window.addEventListener('DOMContentLoaded', function () {
        observer.observe(document.body, { childList: true, subtree: true });
      });
    }
  }
})();
