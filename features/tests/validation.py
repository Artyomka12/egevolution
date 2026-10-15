"""Pure test input validation. No database or application imports."""
from copy import deepcopy
import hashlib
import json


class ValidationError(ValueError):
    code = "VALIDATION_ERROR"
    message = "Проверьте заполнение полей."

    def __init__(self, field_errors):
        self.field_errors = dict(field_errors)
        super().__init__(self.message)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_transport(text):
    """Apply the approved LF convention; preserve spaces, case and Unicode."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


_DOCUMENT_FIELDS = frozenset(("title", "description", "time_limit_seconds",
                              "attempt_limit", "show_correct_answers", "questions"))
_QUESTION_FIELDS = frozenset(("title", "prompt_text", "code_text", "question_type",
                              "free_input_mode", "grading_mode", "media_id",
                              "options", "accepted_answers"))
_OPTION_FIELDS = frozenset(("text", "is_correct"))
_QUESTION_TYPES = ("single_choice", "multiple_choice", "free_text")


def _unknown_fields(value, allowed, path, errors):
    if any(key not in allowed for key in value):
        errors[path] = "Неизвестные поля не допускаются."


def _text(value, path, errors, *, nullable=False, lf=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        errors[path] = "Ожидается строка."
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        errors[path] = "Некорректная строка Unicode."
    return normalize_transport(value) if lf else value


def _positive_integer(value, path, errors, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not int or value <= 0:
        errors[path] = "Ожидается положительное целое число."


def validate_draft(document):
    """Return detached shaped input; missing educational content is allowed.

    Unknown keys, including published IDs, are rejected. No unapproved upper
    caps apply. Media ownership/readiness belongs to the database transaction.
    """
    if not isinstance(document, dict):
        raise ValidationError({"document": "Ожидается объект."})
    errors = {}
    _unknown_fields(document, _DOCUMENT_FIELDS, "document", errors)
    result = {
        "title": document.get("title", ""),
        "description": document.get("description", ""),
        "time_limit_seconds": document.get("time_limit_seconds"),
        "attempt_limit": document.get("attempt_limit"),
        "show_correct_answers": document.get("show_correct_answers", False),
        "questions": [],
    }
    for key in ("title", "description"):
        result[key] = _text(result[key], key, errors, lf=True)
    _positive_integer(result["time_limit_seconds"], "time_limit_seconds", errors, nullable=True)
    _positive_integer(result["attempt_limit"], "attempt_limit", errors, nullable=True)
    if type(result["show_correct_answers"]) is not bool:
        errors["show_correct_answers"] = "Ожидается логическое значение."
    questions = document.get("questions", [])
    if not isinstance(questions, list):
        errors["questions"] = "Ожидается массив вопросов."
        questions = []
    for index, raw in enumerate(questions):
        path = f"questions.{index}"
        if not isinstance(raw, dict):
            errors[path] = "Ожидается объект вопроса."
            continue
        _unknown_fields(raw, _QUESTION_FIELDS, path, errors)
        question_type = raw.get("question_type", "single_choice")
        question = {
            "title": raw.get("title", ""), "prompt_text": raw.get("prompt_text", ""),
            "code_text": raw.get("code_text"), "question_type": question_type,
            "free_input_mode": raw.get("free_input_mode", "singleline" if question_type == "free_text" else None),
            "grading_mode": raw.get("grading_mode", "auto"),
            "media_id": raw.get("media_id"), "options": [], "accepted_answers": [],
        }
        for key in ("title", "prompt_text", "code_text"):
            question[key] = _text(question[key], f"{path}.{key}", errors,
                                  nullable=key == "code_text", lf=True)
        if question_type not in _QUESTION_TYPES:
            errors[f"{path}.question_type"] = "Неизвестный тип вопроса."
        if question["free_input_mode"] not in (None, "singleline", "multiline"):
            errors[f"{path}.free_input_mode"] = "Неизвестный формат ввода."
        if question["grading_mode"] not in ("auto", "manual"):
            errors[f"{path}.grading_mode"] = "Неизвестный режим проверки."
        _positive_integer(question["media_id"], f"{path}.media_id", errors, nullable=True)
        options = raw.get("options", [])
        if not isinstance(options, list):
            errors[f"{path}.options"] = "Ожидается массив вариантов."
            options = []
        for option_index, option in enumerate(options):
            option_path = f"{path}.options.{option_index}"
            if not isinstance(option, dict):
                errors[option_path] = "Ожидается объект варианта."
                continue
            _unknown_fields(option, _OPTION_FIELDS, option_path, errors)
            text = _text(option.get("text", ""), f"{option_path}.text", errors, lf=True)
            correct = option.get("is_correct", False)
            if type(correct) is not bool:
                errors[f"{option_path}.is_correct"] = "Ожидается логическое значение."
            question["options"].append({"text": text, "is_correct": correct})
        accepted = raw.get("accepted_answers", [])
        if not isinstance(accepted, list):
            errors[f"{path}.accepted_answers"] = "Ожидается массив строк."
            accepted = []
        question["accepted_answers"] = [
            _text(value, f"{path}.accepted_answers.{i}", errors, lf=True)
            for i, value in enumerate(accepted)
        ]
        result["questions"].append(question)
    if errors:
        raise ValidationError(errors)
    return deepcopy(result)


def validate_publication(document):
    """Return a publishable document, without mutating the draft."""
    result = validate_draft(document)
    errors = {}
    if not result["title"].strip():
        errors["title"] = "Укажите название теста."
    _positive_integer(result["time_limit_seconds"], "time_limit_seconds", errors)
    if not result["questions"]:
        errors["questions"] = "Добавьте хотя бы один вопрос."
    for index, question in enumerate(result["questions"]):
        path = f"questions.{index}"
        for key in ("title", "prompt_text"):
            if not question[key].strip():
                errors[f"{path}.{key}"] = "Заполните обязательное поле."
        if question["question_type"] == "free_text":
            if question["free_input_mode"] is None:
                errors[f"{path}.free_input_mode"] = "Выберите формат ввода."
            if question["options"]:
                errors[f"{path}.options"] = "Свободный вопрос не содержит вариантов выбора."
            if question["grading_mode"] == "auto" and not question["accepted_answers"]:
                errors[f"{path}.accepted_answers"] = "Добавьте допустимую строку ответа."
            for answer_index, value in enumerate(question["accepted_answers"]):
                if value == "":
                    errors[f"{path}.accepted_answers.{answer_index}"] = "Пустой эталон недопустим."
        else:
            if question["free_input_mode"] is not None:
                errors[f"{path}.free_input_mode"] = "Формат ввода применяется только к свободному ответу."
            if question["grading_mode"] != "auto":
                errors[f"{path}.grading_mode"] = "Варианты выбора проверяются автоматически."
            if question["accepted_answers"]:
                errors[f"{path}.accepted_answers"] = "Варианты выбора не содержат строк-эталонов."
            if len(question["options"]) < 2:
                errors[f"{path}.options"] = "Добавьте минимум два варианта."
            for option_index, option in enumerate(question["options"]):
                if not option["text"].strip():
                    errors[f"{path}.options.{option_index}.text"] = "Укажите текст варианта."
            count = sum(option["is_correct"] for option in question["options"])
            if question["question_type"] == "single_choice" and count != 1:
                errors[f"{path}.options"] = "Отметьте ровно один правильный вариант."
            if question["question_type"] == "multiple_choice" and count == 0:
                errors[f"{path}.options"] = "Отметьте хотя бы один правильный вариант."
    if errors:
        raise ValidationError(errors)
    return result


def validate_answer(question, answer):
    """Return a detached answer validated against a server-loaded question.

    Choice options use published integer IDs. No correctness is computed here.
    """
    question_type = question.get("question_type")
    if question_type == "free_text":
        errors = {}
        result = _text(answer, "answer", errors, lf=True)
        if errors:
            raise ValidationError(errors)
        return result
    if question_type not in ("single_choice", "multiple_choice"):
        raise ValidationError({"answer": "Неизвестный тип вопроса."})
    own_ids = {option["id"] for option in question.get("options", [])
               if type(option.get("id")) is int and option["id"] > 0}
    if question_type == "single_choice":
        if answer is None:
            return None
        if type(answer) is not int or answer not in own_ids:
            raise ValidationError({"answer": "Выберите вариант этого вопроса."})
        return answer
    if (not isinstance(answer, list)
            or any(type(value) is not int or value not in own_ids for value in answer)
            or len(answer) != len(set(answer))):
        raise ValidationError({"answer": "Ожидается массив уникальных вариантов этого вопроса."})
    return list(answer)
