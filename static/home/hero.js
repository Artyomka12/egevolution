/* Camera flight, scattered materials, subject groups, then the goal. */
(function () {
    'use strict';
    var scene = document.getElementById('heroScene');
    if (!scene) return;
    var viewport = scene.querySelector('.evo-viewport');
    var cards = Array.from(scene.querySelectorAll('[data-evo-card]'));
    var copies = Array.from(scene.querySelectorAll('[data-evo-copy]'));
    var subjects = Array.from(scene.querySelectorAll('[data-evo-group]'));
    var fragments = Array.from(scene.querySelectorAll('.evo-fragment'));
    var rings = Array.from(scene.querySelectorAll('.evo-depth-rings i'));
    var chapters = Array.from(scene.querySelectorAll('[data-evo-step]'));
    var field = scene.querySelector('.evo-number-field');
    var grid = scene.querySelector('.evo-grid');
    var enter = scene.querySelector('.evo-enter');
    var cue = scene.querySelector('.evo-scroll-cue');
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    var width, height, start, distance, mobile, cardScale, groupPitch;
    var layouts = [], foreground = [];
    var progress = 0, target = 0, frame = 0, previousTime = 0, activeChapter = -1;
    var FOCAL = 900, CAMERA_END = 1800;
    function clamp(value) { return Math.max(0, Math.min(1, value)); }
    function mix(a, b, t) { return a + (b - a) * t; }
    function ease(a, b, p) { var t = clamp((p - a) / (b - a)); return t * t * (3 - 2 * t); }
    function project(depth, camera) {
        var z = FOCAL + depth - camera;
        return { scale: FOCAL / Math.max(45, z), alpha: ease(45, 180, z) };
    }
    function place(element, x, y, scale, rotate, ry, opacity) {
        element.style.transform = 'translate3d(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px,0) rotate(' + rotate.toFixed(2) + 'deg) rotateY(' + ry.toFixed(2) + 'deg) scale(' + scale.toFixed(4) + ')';
        element.style.opacity = opacity.toFixed(3);
        element.style.visibility = opacity < .005 ? 'hidden' : 'visible';
    }
    function showCopy(index, opacity, scale) {
        var element = copies[index], shown = opacity > .02;
        element.style.opacity = opacity.toFixed(3);
        element.style.visibility = shown ? 'visible' : 'hidden';
        element.style.pointerEvents = opacity > .7 ? 'auto' : 'none';
        element.style.transform = (index === 2 ? '' : 'translateY(-50%) ') + 'scale(' + scale.toFixed(4) + ')';
        element.setAttribute('aria-hidden', shown ? 'false' : 'true');
        element.querySelectorAll('a').forEach(function (link) { link.tabIndex = opacity > .7 ? 0 : -1; });
    }
    for (var n = 0; n < 27; n++) {
        var number = document.createElement('span');
        var angle = (n / 27) * Math.PI * 2 - Math.PI / 2;
        number.textContent = String(n + 1).padStart(2, '0');
        number.style.left = (50 + Math.cos(angle) * (n % 2 ? 46 : 39)) + '%';
        number.style.top = (49 + Math.sin(angle) * (n % 2 ? 40 : 43)) + '%';
        field.appendChild(number);
    }
    function measure() {
        width = viewport.clientWidth; height = viewport.clientHeight;
        start = scene.getBoundingClientRect().top + window.scrollY;
        distance = Math.max(1, scene.offsetHeight - height);
        mobile = window.matchMedia('(max-width: 820px)').matches;
        cardScale = mobile ? Math.max(.45, Math.min(.94, (height - 280) / 620, (width - 65) / 240)) : Math.min(1.12, width / 1440, height / 900);
        groupPitch = mobile ? width * 1.08 : Math.min(width * .285, 430);
        var turns = [-8, 6, -4, 7, -6, 4, -5, 8, -4];
        var depths = [1660, 1960, 1800, 1920, 1700, 2010, 1760, 2000, 1850];
        // Fixed, interleaved positions make the same cards retrace their paths on reverse scroll.
        var scattered = mobile
            ? [[-.30, .05], [.04, .57], [.29, .95], [.29, 0], [-.29, .77], [-.015, .25], [-.12, 1], [.30, .38], [-.29, .40]]
            : [[-.35, -.22], [.03, .04], [.40, .11], [.30, -.29], [-.26, .285], [-.06, -.265], [.155, .30], [.225, -.055], [-.40, .02]];
        var scatteredTurns = [-20, 14, -16, 22, -12, 9, -24, 16, -9];
        var scatteredScales = [.91, .83, .90, .86, 1, .78, .83, .95, .84];
        layouts = cards.map(function (card, i) {
            var group = Number(card.dataset.group), slot = i % 3;
            var offsets = mobile ? [-.13 * width, .13 * width, -.07 * width] : [-55, 58, -32].map(function (x) { return x * cardScale; });
            var targetX = (mobile ? group : group - 1) * groupPitch + offsets[slot];
            var targetY = mobile ? [-.10, .075, .26][slot] * height : [-.155, .055, .24][slot] * height + [0, 8, -9][group] * cardScale;
            return {
                x: targetX, y: targetY, scale: cardScale * [1, .90, .95][slot],
                depth: depths[i], end: project(depths[i], CAMERA_END).scale, r: turns[i], group: group,
                scatteredX: scattered[i][0] * width,
                scatteredY: mobile ? mix(height * .19, height - 155, scattered[i][1]) - height / 2 : scattered[i][1] * height,
                scatteredScale: cardScale * scatteredScales[i] * (mobile ? .65 : 1),
                scatteredR: scatteredTurns[i]
            };
        });
        var positions = mobile ? [[-.39, -.32], [.38, -.29], [-.41, .30], [.40, .31], [-.62, -.02], [.60, .04]] : [[-.38, -.26], [.37, -.27], [-.37, .25], [.38, .26], [-.48, .01], [.46, .015]];
        foreground = positions.map(function (xy, i) {
            var depth = [-100, 160, 290, 40, 390, -160][i], initial = project(depth, 0).scale;
            return { x: xy[0] * width / initial, y: xy[1] * height / initial, scale: (mobile ? .56 : Math.min(1, width / 1450)) / initial, depth: depth, r: [-12, 10, 8, -9, -7, 12][i] };
        });
        updateTarget(); progress = target; draw(progress);
    }
    function draw(p) {
        var dive = ease(.025, .345, p), camera = CAMERA_END * dive;
        var collect = ease(.805, .875, p), compress = ease(.875, .948, p);
        var materialIn = ease(.12, .30, p), materialOut = 1 - ease(.90, .955, p);
        var readingTravel = mobile ? ease(.585, .775, p) * 2 : 0;
        var titleDepth = project(0, camera);
        showCopy(0, titleDepth.alpha * (1 - ease(2.8, 6.2, titleDepth.scale)), titleDepth.scale);
        var insideAlpha = ease(.425, .535, p) * (1 - ease(.79, .845, p));
        showCopy(1, insideAlpha, mix(.92, 1, ease(.425, .535, p)));
        var goal = ease(.915, .985, p);
        showCopy(2, goal, mix(.42, 1, goal));
        foreground.forEach(function (f, i) {
            var depth = project(f.depth, camera);
            place(fragments[i], f.x * depth.scale, f.y * depth.scale, f.scale * depth.scale, f.r, (i % 2 ? -8 : 8), .68 * depth.alpha * (1 - ease(.27, .345, p)));
        });
        cards.forEach(function (card, i) {
            var l = layouts[i], perspective = project(l.depth, camera).scale / l.end;
            var arrange = ease(.385 + i * .003, .54 + i * .003, p);
            var panX = mobile ? readingTravel * groupPitch : 0;
            var x = mix(l.scatteredX, l.x - panX, arrange) * perspective;
            var y = mix(l.scatteredY, l.y, arrange) * perspective;
            var scale = mix(l.scatteredScale, l.scale, arrange) * perspective;
            var rotation = mix(l.scatteredR, l.r, arrange);
            var visibility = mobile ? 1 - ease(.58, 1.13, Math.abs(l.group - readingTravel)) : 1;
            visibility = mix(1, visibility, arrange);
            var orderedScale = mobile ? .27 : .38;
            x = mix(x, (i % 3 - 1) * 254 * orderedScale, collect) * (1 - compress);
            y = mix(y, (Math.floor(i / 3) - 1) * 190 * orderedScale, collect) * (1 - compress);
            scale = mix(scale, orderedScale, collect) * (1 - compress * .88);
            place(card, x, y, scale, rotation * (1 - collect), (i % 2 ? -6 : 5) * (1 - collect), materialIn * materialOut * mix(visibility, 1, collect));
        });
        subjects.forEach(function (subject, i) {
            var visibility = mobile ? 1 - ease(.4, .82, Math.abs(i - readingTravel)) : 1;
            var x = mobile ? (i - readingTravel) * groupPitch : (i - 1) * groupPitch;
            place(subject, x, -height * (mobile ? .255 : .31), 1, 0, 0, insideAlpha * ease(.49, .575, p) * visibility);
        });
        var front = project(110, camera);
        field.style.transform = 'scale(' + front.scale.toFixed(4) + ')';
        field.style.opacity = (front.alpha * (1 - ease(.24, .34, p))).toFixed(3);
        grid.style.transform = 'scale(' + (1 + dive * 3).toFixed(4) + ')';
        grid.style.opacity = (1 - dive * .65).toFixed(3);
        rings.forEach(function (ring, i) {
            var depth = project(i * 510 + 40, camera);
            ring.style.transform = 'translate(-50%, -50%) scale(' + (depth.scale * [.75, .46, .28][i]).toFixed(4) + ')';
            ring.style.opacity = (depth.alpha * ease(.025, .08, p) * (1 - ease(.28, .39, p))).toFixed(3);
        });
        cue.style.opacity = (1 - ease(0, .10, p)).toFixed(3);
        var chapter = p < .295 ? 0 : p < .90 ? 1 : 2;
        if (chapter !== activeChapter) {
            chapters.forEach(function (button, i) { if (i === chapter) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current'); });
            activeChapter = chapter;
        }
        var boundaries = [0, .295, .90, 1];
        chapters.forEach(function (button, i) { button.style.setProperty('--chapter-fill', clamp((p - boundaries[i]) / (boundaries[i + 1] - boundaries[i])).toFixed(3)); });
    }
    function updateTarget() {
        target = reduced.matches ? 0 : clamp((window.scrollY - start) / distance);
        var bounds = viewport.getBoundingClientRect();
        document.body.classList.toggle('evo-in-scene', bounds.top <= 70 && bounds.bottom > 70);
    }
    function tick(time) {
        var elapsed = previousTime ? Math.min(time - previousTime, 64) : 16;
        previousTime = time;
        progress += (target - progress) * (1 - Math.exp(-elapsed / 85));
        if (Math.abs(target - progress) < .00015) progress = target;
        draw(progress);
        if (progress !== target) frame = requestAnimationFrame(tick); else { frame = 0; previousTime = 0; }
    }
    function onScroll() { updateTarget(); if (!frame && !reduced.matches) frame = requestAnimationFrame(tick); }
    function goTo(p) { window.scrollTo({ top: start + distance * p, behavior: reduced.matches ? 'auto' : 'smooth' }); }
    chapters.forEach(function (button, i) { button.addEventListener('click', function () { goTo([0, .37, 1][i]); }); });
    enter.addEventListener('click', function (event) { if (!reduced.matches) { event.preventDefault(); goTo(.37); } });
    function configure() {
        scene.classList.toggle('evo-enhanced', !reduced.matches);
        enter.href = reduced.matches ? '#intro' : '#evoInside';
        enter.firstChild.textContent = reduced.matches ? 'О платформе ' : 'Погрузиться ';
        if (frame) cancelAnimationFrame(frame);
        frame = 0; previousTime = 0; measure();
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', measure, { passive: true });
    window.addEventListener('pageshow', measure);
    if (reduced.addEventListener) reduced.addEventListener('change', configure);
    configure();
})();
