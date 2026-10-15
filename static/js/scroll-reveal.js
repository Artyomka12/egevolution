/* ============================================================
   EGEvolution — Scroll Reveal (shared)
   Добавляет класс .visible элементам с классом .reveal
   при попадании в viewport.
   Подключается через base.html перед {% block scripts %}.
   Не подключается к: start.html (собственная inline-версия),
   exam.html, reshenie.html, admin-шаблонам.
   ============================================================ */
(function () {
    'use strict';

    var elements = Array.from(document.querySelectorAll('.reveal'));
    var pending = new Map();
    var regular, tall, sizes, motion;
    var stopped = false;

    // Fail open: animation must never be required to read the page.
    function revealAll() {
        stopped = true;
        elements.forEach(function (el) {
            el.classList.remove('reveal-pending');
            el.classList.add('visible');
        });
        pending.clear();
        [regular, tall, sizes].forEach(function (observer) {
            try { if (observer) observer.disconnect(); } catch (_) { /* Already visible. */ }
        });
        window.removeEventListener('resize', refresh);
        document.removeEventListener('load', refresh, true);
    }

    function refresh() {
        if (stopped) return;
        try {
            var height = document.documentElement.clientHeight;
            pending.forEach(function (observer, el) {
                var next = el.getBoundingClientRect().height * 0.12 >= height ? tall : regular;
                if (next !== observer) {
                    if (observer) observer.unobserve(el);
                    next.observe(el);
                    pending.set(el, next);
                }
            });
        } catch (_) { revealAll(); }
    }

    function appear(entries, observer) {
        if (stopped) return;
        try {
            entries.forEach(function (entry) {
                // Ignore callbacks queued before a size-driven observer switch.
                if (pending.get(entry.target) !== observer) return;
                if (entry.isIntersecting && (observer === tall || entry.intersectionRatio >= 0.12)) {
                    entry.target.classList.add('visible');
                    pending.delete(entry.target);
                    observer.unobserve(entry.target);
                    if (sizes) sizes.unobserve(entry.target);
                }
            });
        } catch (_) { revealAll(); }
    }

    try {
        motion = window.matchMedia('(prefers-reduced-motion: reduce)');
        if (motion.matches || !('IntersectionObserver' in window)) return;
        regular = new IntersectionObserver(appear, { threshold: 0.12 });
        tall = new IntersectionObserver(appear, { threshold: 0 });
        if ('ResizeObserver' in window) sizes = new ResizeObserver(refresh);

        elements.forEach(function (el) {
            if (el.classList.contains('visible')) return;
            pending.set(el, null);
            if (sizes) sizes.observe(el);
        });
        refresh();
        if (stopped) return;
        // Hide only after observation has been installed successfully.
        pending.forEach(function (_, el) { el.classList.add('reveal-pending'); });
        window.addEventListener('resize', refresh);
        document.addEventListener('load', refresh, true);
        var onMotionChange = function (event) { if (event.matches) revealAll(); };
        if (motion.addEventListener) motion.addEventListener('change', onMotionChange);
        else if (motion.addListener) motion.addListener(onMotionChange);
    } catch (_) { revealAll(); }
})();
