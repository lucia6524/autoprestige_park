/* ==========================================================================
   Notify — notifications toast & dialogues de confirmation (site entier)
  --------------------------------------------------------------------------
   Système partagé, zéro dépendance : js/notify.js fournit window.Notify.

     Notify.success(message, opts?)   Notify.error(message, opts?)
     Notify.info(message, opts?)      Notify.warning(message, opts?)
     await Notify.ask({ title, message, confirmLabel, cancelLabel, tone })
        → Promise<boolean>  (remplace confirm())

   opts : { title?: string, duration?: ms }
   Style : variables du thème (style.css) avec replis → fonctionne aussi sur
   la page admin (palette propre). Aucun innerHTML avec donnée externe :
   tout le texte passe par textContent (anti-XSS).
   ========================================================================== */
(function () {
  'use strict';

  var ICONS = {
    success: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
    error: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    info: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    warning: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
  };

  var DURATIONS = { success: 3800, info: 4500, warning: 5500, error: 6500 };
  var MAX_VISIBLE = 4;

  var CSS = ''
    + '.notify-stack{position:fixed;top:18px;right:18px;z-index:2147483000;display:flex;'
    + 'flex-direction:column;gap:10px;width:min(380px,calc(100vw - 24px));pointer-events:none;'
    + 'font-family:inherit}'
    + '.nt-toast{pointer-events:auto;display:flex;align-items:flex-start;gap:12px;position:relative;'
    + 'overflow:hidden;background:var(--bg-card,var(--card,#fff));color:var(--text-primary,var(--text,#111827));'
    + 'border:1px solid var(--border,#e5e7eb);border-left:4px solid var(--nt-accent,#2563eb);'
    + 'border-radius:12px;box-shadow:var(--shadow-lg,0 12px 32px rgba(0,0,0,.18));'
    + 'padding:14px 40px 14px 14px;animation:nt-in .28s cubic-bezier(.21,1.02,.73,1) both}'
    + '.nt-toast.nt-leaving{animation:nt-out .22s ease both}'
    + '.nt-icon{flex:none;width:28px;height:28px;border-radius:9px;display:flex;align-items:center;'
    + 'justify-content:center;background:color-mix(in srgb,var(--nt-accent,#2563eb) 14%,transparent);'
    + 'color:var(--nt-accent,#2563eb)}'
    + '.nt-body{min-width:0;flex:1}'
    + '.nt-title{font-size:.86rem;font-weight:700;margin:0 0 2px;color:var(--text-primary,var(--text,#111827))}'
    + '.nt-msg{font-size:.86rem;line-height:1.45;margin:0;color:var(--text-secondary,var(--text-muted,#4b5563));word-wrap:break-word}'
    + '.nt-close{position:absolute;top:8px;right:8px;width:24px;height:24px;border:none;background:transparent;'
    + 'color:var(--text-muted,#9ca3af);cursor:pointer;border-radius:7px;display:flex;align-items:center;'
    + 'justify-content:center;font-size:15px;line-height:1}'
    + '.nt-close:hover{background:rgba(128,128,128,.14);color:var(--text-primary,var(--text,#111827))}'
    + '.nt-bar{position:absolute;left:0;bottom:0;height:3px;width:100%;'
    + 'background:var(--nt-accent,#2563eb);opacity:.45;transform-origin:left;animation:nt-bar linear forwards}'
    + '.nt-success{--nt-accent:var(--success,#16a34a)}'
    + '.nt-error{--nt-accent:var(--danger,#dc2626)}'
    + '.nt-info{--nt-accent:var(--accent-light,var(--accent,#2563eb))}'
    + '.nt-warning{--nt-accent:var(--warning,#d97706)}'
    + '@keyframes nt-in{from{opacity:0;transform:translateX(110%)}to{opacity:1;transform:none}}'
    + '@keyframes nt-out{to{opacity:0;transform:translateY(-8px)}}'
    + '@keyframes nt-bar{from{transform:scaleX(1)}to{transform:scaleX(0)}}'
    + '.nt-dialog-backdrop{position:fixed;inset:0;z-index:2147483001;background:rgba(9,9,14,.55);'
    + 'backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;padding:20px;'
    + 'animation:nt-fade .18s ease both}'
    + '.nt-dialog{width:min(430px,100%);background:var(--bg-card,var(--card,#fff));'
    + 'color:var(--text-primary,var(--text,#111827));border:1px solid var(--border,#e5e7eb);'
    + 'border-radius:16px;box-shadow:var(--shadow-lg,0 24px 64px rgba(0,0,0,.3));padding:24px;'
    + 'animation:nt-pop .22s cubic-bezier(.21,1.02,.73,1) both}'
    + '.nt-dialog h3{margin:0 0 8px;font-size:1.05rem;font-weight:800}'
    + '.nt-dialog p{margin:0 0 20px;font-size:.92rem;line-height:1.55;'
    + 'color:var(--text-secondary,var(--text-muted,#4b5563))}'
    + '.nt-dialog-actions{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}'
    + '.nt-btn{padding:10px 18px;border-radius:10px;font:inherit;font-size:.9rem;font-weight:700;'
    + 'cursor:pointer;border:1.5px solid var(--border,#e5e7eb);background:transparent;'
    + 'color:var(--text-primary,var(--text,#111827))}'
    + '.nt-btn:hover{border-color:var(--text-muted,#9ca3af)}'
    + '.nt-btn-primary{background:var(--accent,var(--accent-light,#2563eb));border-color:transparent;color:#fff}'
    + '.nt-btn-primary:hover{background:var(--accent-hover,var(--accent-light,#2563eb));border-color:transparent}'
    + '.nt-btn-danger{background:var(--danger,#dc2626);border-color:transparent;color:#fff}'
    + '.nt-btn-danger:hover{filter:brightness(1.08);border-color:transparent}'
    + '@keyframes nt-fade{from{opacity:0}to{opacity:1}}'
    + '@keyframes nt-pop{from{opacity:0;transform:scale(.94) translateY(8px)}to{opacity:1;transform:none}}'
    + '@media (prefers-reduced-motion:reduce){.nt-toast,.nt-dialog,.nt-dialog-backdrop{animation-duration:.01ms}'
    + '.nt-bar{animation-duration:9999s}}';

  function injectStyle() {
    if (document.querySelector('style[data-notify]')) return;
    var style = document.createElement('style');
    style.setAttribute('data-notify', '');
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function getStack() {
    var stack = document.querySelector('.notify-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'notify-stack';
      stack.setAttribute('role', 'status');
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    return stack;
  }

  /* ===== Toasts ===== */

  function dismissToast(toast) {
    if (!toast || toast.__leaving) return;
    toast.__leaving = true;
    toast.classList.add('nt-leaving');
    setTimeout(function () { toast.remove(); }, 240);
  }

  function show(message, opts) {
    opts = opts || {};
    var type = opts.type || 'info';
    injectStyle();
    var stack = getStack();

    while (stack.children.length >= MAX_VISIBLE) {
      dismissToast(stack.firstElementChild);
    }

    var toast = document.createElement('div');
    toast.className = 'nt-toast nt-' + type;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

    var icon = document.createElement('span');
    icon.className = 'nt-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = ICONS[type] || ICONS.info;

    var body = document.createElement('div');
    body.className = 'nt-body';
    if (opts.title) {
      var title = document.createElement('p');
      title.className = 'nt-title';
      title.textContent = opts.title; // textContent : jamais d'HTML injecté
      body.appendChild(title);
    }
    var msg = document.createElement('p');
    msg.className = 'nt-msg';
    msg.textContent = message || '';
    body.appendChild(msg);

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'nt-close';
    close.setAttribute('aria-label', 'Fermer la notification');
    close.textContent = '✕';
    close.addEventListener('click', function () { dismissToast(toast); });

    var bar = document.createElement('span');
    bar.className = 'nt-bar';
    bar.setAttribute('aria-hidden', 'true');
    var duration = typeof opts.duration === 'number' ? opts.duration : (DURATIONS[type] || 4500);
    bar.style.animationDuration = duration + 'ms';

    toast.appendChild(icon);
    toast.appendChild(body);
    toast.appendChild(close);
    toast.appendChild(bar);
    stack.appendChild(toast);

    // Pause au survol : la barre ET le minuteur s'arrêtent, puis reprennent.
    var timer = setTimeout(function () { dismissToast(toast); }, duration);
    toast.addEventListener('mouseenter', function () {
      clearTimeout(timer);
      var computed = getComputedStyle(bar);
      bar.style.animation = 'none';
      bar.style.transform = 'scaleX(' + (parseFloat(computed.width) / Math.max(toast.offsetWidth, 1)) + ')';
    });
    toast.addEventListener('mouseleave', function () {
      bar.style.animation = '';
      bar.style.transform = '';
      timer = setTimeout(function () { dismissToast(toast); }, 1200);
    });

    return toast;
  }

  /* ===== Dialogue de confirmation (remplace confirm()) ===== */

  function ask(opts) {
    opts = opts || {};
    injectStyle();
    return new Promise(function (resolve) {
      var previouslyFocused = document.activeElement;

      var backdrop = document.createElement('div');
      backdrop.className = 'nt-dialog-backdrop';

      var dialog = document.createElement('div');
      dialog.className = 'nt-dialog';
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('aria-modal', 'true');
      var titleId = 'nt-dialog-title-' + Date.now();
      dialog.setAttribute('aria-labelledby', titleId);

      var title = document.createElement('h3');
      title.id = titleId;
      title.textContent = opts.title || 'Confirmer votre action';

      var text = document.createElement('p');
      text.textContent = opts.message || '';

      var actions = document.createElement('div');
      actions.className = 'nt-dialog-actions';

      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'nt-btn';
      cancel.textContent = opts.cancelLabel || 'Annuler';

      var confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'nt-btn ' + (opts.tone === 'danger' ? 'nt-btn-danger' : 'nt-btn-primary');
      confirmBtn.textContent = opts.confirmLabel || 'Confirmer';

      function close(result) {
        document.removeEventListener('keydown', onKey, true);
        backdrop.remove();
        if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
        resolve(result);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.stopPropagation(); close(false); }
        if (e.key === 'Tab') {
          // Piège de focus minimaliste : deux boutons seulement.
          if (document.activeElement === confirmBtn && e.shiftKey) {
            e.preventDefault(); cancel.focus();
          } else if (document.activeElement === cancel && !e.shiftKey) {
            e.preventDefault(); confirmBtn.focus();
          }
        }
      }

      cancel.addEventListener('click', function () { close(false); });
      confirmBtn.addEventListener('click', function () { close(true); });
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) close(false);
      });
      document.addEventListener('keydown', onKey, true);

      actions.appendChild(cancel);
      actions.appendChild(confirmBtn);
      dialog.appendChild(title);
      dialog.appendChild(text);
      dialog.appendChild(actions);
      backdrop.appendChild(dialog);
      document.body.appendChild(backdrop);
      confirmBtn.focus();
    });
  }

  window.Notify = {
    show: show,
    success: function (m, o) { return show(m, Object.assign({ type: 'success' }, o)); },
    error: function (m, o) { return show(m, Object.assign({ type: 'error' }, o)); },
    info: function (m, o) { return show(m, Object.assign({ type: 'info' }, o)); },
    warning: function (m, o) { return show(m, Object.assign({ type: 'warning' }, o)); },
    ask: ask
  };
})();
