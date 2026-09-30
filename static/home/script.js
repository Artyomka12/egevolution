/* Homepage interactions. The approved opening remains in hero.js. */
(function () {
    'use strict';
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    var progressBar = document.getElementById('nhProgressBar');
    var progressFrame = 0;
    function updateProgress() {
        var page = document.documentElement;
        var max = page.scrollHeight - page.clientHeight;
        progressBar.style.width = (max > 0 ? page.scrollTop / max * 100 : 0) + '%';
        progressFrame = 0;
    }
    function queueProgress() { if (!progressFrame) progressFrame = requestAnimationFrame(updateProgress); }
    if (progressBar) {
        window.addEventListener('scroll', queueProgress, { passive: true });
        window.addEventListener('resize', queueProgress, { passive: true });
        if ('ResizeObserver' in window) new ResizeObserver(queueProgress).observe(document.body);
        updateProgress();
    }

    if (!reduced.matches && 'IntersectionObserver' in window) {
        var revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    revealObserver.unobserve(entry.target);
                }
            });
        }, { threshold: .08 });
        document.querySelectorAll('.nh-content .reveal').forEach(function (element) {
            element.classList.add('will-reveal');
            revealObserver.observe(element);
        });
    }

    var tabs = Array.from(document.querySelectorAll('.nh-platform-tabs [role="tab"]'));
    function selectTab(tab, focus) {
        var previous = tabs.find(function (item) { return item.getAttribute('aria-selected') === 'true'; });
        if (previous === tab) { if (focus) tab.focus(); return; }
        var container = document.querySelector('.nh-platform-panels');
        var height = container.getBoundingClientRect().height;
        container.getAnimations().forEach(function (animation) { animation.cancel(); });
        tabs.forEach(function (item) {
            var active = item === tab;
            item.setAttribute('aria-selected', String(active));
            item.tabIndex = active ? 0 : -1;
            var panel = document.getElementById(item.getAttribute('aria-controls'));
            panel.getAnimations({ subtree: true }).forEach(function (animation) { animation.cancel(); });
            panel.hidden = !active;
        });
        var incoming = document.getElementById(tab.getAttribute('aria-controls'));
        if (!reduced.matches) {
            var direction = tabs.indexOf(tab) > tabs.indexOf(previous) ? 1 : -1;
            container.animate([{ height: height + 'px' }, { height: incoming.offsetHeight + 'px' }], { duration: 340, easing: 'cubic-bezier(.2,.7,.3,1)' });
            Array.from(incoming.children).forEach(function (part, index) {
                part.animate([
                    { opacity: 0, transform: 'translate(' + direction * (index ? 24 : 12) + 'px, 9px)' },
                    { opacity: 1, transform: 'translate(0, 0)' }
                ], { duration: 420, delay: index * 55, fill: 'backwards', easing: 'cubic-bezier(.2,.7,.3,1)' });
            });
        }
        if (focus) tab.focus();
    }
    tabs.forEach(function (tab, index) {
        tab.addEventListener('click', function () { selectTab(tab, false); });
        tab.addEventListener('keydown', function (event) {
            var next;
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
            if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
            if (event.key === 'Home') next = 0;
            if (event.key === 'End') next = tabs.length - 1;
            if (next !== undefined) { event.preventDefault(); selectTab(tabs[next], true); }
        });
    });

    var dialog = document.getElementById('screenDialog');
    var dialogImage = document.getElementById('dialogImage');
    document.querySelectorAll('.nh-screen-open').forEach(function (button) {
        button.addEventListener('click', function () {
            var source = button.querySelector('img');
            dialogImage.src = source.currentSrc || source.src;
            dialogImage.alt = source.alt;
            document.getElementById('dialogCaption').textContent = source.alt;
            dialog.showModal();
            dialog.querySelector('.nh-screen-scroll').scrollTo(0, 0);
        });
    });
    dialog.addEventListener('click', function (event) {
        if (event.target !== dialog) return;
        var bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });

    var reviewTrack = document.getElementById('reviewTrack');
    var reviews = Array.from(reviewTrack.children);
    var reviewIndex = 0;
    var story = document.getElementById('reviewStory');
    // Only results stated in the original reviews. Missing scores are never inferred.
    var stories = [
        { from: '44', to: '94', caption: 'Ярослав · Пробный → ЕГЭ' },
        { words: 'Прогресс за 3 недели', caption: 'Арсений · Первые результаты занятий' },
        { words: 'Знания по полочкам', caption: 'Юлия Сидякина · Понятные объяснения' },
        { words: 'Ребёнок доволен', caption: 'Людмила · После четырёх занятий' },
        { from: 'С нуля', to: '88', caption: 'Алёна · За 10 месяцев подготовки' },
        { words: 'Понятнее сложные темы', caption: 'Тимур · Подготовка практически с нуля' },
        { from: '52', to: '90', caption: 'Аскольд · Результат старшей дочери. Младший сын — 84 балла за 21 занятие.' }
    ];
    var lastStory = 0;
    function updateStory(index) {
        if (lastStory === index) return;
        lastStory = index;
        var data = stories[index];
        var result = document.createElement('div');
        if (data.words) {
            result.className = 'nh-result-words';
            result.textContent = data.words;
        } else {
            result.className = 'nh-result-score';
            var from = document.createElement('span');
            from.textContent = data.from;
            if (!/^\d+$/.test(data.from)) from.className = 'nh-result-from-text';
            var arrow = document.createElement('i');
            arrow.textContent = '→'; arrow.setAttribute('aria-hidden', 'true');
            var to = document.createElement('strong'); to.textContent = data.to;
            result.append(from, arrow, to);
        }
        var caption = document.createElement('p');
        caption.className = 'nh-result-caption'; caption.textContent = data.caption;
        story.replaceChildren(result, caption);
        story.getAnimations().forEach(function (animation) { animation.cancel(); });
        if (!reduced.matches) story.animate([{ opacity: .2, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 300, easing: 'ease-out' });
    }
    function readReviewPosition() {
        reviewIndex = Math.max(0, Math.min(reviews.length - 1, Math.round(reviewTrack.scrollLeft / reviewTrack.clientWidth)));
        document.getElementById('reviewCount').textContent = (reviewIndex + 1) + ' / ' + reviews.length;
        updateStory(reviewIndex);
    }
    function moveReview(direction) {
        var next = (reviewIndex + direction + reviews.length) % reviews.length;
        reviewTrack.scrollTo({ left: next * reviewTrack.clientWidth, behavior: reduced.matches ? 'instant' : 'smooth' });
    }
    reviewTrack.addEventListener('scroll', readReviewPosition, { passive: true });
    document.getElementById('reviewPrev').addEventListener('click', function () { moveReview(-1); });
    document.getElementById('reviewNext').addEventListener('click', function () { moveReview(1); });
    reviewTrack.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault(); moveReview(event.key === 'ArrowRight' ? 1 : -1);
        }
    });
    window.addEventListener('resize', function () {
        reviewTrack.scrollTo({ left: reviewIndex * reviewTrack.clientWidth, behavior: 'instant' });
    }, { passive: true });
    // Keep native details semantics, while animating both opening and closing.
    document.querySelectorAll('.nh-faq-list details').forEach(function (details) {
        var summary = details.querySelector('summary');
        var animation = null;
        var desiredOpen = details.open;
        summary.addEventListener('click', function (event) {
            event.preventDefault();
            desiredOpen = !desiredOpen;
            var start = details.getBoundingClientRect().height;
            if (animation) { animation.cancel(); animation = null; }
            if (reduced.matches) { details.open = desiredOpen; details.style.overflow = ''; return; }
            details.open = true;
            var style = getComputedStyle(details);
            var closedHeight = summary.getBoundingClientRect().height + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
            var end = desiredOpen ? details.getBoundingClientRect().height : closedHeight;
            details.style.overflow = 'hidden';
            animation = details.animate([{ height: start + 'px' }, { height: end + 'px' }], { duration: 300, easing: 'cubic-bezier(.2,.7,.3,1)' });
            animation.onfinish = function () {
                details.open = desiredOpen;
                details.style.overflow = '';
                animation = null;
            };
        });
    });
})();
