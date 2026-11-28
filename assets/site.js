/* Eglur · www.eglurtech.com
   Navigation, the case animation, the draft demo and the contact form.
   No cookies, no tracking, no dependencies. Everything here is an enhancement:
   every page reads in full without it. */
(function () {
  'use strict';

  var doc = document;
  /* Loaded in <head>, so the page never shows a state it is about to hide. */
  doc.documentElement.classList.add('js');
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();

  function init() {

    var reduce = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    var canHover = window.matchMedia ? window.matchMedia('(hover: hover)') : { matches: false };

    function $(sel, el) { return (el || doc).querySelector(sel); }
    function $$(sel, el) { return Array.prototype.slice.call((el || doc).querySelectorAll(sel)); }
    function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
    function easeOut(x) { return 1 - Math.pow(1 - x, 3); }

    /* ---------- Header: a hairline once the page moves ---------- */
    var header = $('.site-header');
    if (header) {
      var queued = false;
      var paint = function () { header.classList.toggle('scrolled', window.scrollY > 8); queued = false; };
      window.addEventListener('scroll', function () {
        if (!queued) { queued = true; window.requestAnimationFrame(paint); }
      }, { passive: true });
      paint();
    }

    /* ---------- Phone menu: close on Escape, outside tap or a chosen link ---------- */
    $$('.menu').forEach(function (menu) {
      var summary = $('summary', menu);
      doc.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && menu.open) { menu.open = false; summary.focus(); }
      });
      doc.addEventListener('click', function (e) {
        if (menu.open && !menu.contains(e.target)) menu.open = false;
      });
      $$('a', menu).forEach(function (a) {
        a.addEventListener('click', function () { menu.open = false; });
      });
    });

    /* ---------- Section spy: links light up for the section in view ---------- */
    var spyLinks = $$('[data-spy]');
    if (spyLinks.length && 'IntersectionObserver' in window) {
      var bySection = {};
      spyLinks.forEach(function (a) {
        var id = a.getAttribute('data-spy');
        if (doc.getElementById(id)) (bySection[id] = bySection[id] || []).push(a);
      });
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          (bySection[e.target.id] || []).forEach(function (a) {
            if (e.isIntersecting) {
              var group = a.getAttribute('data-g') || 'nav';
              spyLinks.forEach(function (x) {
                if ((x.getAttribute('data-g') || 'nav') === group) x.classList.remove('here');
              });
              a.classList.add('here');
            } else {
              a.classList.remove('here');
            }
          });
        });
      }, { rootMargin: '-42% 0px -52% 0px' });
      Object.keys(bySection).forEach(function (id) { spy.observe(doc.getElementById(id)); });
    }

    /* ---------- Figures settle into place once, as they arrive ---------- */
    var reveals = $$('.reveal');
    if (reveals.length) {
      if (reduce.matches || !('IntersectionObserver' in window)) {
        reveals.forEach(function (el) { el.classList.add('in'); });
      } else {
        var rv = new IntersectionObserver(function (entries) {
          entries.forEach(function (e) {
            if (e.isIntersecting) { e.target.classList.add('in'); rv.unobserve(e.target); }
          });
        }, { threshold: 0.12 });
        reveals.forEach(function (el) { rv.observe(el); });
      }
    }

    /* ---------- Contents: a line that fills as you read (data page) ---------- */
    var toc = $('.toc');
    if (toc) {
      var layout = toc.closest('.dlayout');
      var list = $('ol', toc);
      var prog = doc.createElement('span');
      prog.className = 'prog';
      prog.setAttribute('aria-hidden', 'true');
      list.appendChild(prog);
      var tocQueued = false;
      var tocPaint = function () {
        var r = layout.getBoundingClientRect();
        var p = clamp((window.innerHeight * 0.4 - r.top) / Math.max(1, r.height - window.innerHeight * 0.5), 0, 1);
        prog.style.setProperty('--p', p.toFixed(3));
        tocQueued = false;
      };
      window.addEventListener('scroll', function () {
        if (!tocQueued) { tocQueued = true; window.requestAnimationFrame(tocPaint); }
      }, { passive: true });
      window.addEventListener('resize', tocPaint);
      tocPaint();
    }

    /* ---------- The case: one constituent's case, by hand and with Eglur ---------- */
    function fmtMinutes(m) {
      m = Math.round(m);
      if (m < 60) return m + ' min';
      var h = Math.floor(m / 60), r = m % 60;
      return h + 'h ' + (r < 10 ? '0' : '') + r + 'm';
    }

    function typeWords(box, timed) {
      var t0 = parseFloat(box.getAttribute('data-type-from'));
      var t1 = parseFloat(box.getAttribute('data-type-to'));
      var words = [];
      Array.prototype.slice.call(box.childNodes).forEach(function (node) {
        if (node.nodeType === 3) {
          var frag = doc.createDocumentFragment();
          node.textContent.split(/(\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(doc.createTextNode(part)); return; }
            var w = doc.createElement('span');
            w.className = 'w';
            w.textContent = part;
            frag.appendChild(w);
            words.push(w);
          });
          box.replaceChild(frag, node);
        } else if (node.nodeType === 1) {
          node.classList.add('w');
          words.push(node);
        }
      });
      words.forEach(function (w, i) {
        var at = t0 + (t1 - t0) * i / Math.max(1, words.length - 1);
        w.setAttribute('data-at', at.toFixed(2));
        timed.push({ el: w, at: at, off: Infinity });
      });
    }

    function initCase(el) {
      var T = parseFloat(el.getAttribute('data-duration')) || 46;
      var stage = $('.case-stage', el);
      var btn = $('.case-play', el);
      var btnText = $('.case-play-txt', el);
      if (!stage || !btn) return;

      var scenes = $$('[data-scene]', el).map(function (s) {
        return { el: s, from: parseFloat(s.getAttribute('data-from')), to: parseFloat(s.getAttribute('data-to')) };
      });
      var chapters = $$('.case-tab', el).map(function (b) {
        return { el: b, start: parseFloat(b.getAttribute('data-start')), end: parseFloat(b.getAttribute('data-end')) };
      });
      var timed = $$('[data-at]', el).map(function (e) {
        return {
          el: e,
          at: parseFloat(e.getAttribute('data-at')),
          off: e.hasAttribute('data-off') ? parseFloat(e.getAttribute('data-off')) : Infinity
        };
      });
      $$('[data-type]', el).forEach(function (box) { typeWords(box, timed); });
      var toggles = $$('[data-cls-at]', el).map(function (e) {
        return { el: e, at: parseFloat(e.getAttribute('data-cls-at')), cls: e.getAttribute('data-cls') };
      });
      $$('[data-min]', el).forEach(function (row) {
        row.style.setProperty('--w', (parseFloat(row.getAttribute('data-min')) / 45 * 100).toFixed(1) + '%');
      });
      var meters = {};
      $$('[data-meter]', el).forEach(function (m) {
        meters[m.getAttribute('data-meter')] = { box: m, v: $('.v', m), steps: [], shown: '' };
      });
      $$('[data-add]', el).forEach(function (s) {
        var parts = s.getAttribute('data-add').split(':');
        var m = meters[parts[0]];
        if (m) m.steps.push({ at: parseFloat(s.getAttribute('data-at')), min: parseFloat(parts[1]) });
      });

      var t = 0, playing = false, ended = false, userPaused = false, last = 0, raf = 0, active = null;

      function fitStage() { if (active) stage.style.height = active.el.offsetHeight + 'px'; }
      var ro = window.ResizeObserver ? new ResizeObserver(fitStage) : null;

      function render() {
        timed.forEach(function (x) { x.el.classList.toggle('on', t >= x.at && t < x.off); });
        toggles.forEach(function (x) { x.el.classList.toggle(x.cls, t >= x.at); });

        var current = scenes[scenes.length - 1];
        scenes.forEach(function (s) { if (t >= s.from && t < s.to) current = s; });
        if (current !== active) {
          scenes.forEach(function (s) { s.el.classList.toggle('on', s === current); });
          if (ro && active) ro.unobserve(active.el);
          active = current;
          if (ro) ro.observe(active.el);
          fitStage();
        }

        Object.keys(meters).forEach(function (k) {
          var m = meters[k], total = 0;
          m.steps.forEach(function (s) { total += s.min * easeOut(clamp((t - s.at) / 0.9, 0, 1)); });
          var text = fmtMinutes(total);
          if (text !== m.shown) { m.v.textContent = text; m.shown = text; }
          m.box.classList.toggle('zero', total < 0.5);
        });

        chapters.forEach(function (c, i) {
          c.el.style.setProperty('--p', clamp((t - c.start) / (c.end - c.start), 0, 1).toFixed(3));
          var isCurrent = t >= c.start && (t < c.end || i === chapters.length - 1);
          c.el.classList.toggle('cur', isCurrent);
          if (isCurrent) c.el.setAttribute('aria-current', 'step');
          else c.el.removeAttribute('aria-current');
        });
      }

      function setButton(state) {
        btn.setAttribute('data-state', state);
        var word = state === 'pause' ? 'Pause' : (state === 'replay' ? 'Replay' : 'Play');
        btnText.textContent = word;
        btn.setAttribute('aria-label', word + ' the animation');
      }

      function tick(now) {
        if (!playing) return;
        t += Math.min(0.25, (now - last) / 1000);   /* slow devices keep pace; a hidden tab pauses instead */
        last = now;
        if (t >= T) {
          t = T;
          render();
          playing = false;
          ended = true;
          setButton('replay');
          return;
        }
        render();
        raf = window.requestAnimationFrame(tick);
      }

      function play() {
        if (ended || t >= T) { t = 0; ended = false; render(); }
        if (playing) return;
        playing = true;
        last = window.performance.now();
        setButton('pause');
        raf = window.requestAnimationFrame(tick);
      }

      function pause() {
        playing = false;
        window.cancelAnimationFrame(raf);
        setButton(ended ? 'replay' : 'play');
      }

      btn.addEventListener('click', function () {
        if (playing) { userPaused = true; pause(); }
        else { userPaused = false; play(); }
      });

      chapters.forEach(function (c) {
        c.el.addEventListener('click', function () {
          ended = false;
          if (reduce.matches) {
            pause();
            t = c.end - 0.01;
            render();
            return;
          }
          t = c.start;
          render();
          userPaused = false;
          play();
        });
      });

      if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
          entries.forEach(function (e) {
            if (e.intersectionRatio >= 0.35) {
              if (!playing && !userPaused && !ended && !reduce.matches) play();
            } else if (e.intersectionRatio < 0.1 && playing) {
              pause();
            }
          });
        }, { threshold: [0, 0.1, 0.35, 0.6] }).observe(stage);
      }
      doc.addEventListener('visibilitychange', function () { if (doc.hidden && playing) pause(); });
      window.addEventListener('resize', fitStage);

      t = reduce.matches && chapters.length ? chapters[0].end - 0.01 : 0;
      render();
      setButton('play');
    }

    $$('.case').forEach(initCase);

    /* ---------- The draft that shows its working ---------- */
    function initDemo(el) {
      var segs = $$('.seg', el);
      var side = $('.demo-side', el);
      if (!segs.length || !side) return;
      var kindEl = $('.demo-kind', side), srcEl = $('.demo-src', side), quoteEl = $('.demo-quote', side);
      var checksEl = $('.demo-checks', side), actions = $('.demo-act', side);
      var errorBtn = $('[data-error]', el), resetBtn = $('[data-reset]', el);
      var target = $('[data-alt]', el);
      var current = null;
      var ATTRS = ['data-kind', 'data-label', 'data-src', 'data-quote', 'data-checks'];

      segs.forEach(function (s) {
        s.setAttribute('role', 'button');
        s.setAttribute('tabindex', '0');
        s.setAttribute('aria-pressed', 'false');
        s._orig = { html: s.innerHTML, cls: s.className };
        ATTRS.forEach(function (a) { s._orig[a] = s.getAttribute(a) || ''; });
        s.addEventListener('click', function () { select(s); });
        s.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(s); }
        });
        s.addEventListener('mouseenter', function () { if (canHover.matches) select(s); });
      });

      function select(s) {
        current = s;
        segs.forEach(function (x) {
          x.classList.toggle('sel', x === s);
          x.setAttribute('aria-pressed', x === s ? 'true' : 'false');
        });
        var kind = s.getAttribute('data-kind');
        side.setAttribute('data-kind', kind);
        kindEl.textContent = s.getAttribute('data-label');
        srcEl.textContent = s.getAttribute('data-src');
        var quote = s.getAttribute('data-quote') || '';
        quoteEl.textContent = quote;
        quoteEl.hidden = !quote;
        checksEl.textContent = '';
        (s.getAttribute('data-checks') || '').split('|').forEach(function (line) {
          if (!line) return;
          var li = doc.createElement('li');
          if (line.charAt(0) === '!') { li.className = 'bad'; line = line.slice(1); }
          li.textContent = line;
          checksEl.appendChild(li);
        });
        actions.hidden = kind !== 'ai';
      }

      function restore(s) {
        s.innerHTML = s._orig.html;
        s.className = s._orig.cls;
        ATTRS.forEach(function (a) { s.setAttribute(a, s._orig[a]); });
        if (s === current) s.classList.add('sel');
      }

      function setError(on) {
        if (!target || !errorBtn) return;
        errorBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
        errorBtn.textContent = on ? 'Remove the error' : 'Introduce an error';
        if (on) {
          var sup = $('sup', target);
          target.textContent = target.getAttribute('data-alt');
          if (sup) target.appendChild(sup.cloneNode(true));
          target.classList.add('k-flag');
          target.setAttribute('data-kind', 'flag');
          target.setAttribute('data-label', 'Flagged');
          target.setAttribute('data-checks', target.getAttribute('data-alt-checks'));
        } else {
          restore(target);
        }
        select(target);
      }

      if (errorBtn) {
        errorBtn.addEventListener('click', function () {
          setError(errorBtn.getAttribute('aria-pressed') !== 'true');
        });
      }

      $('[data-accept]', el).addEventListener('click', function () {
        var s = current;
        if (!s || s.getAttribute('data-kind') !== 'ai') return;
        s.classList.add('accepted');
        s.setAttribute('data-kind', 'yours');
        s.setAttribute('data-label', 'Accepted');
        s.setAttribute('data-checks', 'Accepted by a person: now part of the draft|Now set in the same type as the office’s own words');
        select(s);
      });

      $('[data-reject]', el).addEventListener('click', function () {
        var s = current;
        if (!s || s.getAttribute('data-kind') !== 'ai') return;
        s.classList.add('rejected');
        s.setAttribute('data-kind', 'rejected');
        s.setAttribute('data-label', 'Rejected');
        s.setAttribute('data-checks', 'Rejected by a person: left out of the draft');
        select(s);
      });

      if (resetBtn) {
        resetBtn.addEventListener('click', function () {
          segs.forEach(restore);
          if (errorBtn) {
            errorBtn.setAttribute('aria-pressed', 'false');
            errorBtn.textContent = 'Introduce an error';
          }
          select(segs[1] || segs[0]);
        });
      }

      select(segs[1] || segs[0]);
    }

    $$('[data-demo]').forEach(initDemo);

    /* ---------- Contact form: saved to our database, which emails it on to us ----------
       The public key can only add a message; it can't read any back. */
    function initContact(form) {
      var endpoint = form.getAttribute('data-endpoint'), key = form.getAttribute('data-key');
      var done = doc.getElementById('cf-done'), status = $('[data-status]', form);
      var btn = $('[type="submit"]', form), btnText = btn.textContent, sending = false;
      var inputs = { name: doc.getElementById('cf-name'), email: doc.getElementById('cf-email'),
                     organisation: doc.getElementById('cf-org'), message: doc.getElementById('cf-message') };
      var fails = $$('[data-fail]', form);

      /* "Join an early conversation" links here with ?about=conversation */
      var about = (/[?&]about=([a-z-]{1,40})/.exec(window.location.search) || [])[1];
      $$('input[name="topic"]', form).forEach(function (r) { if (r.value === about) r.checked = true; });

      /* which of our pages they came from, so the reply can pick up the thread */
      var fromPage = '';
      try {
        var ref = doc.referrer ? new URL(doc.referrer) : null;
        if (ref && ref.origin === window.location.origin) {
          fromPage = ref.pathname.replace(/\.html$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '').slice(0, 40);
          if (!fromPage || fromPage === 'index') fromPage = 'home';
        }
      } catch (err) { fromPage = ''; }

      function oneLine(s) { return String(s || '').replace(/[\u0000-\u001f\u007f\s]+/g, ' ').trim(); }
      function values() {
        var topic = $('input[name="topic"]:checked', form);
        return {
          name: oneLine(inputs.name.value),
          email: String(inputs.email.value || '').trim(),
          organisation: oneLine(inputs.organisation.value),
          topic: topic ? topic.value : '',
          message: String(inputs.message.value || '').replace(/\r\n?/g, '\n')
            .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim(),
          from_page: fromPage
        };
      }
      function problem(field, v) {
        if (field === 'name') return !v ? 'Enter your name' : v.length > 120 ? 'Name must be 120 characters or fewer' : '';
        if (field === 'email') return !v ? 'Enter your email address'
          : (v.length > 254 || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) ? 'Enter an email address in the correct format, like name@example.com' : '';
        if (field === 'organisation') return v.length > 160 ? 'Organisation must be 160 characters or fewer' : '';
        if (field === 'message') return !v ? 'Enter a message' : v.length > 5000 ? 'Message must be 5,000 characters or fewer' : '';
        return '';
      }
      function setError(input, msg) {
        var box = doc.getElementById(input.id + '-err');
        var ids = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(function (id) { return id && id !== box.id; });
        if (msg) {
          $('[data-msg]', box).textContent = msg;
          ids.push(box.id);
          input.setAttribute('aria-invalid', 'true');
        } else {
          input.removeAttribute('aria-invalid');
        }
        box.hidden = !msg;
        if (ids.length) input.setAttribute('aria-describedby', ids.join(' '));
        else input.removeAttribute('aria-describedby');
      }
      Object.keys(inputs).forEach(function (field) {
        inputs[field].addEventListener('input', function () {
          if (inputs[field].getAttribute('aria-invalid') === 'true' && !problem(field, values()[field])) setError(inputs[field], '');
        });
      });

      function busy(on) {
        sending = on;
        btn.textContent = on ? 'Sending…' : btnText;
        if (on) { btn.setAttribute('aria-disabled', 'true'); form.setAttribute('aria-busy', 'true'); }
        else { btn.removeAttribute('aria-disabled'); form.removeAttribute('aria-busy'); }
        status.textContent = on ? 'Sending your message…' : '';
      }
      function showFail(kind) {
        fails.forEach(function (f) { f.hidden = f.getAttribute('data-fail') !== kind; });
        btn.focus();
      }
      function showDone(v) {
        $('[data-name]', done).textContent = v.name;
        $('[data-email]', done).textContent = v.email;
        form.hidden = true;
        done.hidden = false;
        var top = done.getBoundingClientRect().top + window.scrollY - 110;
        if (window.scrollY > top) window.scrollTo({ top: Math.max(0, top), behavior: reduce.matches ? 'auto' : 'smooth' });
        $('h2', done).focus({ preventScroll: true });
      }
      $('[data-edit]', done).addEventListener('click', function () {
        form.classList.remove('ld', 'd2');
        done.hidden = true;
        form.hidden = false;
        inputs.email.focus();
        inputs.email.select();
      });

      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (sending) return;
        fails.forEach(function (f) { f.hidden = true; });
        var v = values(), first = null;
        ['name', 'email', 'organisation', 'message'].forEach(function (field) {
          var msg = problem(field, v[field]);
          setError(inputs[field], msg);
          if (msg && !first) first = inputs[field];
        });
        if (first) { first.focus(); return; }

        busy(true);
        var ctl = window.AbortController ? new AbortController() : null;
        var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 20000);
        var headers = { 'apikey': key, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' };
        if (key.indexOf('sb_') !== 0) headers.Authorization = 'Bearer ' + key;   // older JWT keys only
        fetch(endpoint, { method: 'POST', credentials: 'omit', headers: headers, body: JSON.stringify(v), signal: ctl ? ctl.signal : undefined })
          .then(function (r) {
            if (r.ok) return 'sent';
            return r.json().then(function (b) { return (b && b.code) || ''; }, function () { return ''; })
              .then(function (code) { return r.status === 429 || code === 'PT429' ? 'busy' : 'failed'; });
          }, function () { return 'failed'; })
          .then(function (result) {
            clearTimeout(timer);
            busy(false);
            if (result === 'sent') showDone(v); else showFail(result);
          });
      });
    }

    $$('form[data-contact]').forEach(initContact);
  }
})();
