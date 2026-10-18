"""HTTP infrastructure for the tests feature; registration has no DB effects."""
import hashlib
from pathlib import Path
import sqlite3
import uuid

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException
from core.content_store import ContentError, store_for


def error_response(code, message, status, *, field_errors=None, details=None):
    payload = {"error": {"code": code, "message": message},
               "request_id": getattr(g, "tests_request_id", uuid.uuid4().hex)}
    if field_errors:
        payload["field_errors"] = field_errors
    if details:
        payload.update(details)
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def json_body():
    from features.tests.errors import TestsError
    if not request.is_json:
        raise TestsError("BAD_JSON", 415, "Ожидается JSON.")
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise TestsError("BAD_JSON", 400, "Ожидается JSON-объект.")
    return value


def configure_blueprint(bp, app, database_factory, *, admin=False):
    """Current-user guards and connection lifecycle, shared by both interfaces."""
    from features.tests.errors import TestsError
    from features.tests.validation import ValidationError
    from flask_wtf.csrf import CSRFError

    @bp.errorhandler(CSRFError)
    def csrf_error(error):
        ident = session.get("user_id")
        if type(ident) is not int or ident <= 0:
            return error_response("AUTH_REQUIRED", "Требуется вход.", 401)
        # Return a bounded diagnostic, never the token, cookie or raw request.
        reason = {
            "The CSRF token has expired.": "expired",
            "The CSRF token is missing.": "missing",
            "The CSRF session token is missing.": "session_missing",
            "The CSRF token is invalid.": "invalid",
            "The CSRF tokens do not match.": "mismatch",
        }.get(error.description, "invalid")
        return error_response("CSRF_FAILED", "Не удалось подтвердить защиту запроса. Ваш ввод остаётся на странице. Повторите сохранение.",
                              400, details={"csrf_reason": reason})

    @bp.before_request
    def authorize():
        g.tests_request_id = uuid.uuid4().hex
        ident = session.get("user_id")
        if type(ident) is not int or ident <= 0:
            if not request.path.startswith("/api/"):
                return redirect(url_for("login", next=request.path))
            return error_response("AUTH_REQUIRED", "Требуется вход.", 401)
        db = database_factory()
        g.tests_db = db
        db.isolation_level = None
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA recursive_triggers=ON")
        db.execute("PRAGMA busy_timeout=5000")
        user = db.execute("SELECT id,is_admin FROM users WHERE id=?", (ident,)).fetchone()
        if not user:
            return error_response("AUTH_REQUIRED", "Требуется вход.", 401)
        g.tests_user = dict(user)
        if admin and user["is_admin"] != 1:
            return error_response("ADMIN_REQUIRED", "Требуются права администратора.", 403)
        try:
            row = db.execute("SELECT checksum FROM schema_migrations WHERE version='003_json_content.sql'").fetchone()
            expected = hashlib.sha256((Path(__file__).resolve().parents[1] /
                                       "migrations/003_json_content.sql").read_bytes()).hexdigest()
            if row is None or row[0] != expected:
                raise ValueError("schema")
            store_for(db, 'tests').get('test_catalog_state', 1)
        except (sqlite3.OperationalError, ValueError, OSError):
            return error_response("SCHEMA_REQUIRED", "Раздел тестов пока недоступен.", 503)
        if admin and request.method not in {"GET", "HEAD", "OPTIONS"} and not app.config.get("TESTS_ADMIN_WRITES_ENABLED", True):
            return error_response("TEMPORARILY_UNAVAILABLE", "Изменения тестов временно недоступны.", 503)

    @bp.teardown_request
    def close_database(error):
        db = g.pop("tests_db", None)
        if db is not None:
            db.close()

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @bp.errorhandler(TestsError)
    def domain_error(error):
        return error_response(error.code, str(error), error.status,
                              details=getattr(error, "details", None))

    @bp.errorhandler(ContentError)
    def content_error(error):
        return error_response('CONTENT_UNAVAILABLE', 'Учебные материалы временно недоступны.', 503)

    @bp.errorhandler(ValidationError)
    def invalid(error):
        return error_response(error.code, error.message, 422, field_errors=error.field_errors)

    @bp.errorhandler(sqlite3.Error)
    def database_error(error):
        busy = isinstance(error, sqlite3.OperationalError) and any(
            word in str(error).lower() for word in ("locked", "busy"))
        return error_response("DB_BUSY" if busy else "TEMPORARILY_UNAVAILABLE",
                              "Операция временно недоступна. Повторите запрос.", 503)

    @bp.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error_response("BAD_REQUEST", "Запрос не может быть обработан.", error.code)
        # Never expose SQL, answer bodies, tokens, paths or tracebacks to clients.
        return error_response("INTERNAL_ERROR", "Не удалось выполнить операцию.", 500)
