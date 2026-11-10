/* Arkan UI kit, R0: display settings, sheets, list detail, filters, toasts. No dependencies, no network.
   Load in <head> so the saved display settings apply before the page paints.
   Settings live in localStorage under "arkan-ui.<name>" and are set on <html> as data-theme, data-density, data-size, data-motion.
   Markup contract (data attributes):
     [data-ui-setting="theme|density|size|motion"][data-value]   button of a segmented control
     [data-ui-open="sheetId"]  [data-ui-close]                   open or close a .sheet-wrap
     [data-ui-detail="templateId"]                               a row that shows <template id> in the side panel, or in a sheet on narrow widths
     [data-ui-filter="name"] [data-value]                        chips or tree buttons; rows are [data-ui-row="name"][data-tags="a b"]
     [data-ui-search="name"]                                     text input that filters the same rows
     [data-ui-toast="message"]                                   shows a short message
     .gridpick[data-ui-single] .pick                             one choice at a time; .toggle flips aria-pressed on its own */
(function () {
  'use strict';
  var PREFIX = 'arkan-ui.';
  var CHOICES = {
    theme: ['system', 'light', 'dark', 'contrast'],
    density: ['comfortable', 'compact'],
    size: ['small', 'normal', 'large'],
    motion: ['full', 'reduce']
  };
  var DEFAULT = { theme: 'system', density: 'comfortable', size: 'normal', motion: 'full' };
  var root = document.documentElement;
  var state = {};
  var lastFocus = null;
  var toastTimer = null;

  function read(k) {
    try {
      var v = localStorage.getItem(PREFIX + k);
      return CHOICES[k].indexOf(v) > -1 ? v : DEFAULT[k];
    } catch (e) { return DEFAULT[k]; }
  }
  function write(k, v) { try { localStorage.setItem(PREFIX + k, v); } catch (e) { /* storage blocked: the choice lasts for this page only */ } }

  /* A page that embeds this one may set data-theme itself (a viewer's own light or dark choice). "System" must leave that alone:
     the attribute is removed only when this script set it, and then put back as it was. */
  var hostTheme = null, ownsTheme = false;
  function paint(k, v) {
    state[k] = v;
    if (k === 'theme') {
      if (v === DEFAULT.theme) {
        if (ownsTheme) {
          ownsTheme = false;
          if (hostTheme) root.setAttribute('data-theme', hostTheme); else root.removeAttribute('data-theme');
        }
      } else {
        if (!ownsTheme) { hostTheme = root.getAttribute('data-theme'); ownsTheme = true; }
        root.setAttribute('data-theme', v);
      }
    } else if (v === DEFAULT[k]) root.removeAttribute('data-' + k); else root.setAttribute('data-' + k, v);
    var btns = document.querySelectorAll('[data-ui-setting="' + k + '"]');
    for (var i = 0; i < btns.length; i++) btns[i].setAttribute('aria-pressed', String(btns[i].getAttribute('data-value') === v));
  }

  /* A change made in a page inside a frame, or in the frame's parent, reaches the others through postMessage. */
  function broadcast(k, v) {
    var msg = { arkanUi: 'setting', key: k, value: v };
    if (window.parent && window.parent !== window) window.parent.postMessage(msg, '*');
    var frames = document.getElementsByTagName('iframe');
    for (var i = 0; i < frames.length; i++) {
      try { frames[i].contentWindow.postMessage(msg, '*'); } catch (e) { /* frame not ready */ }
    }
  }
  function set(k, v) {
    if (!CHOICES[k] || CHOICES[k].indexOf(v) < 0 || state[k] === v) return;
    paint(k, v);
    write(k, v);
    broadcast(k, v);
  }
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (d && d.arkanUi === 'setting') set(d.key, d.value);
  });

  Object.keys(CHOICES).forEach(function (k) { paint(k, read(k)); });

  /* Sheets */
  function focusables(el) {
    return el.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');
  }
  function openSheet(id) {
    var wrap = document.getElementById(id);
    if (!wrap) return;
    closeSheets(true);
    lastFocus = document.activeElement;
    wrap.hidden = false;
    document.body.classList.add('sheet-open');
    var first = focusables(wrap.querySelector('.sheet') || wrap)[0];
    (first || wrap.querySelector('.sheet') || wrap).focus();
  }
  function closeSheets(keepFocus) {
    var open = document.querySelectorAll('.sheet-wrap:not([hidden])');
    for (var i = 0; i < open.length; i++) open[i].hidden = true;
    document.body.classList.remove('sheet-open');
    if (!keepFocus && lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function toast(message) {
    var el = document.getElementById('ui-toast');
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3200);
  }

  /* List detail: a side panel on wide shells, a sheet otherwise */
  function showDetail(row) {
    var tpl = document.getElementById(row.getAttribute('data-ui-detail'));
    if (!tpl || !tpl.content) return;
    var list = row.closest('[data-ui-list]') || document;
    var rows = list.querySelectorAll('[data-ui-detail]');
    for (var i = 0; i < rows.length; i++) rows[i].setAttribute('aria-current', String(rows[i] === row));
    var panel = document.querySelector('.lsplit > .panel');
    var panelShown = panel && getComputedStyle(panel).display !== 'none' && row.getAttribute('data-ui-sheet') !== 'only';
    if (panelShown) {
      panel.innerHTML = '';
      panel.appendChild(tpl.content.cloneNode(true));
      return;
    }
    var body = document.getElementById('ui-sheet-body');
    var sheet = document.querySelector('#ui-sheet .sheet');
    if (!body || !sheet) return;
    sheet.classList.toggle('wide', row.getAttribute('data-ui-sheet-size') === 'wide');
    body.innerHTML = '';
    body.appendChild(tpl.content.cloneNode(true));
    openSheet('ui-sheet');
  }

  /* Filters: chips or tree buttons narrow rows by tag, search narrows by text; both apply together.
     Several controls may share one name (a folder tree on wide screens, chips on narrow ones); they stay in step. */
  var picked = {};
  function pickFilter(name, value) {
    picked[name] = value;
    var items = document.querySelectorAll('[data-ui-filter="' + name + '"] [data-value]');
    for (var i = 0; i < items.length; i++) {
      var on = items[i].getAttribute('data-value') === value;
      items[i].setAttribute(items[i].classList.contains('fchip') ? 'aria-pressed' : 'aria-current', String(on));
    }
    applyFilter(name);
  }
  function applyFilter(name) {
    var want = picked[name] || 'all';
    var input = document.querySelector('[data-ui-search="' + name + '"]');
    var q = input ? input.value.trim().toLowerCase() : '';
    var rows = document.querySelectorAll('[data-ui-row="' + name + '"]');
    var shown = 0;
    for (var i = 0; i < rows.length; i++) {
      var tags = ' ' + (rows[i].getAttribute('data-tags') || '') + ' ';
      var ok = (want === 'all' || tags.indexOf(' ' + want + ' ') > -1) && (!q || rows[i].textContent.toLowerCase().indexOf(q) > -1);
      rows[i].hidden = !ok;
      if (ok) shown++;
    }
    var groups = document.querySelectorAll('[data-ui-group="' + name + '"]');
    for (var g = 0; g < groups.length; g++) {
      groups[g].hidden = !groups[g].querySelector('[data-ui-row="' + name + '"]:not([hidden])');
    }
    var empty = document.querySelector('[data-ui-empty="' + name + '"]');
    if (empty) empty.hidden = shown > 0;
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    if (t.classList.contains('sheet-wrap')) { closeSheets(); return; }

    var el = t.closest('[data-ui-setting]');
    if (el) { set(el.getAttribute('data-ui-setting'), el.getAttribute('data-value')); return; }

    el = t.closest('[data-ui-open]');
    if (el) { e.preventDefault(); openSheet(el.getAttribute('data-ui-open')); return; }

    el = t.closest('[data-ui-close]');
    if (el) { closeSheets(); return; }

    el = t.closest('[data-ui-detail]');
    if (el) { showDetail(el); return; }

    el = t.closest('[data-ui-filter] [data-value]');
    if (el) { pickFilter(el.closest('[data-ui-filter]').getAttribute('data-ui-filter'), el.getAttribute('data-value')); return; }

    el = t.closest('[data-ui-single] .pick');
    if (el) {
      var picks = el.closest('[data-ui-single]').querySelectorAll('.pick');
      for (var j = 0; j < picks.length; j++) picks[j].setAttribute('aria-pressed', String(picks[j] === el));
      return;
    }

    el = t.closest('.toggle');
    if (el) { el.setAttribute('aria-pressed', String(el.getAttribute('aria-pressed') !== 'true')); return; }

    el = t.closest('[data-ui-toast]');
    if (el) { e.preventDefault(); toast(el.getAttribute('data-ui-toast')); }
  });

  document.addEventListener('input', function (e) {
    var name = e.target && e.target.getAttribute && e.target.getAttribute('data-ui-search');
    if (name) applyFilter(name);
  });

  document.addEventListener('keydown', function (e) {
    var open = document.querySelector('.sheet-wrap:not([hidden])');
    if (!open) return;
    if (e.key === 'Escape') { closeSheets(); return; }
    if (e.key !== 'Tab') return;
    var f = focusables(open.querySelector('.sheet') || open);
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  document.addEventListener('DOMContentLoaded', function () {
    Object.keys(CHOICES).forEach(function (k) { paint(k, state[k]); });
  });

  window.ArkanUI = { set: set, get: function (k) { return state[k]; }, openSheet: openSheet, closeSheets: closeSheets, toast: toast, choices: CHOICES };
})();
