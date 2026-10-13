/* Cookie banner behaviour for the demo site. Configured per page with data attributes on the script tag:
 *   data-pre-consent-cookie  analytics-style cookie set BEFORE any choice (a deliberate fault when present)
 *   data-accept-cookie       analytics-style cookie set once the visitor accepts
 *   data-reject              "honoured" (default) or "ignored": whether the accept cookie is still set after Reject
 * All cookies are harmless demo values on 127.0.0.1; nothing leaves the machine. */
(function () {
  var cfg = document.currentScript.dataset;
  var KEY = 'tidewick-consent';
  var banner = document.querySelector('.cookie-banner');

  function hasCookie(name) { return document.cookie.split('; ').some(function (c) { return c.indexOf(name + '=') === 0; }); }
  function setCookie(name) { if (!hasCookie(name)) document.cookie = name + '=demo; path=/; max-age=31536000; SameSite=Lax'; }
  function apply(choice) {
    if (!cfg.acceptCookie) return;
    if (choice === 'accepted' || (choice === 'rejected' && cfg.reject === 'ignored')) setCookie(cfg.acceptCookie);
  }

  if (cfg.preConsentCookie) setCookie(cfg.preConsentCookie);

  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { /* storage blocked: treat as no choice */ }
  if (stored) { apply(stored); if (banner) banner.hidden = true; }

  if (banner) {
    banner.addEventListener('click', function (ev) {
      var btn = ev.target.closest('button[data-consent]');
      if (!btn) return;
      var choice = btn.getAttribute('data-consent');
      try { localStorage.setItem(KEY, choice); } catch (e) { /* ignore */ }
      apply(choice);
      banner.hidden = true;
    });
  }
})();
