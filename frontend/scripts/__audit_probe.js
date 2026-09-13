/* Audit console — collecte erreurs/warnings/rejets/ressources/CSP.
   Copié dans dist/ par scripts/__audit_pages.py, injecté en tête de <head>,
   retiré du build à la fin de l'audit. Expose le JSON dans #__audit_out. */
(function () {
  "use strict";
  var OUT = {
    page: location.pathname,
    consoleErrors: [],
    consoleWarns: [],
    jsErrors: [],
    rejections: [],
    resources: [],
    csp: [],
    ready: false,
  };
  window.__audit = OUT;

  function brief(v) {
    if (v == null) return "null";
    if (v instanceof Error) return v.name + ": " + v.message;
    if (typeof v === "object") {
      try { return JSON.stringify(v).slice(0, 300); } catch (e) { return "[object]"; }
    }
    return String(v).slice(0, 300);
  }

  var _error = console.error.bind(console);
  console.error = function () {
    OUT.consoleErrors.push([].slice.call(arguments).map(brief).join(" | ").slice(0, 400));
    _error.apply(null, arguments);
  };
  var _warn = console.warn.bind(console);
  console.warn = function () {
    OUT.consoleWarns.push([].slice.call(arguments).map(brief).join(" | ").slice(0, 400));
    _warn.apply(null, arguments);
  };

  window.addEventListener("error", function (e) {
    if (e.target && (e.target.src || e.target.href) && e.target.tagName) {
      OUT.resources.push((e.target.tagName + " " + (e.target.src || e.target.href)).slice(0, 300));
      return;
    }
    OUT.jsErrors.push(((e.message || "?") + " @" + (e.filename || "?") + ":" + (e.lineno || "?")).slice(0, 400));
  }, true);

  window.addEventListener("unhandledrejection", function (e) {
    OUT.rejections.push(brief(e.reason).slice(0, 400));
  });

  document.addEventListener("securitypolicyviolation", function (e) {
    OUT.csp.push((e.violatedDirective + " " + e.blockedURL).slice(0, 300));
  });

  function render() {
    var el = document.getElementById("__audit_out");
    if (!el) return;
    el.textContent = "AUDIT_JSON=" + JSON.stringify(OUT);
  }
  setInterval(render, 400);
  window.addEventListener("load", function () {
    setTimeout(function () { OUT.ready = true; render(); }, 2500);
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (document.getElementById("__audit_out")) return;
    var el = document.createElement("pre");
    el.id = "__audit_out";
    el.style.cssText = "display:none";
    document.body.appendChild(el);
    render();
  });
})();
