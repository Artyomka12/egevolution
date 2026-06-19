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

    var observer = new IntersectionObserver(
        function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.12 }
    );

    document.querySelectorAll('.reveal').forEach(function (el) {
        observer.observe(el);
    });
})();
