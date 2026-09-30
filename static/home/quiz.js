/* Homepage preparation quiz and application form. */
(function () {
    'use strict';
    var root = document.getElementById('quiz');
    if (!root) return;
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
        const easyQuestions = [
            {
                text: 'Сколько бит требуется для кодирования 256 различных символов?',
                options: ['6', '7', '8', '9'],
                correct: '8',
                explain: '256 = 2<sup>8</sup>, значит нужно 8 бит.'
            },
            {
                text: 'Переведите число 12 в двоичную систему счисления.',
                options: ['1100', '1010', '1001', '1110'],
                correct: '1100',
                explain: '12 = 8 + 4 = 2<sup>3</sup> + 2<sup>2</sup>, то есть 1100.'
            },
            {
                text: 'Чему равно логическое «1 И 0» (конъюнкция)?',
                options: ['0', '1', 'неопределено', 'ошибка'],
                correct: '0',
                explain: 'Конъюнкция истинна только тогда, когда истинны оба операнда — здесь один из них 0.'
            },
            {
                text: 'Сколько бит нужно для кодирования одного пикселя при палитре из 16 цветов?',
                options: ['2', '4', '8', '16'],
                correct: '4',
                explain: '16 = 2<sup>4</sup>, значит нужно 4 бита на пиксель.'
            },
            {
                text: 'Чему равно 5 // 2 в Python (целочисленное деление)?',
                options: ['1', '2', '2.5', '3'],
                correct: '2',
                explain: '// отбрасывает дробную часть: 5 / 2 = 2.5, значит результат — 2.'
            },
            {
                text: 'Сколько байт в 1 килобайте (по стандарту ЕГЭ, 1 Кбайт = 2¹⁰ байт)?',
                options: ['1000', '1024', '1048576', '100'],
                correct: '1024',
                explain: '1 Кбайт = 2<sup>10</sup> байт = 1024 байта.'
            }
        ];

        const hardQuestion = {
            text: 'Существует ли алгоритм, который для ЛЮБОЙ программы и любых входных данных всегда правильно определит, завершится она или зависнет?',
            options: ['Да', 'Нет', 'Только для коротких программ', 'Только на суперкомпьютере'],
            correct: 'Нет',
            explain: 'Это проблема остановки — Алан Тьюринг доказал, что такого универсального алгоритма не существует.'
        };
    var easyIndex = 0, hard = false, checked = false;
    var answers = new Array(easyQuestions.length + 1).fill(null);
    var workspace = document.getElementById('quizWorkspace');
    var questionStage = document.getElementById('quizQuestionStage');
    var feedback = document.getElementById('quizFeedback');
    var checkButton = document.getElementById('quizCheck');
    var nextButton = document.getElementById('quizNext');
    var options = document.getElementById('quizOptions');
    var stageIds = ['quizQuestionStage', 'quizReadinessStage', 'quizFinalStage'];
    function progress(step, caption) {
        document.getElementById('quizProgress').value = step;
        document.getElementById('quizCaption').textContent = caption;
        document.getElementById('quizStageNumber').textContent = String(step).padStart(2, '0') + ' / 09';
    }
    function reveal(stage, focus) {
        stageIds.forEach(function (id) { document.getElementById(id).hidden = id !== stage.id; });
        stage.getAnimations().forEach(function (animation) { animation.cancel(); });
        if (!reduced.matches) stage.animate([{ opacity: 0, transform: 'translateY(12px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 320, easing: 'ease-out' });
        if (focus) {
            stage.querySelector('legend, h3').focus({ preventScroll: true });
            var top = workspace.getBoundingClientRect().top;
            if (top < 85 || top > window.innerHeight * .45) workspace.scrollIntoView({ block: 'start', behavior: reduced.matches ? 'instant' : 'smooth' });
        }
    }
    function renderQuestion(focus) {
        var question = hard ? hardQuestion : easyQuestions[easyIndex];
        document.getElementById('quizQuestion').textContent = question.text;
        options.replaceChildren();
        question.options.forEach(function (value) {
            var label = document.createElement('label');
            var input = document.createElement('input'); input.type = 'radio'; input.name = 'quiz_answer'; input.value = value;
            var text = document.createElement('span'); text.textContent = value;
            label.append(input, text); options.append(label);
        });
        checked = false; feedback.hidden = true; feedback.textContent = '';
        checkButton.hidden = false; nextButton.hidden = true;
        nextButton.textContent = hard ? 'Посмотреть маршрут →' : easyIndex === easyQuestions.length - 1 ? 'Оценить готовность →' : 'Следующий вопрос →';
        progress(hard ? 8 : easyIndex + 1, hard ? 'Сложный вопрос' : 'Вопрос ' + (easyIndex + 1) + ' из ' + easyQuestions.length);
        reveal(questionStage, focus);
    }
    checkButton.addEventListener('click', function () {
        if (checked) return;
        var selected = options.querySelector('input:checked');
        feedback.hidden = false;
        if (!selected) {
            feedback.className = 'nh-quiz-feedback'; feedback.textContent = 'Выбери один из вариантов ответа.'; return;
        }
        checked = true;
        var question = hard ? hardQuestion : easyQuestions[easyIndex];
        var correct = selected.value === question.correct;
        answers[hard ? easyQuestions.length : easyIndex] = correct;
        // Explanation HTML comes exclusively from the fixed questions above.
        feedback.className = 'nh-quiz-feedback ' + (correct ? 'is-correct' : 'is-incorrect');
        feedback.innerHTML = '<strong>' + (correct ? 'Верно! ' : 'Правильный ответ: ' + question.correct + '. ') + '</strong>' + question.explain;
        options.querySelectorAll('input').forEach(function (input) { input.disabled = true; });
        checkButton.hidden = true; nextButton.hidden = false;
        nextButton.focus({ preventScroll: true });
    });
    nextButton.addEventListener('click', function () {
        if (!checked) return;
        if (hard) {
            var count = answers.filter(function (answer) { return answer === true; }).length;
            document.getElementById('quizSummary').textContent = 'Правильных ответов: ' + count + ' из 7. На вводном занятии подробнее разберём твой уровень и выберем точку старта.';
            progress(9, 'Твой маршрут готов'); reveal(document.getElementById('quizFinalStage'), true);
        } else if (easyIndex < easyQuestions.length - 1) {
            easyIndex++; renderQuestion(true);
        } else {
            progress(7, 'Оцени свою готовность'); reveal(document.getElementById('quizReadinessStage'), true);
        }
    });
    var readinessStage = document.getElementById('quizReadinessStage');
    var readinessResult = document.getElementById('quizReadinessResult');
    var hardButton = document.getElementById('quizHard');
    document.getElementById('quizReadinessCheck').addEventListener('click', function () {
        var choices = [1, 2, 3].map(function (n) { return root.querySelector('input[name="readiness' + n + '"]:checked'); });
        readinessResult.hidden = false;
        if (choices.some(function (choice) { return !choice; })) {
            readinessResult.textContent = 'Ответь на все три вопроса.'; return;
        }
        var yes = choices.reduce(function (sum, choice) { return sum + Number(choice.value); }, 0);
        readinessResult.textContent = yes <= 1
            ? 'Начальный уровень по самооценке. Начни с базовых уроков и теории, затем переходи к практике.'
            : yes === 2 ? 'Средний уровень по самооценке. Продолжай практику и решай больше полных вариантов.'
            : 'Высокая готовность по самооценке. Продолжай решать варианты и разбирать ошибки.';
        hardButton.hidden = false;
    });
    readinessStage.addEventListener('change', function () { hardButton.hidden = true; readinessResult.hidden = true; });
    hardButton.addEventListener('click', function () { if (!hardButton.hidden) { hard = true; renderQuestion(true); } });
    document.getElementById('quizRestart').addEventListener('click', function () {
        easyIndex = 0; hard = false; answers.fill(null);
        readinessStage.querySelectorAll('input').forEach(function (input) { input.checked = false; });
        readinessResult.hidden = true; hardButton.hidden = true;
        renderQuestion(true);
    });
    var form = document.getElementById('quizApplyForm');
    var contact = document.getElementById('quizContact');
    form.querySelectorAll('input[name="contact_type"]').forEach(function (input) {
        input.addEventListener('change', function () {
            var labels = { telegram: ['Username в Telegram', '@username'], vk: ['Ссылка на профиль VK', 'https://vk.com/username'], max: ['Контакт в MAX', 'Ссылка или номер'] };
            var description = labels[input.value];
            document.getElementById('quizContactLabel').textContent = description[0]; contact.placeholder = description[1];
        });
    });
    var submitting = false;
    var submitButton = document.getElementById('quizSubmit');
    form.addEventListener('submit', function (event) {
        if (submitting) { event.preventDefault(); return; }
        if (!form.checkValidity()) { event.preventDefault(); form.reportValidity(); return; }
        submitting = true; submitButton.disabled = true; submitButton.textContent = 'Отправляем…';
    });
    window.addEventListener('pageshow', function () { submitting = false; submitButton.disabled = false; submitButton.textContent = 'Отправить заявку'; });
})();
