"""Student routes with current-account, ownership, latest and writer guards."""
from flask import Blueprint, g, jsonify, render_template, redirect, request, send_file

from core.tests_http import configure_blueprint, json_body
from . import media, service
from .errors import TestsError


def register_student(app, database_factory):
    app.config.setdefault("TESTS_STARTS_ENABLED", False)
    app.config.setdefault("TESTS_CATALOG_ENABLED", True)
    bp = Blueprint("tests_student", __name__)
    configure_blueprint(bp, app, database_factory)

    def actor():
        return g.tests_user["id"]

    def token():
        return request.headers.get("X-Test-Writer-Token")

    def catalog_available():
        if not app.config["TESTS_CATALOG_ENABLED"]:
            raise TestsError("TEMPORARILY_UNAVAILABLE", 503, "Каталог тестов временно недоступен.")

    @bp.get("/tests")
    def index():
        catalog_available()
        return render_template("tests/index.html")

    @bp.get("/tests/attempts/<int:attempt_id>")
    def attempt_page(attempt_id):
        data = service.get_attempt(g.tests_db, attempt_id, actor())
        if data["state"] != "active":
            return redirect(data["result_url"])
        return render_template("tests/attempt.html", attempt_id=attempt_id, attempt=data)

    @bp.get("/tests/attempts/<int:attempt_id>/result")
    def result_page(attempt_id):
        data = service.get_attempt(g.tests_db, attempt_id, actor())
        if data["state"] == "active":
            return redirect(data["attempt_url"])
        result = service.get_result(g.tests_db, attempt_id, actor())
        return render_template("tests/result.html", attempt_id=attempt_id, result=result)

    @bp.get("/api/tests")
    def catalog():
        catalog_available()
        return jsonify(service.catalog(g.tests_db, actor(), starts_enabled=app.config["TESTS_STARTS_ENABLED"]))

    @bp.get("/api/tests/<int:test_id>")
    def detail(test_id):
        catalog_available()
        return jsonify(service.test_detail(g.tests_db, test_id, actor(), starts_enabled=app.config["TESTS_STARTS_ENABLED"]))

    @bp.post("/api/tests/<int:test_id>/attempts")
    def start(test_id):
        data = service.start_attempt(g.tests_db, test_id, json_body(), actor(), starts_enabled=app.config["TESTS_STARTS_ENABLED"])
        created = data.pop("_created")
        return jsonify(data), 201 if created else 200

    @bp.get("/api/tests/attempts/<int:attempt_id>")
    def attempt(attempt_id):
        return jsonify(service.get_attempt(g.tests_db, attempt_id, actor()))

    @bp.get("/api/tests/attempts/<int:attempt_id>/result")
    def result(attempt_id):
        return jsonify(service.get_result(g.tests_db, attempt_id, actor()))

    @bp.post("/api/tests/attempts/<int:attempt_id>/claim")
    def claim(attempt_id):
        return jsonify(service.claim_attempt(g.tests_db, attempt_id, json_body(), actor()))

    @bp.post("/api/tests/attempts/<int:attempt_id>/heartbeat")
    def heartbeat(attempt_id):
        return jsonify(service.heartbeat(g.tests_db, attempt_id, json_body(), actor(), token()))

    @bp.put("/api/tests/attempts/<int:attempt_id>/answers/<int:question_id>")
    def answer(attempt_id, question_id):
        return jsonify(service.save_answer(g.tests_db, attempt_id, question_id, json_body(), actor(), token()))

    @bp.post("/api/tests/attempts/<int:attempt_id>/submit")
    def submit(attempt_id):
        return jsonify(service.submit_attempt(g.tests_db, attempt_id, json_body(), actor(), token()))

    @bp.get("/tests/attempts/<int:attempt_id>/media/<int:media_id>")
    def image(attempt_id, media_id):
        stored = service.get_student_media(g.tests_db, attempt_id, media_id, actor())
        response = send_file(media.resolve_media_path(app.config["TESTS_MEDIA_ROOT"], stored["storage_key"]),
                             mimetype=stored["mime_type"], conditional=False, etag=False, max_age=0)
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    app.register_blueprint(bp)
    return bp
