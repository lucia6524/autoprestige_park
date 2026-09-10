/**
 * Autohaus Loader — overlay plein écran avec le logo qui tourne.
 *
 * Affiché :
 *  - pendant le chargement de chaque page (clic sur un lien interne, puis
 *    l'overlay injecté en <head> reste visible sur la page suivante jusqu'à
 *    l'événement load) ;
 *  - à la demande, pendant les actions asynchrones (connexion, inscription…)
 *    via window.Loader.show() / window.Loader.hide().
 *
 * L'overlay + ses styles sont injectés par un script inline en <head> (pour
 * apparaître dès la première peinture). Ce fichier s'y branche uniquement.
 */
(function () {
  'use strict';
  var OVERLAY_ID = 'ap-loader-overlay';

  function getOverlay() {
    var o = document.getElementById(OVERLAY_ID);
    if (o) return o;
    // Repli : si le script inline de <head> n'a pas tourné (ex. page custom).
    o = document.createElement('div');
    o.id = OVERLAY_ID;
    o.innerHTML =
      '<img class="ap-logo-spin" src="logo.png" alt="" aria-hidden="true">';
    (document.body || document.documentElement).appendChild(o);
    return o;
  }

  function show() {
    getOverlay().classList.add('show');
  }

  function hide() {
    var o = document.getElementById(OVERLAY_ID);
    if (o) o.classList.remove('show');
  }

  function isInternalLink(a) {
    if (!a) return false;
    if (a.target === '_blank') return false;
    if (a.hasAttribute('download')) return false;
    if (a.host && a.host !== window.location.host) return false; // externe
    var href = a.getAttribute('href') || '';
    if (!href) return false;
    if (href.indexOf('javascript:') === 0) return false;
    if (href.indexOf('mailto:') === 0) return false;
    if (href.indexOf('tel:') === 0) return false;
    if (href.charAt(0) === '#') return false; // ancres / scroll
    return true;
  }

  function onClick(e) {
    // Clic modifié (nouvel onglet) → on ne bloque pas l'interface.
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
      return;
    var a = e.target && e.target.closest ? e.target.closest('a') : null;
    if (isInternalLink(a)) show();
  }

  function bind() {
    document.addEventListener('click', onClick, true);
    // Page restaurée depuis le cache (bfcache) ou chargée : on cache.
    window.addEventListener('pageshow', hide);
    window.addEventListener('load', hide);
    // Filet de sécurité si 'load' ne se déclenche jamais.
    setTimeout(hide, 12000);
  }

  window.Loader = { show: show, hide: hide };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();