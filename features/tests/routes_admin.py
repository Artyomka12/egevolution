"""Tests administration routes; lifecycle writes belong to the service layer."""
from flask import Blueprint, g, jsonify, render_template, request, send_file
from flask_wtf.csrf import generate_csrf

from core.tests_http import configure_blueprint, json_body
from . import media, service
from .errors import TestsError
from .validation import ValidationError


def register_admin(app, database_factory, media_root):
    app.config.setdefault("TESTS_MEDIA_ROOT", str(media_root))
    bp = Blueprint("tests_admin", __name__)
    configure_blueprint(bp, app, database_factory, admin=True)

    def actor():
        return g.tests_user["id"]

    @bp.get("/api/admin/tests/csrf")
    def refresh_csrf():
        # The blueprint checks the current DB account and admin role first.
        # Custom header prevents cross-origin simple requests; no CORS is enabled.
        if request.headers.get("X-CSRF-Refresh") != "1":
            raise TestsError("BAD_REQUEST", 400, "Ожидается запрос редактора.")
        return jsonify(csrf_token=generate_csrf(), user_id=actor())

    def pagination():
        values = {}
        if set(request.args) - {"offset", "limit"}:
            raise ValidationError({"query": "Неизвестные параметры запроса."})
        for name, default, minimum in (("offset", 0, 0), ("limit", 50, 1)):
            raw = request.args.get(name, str(default))
            if (len(request.args.getlist(name)) > 1 or not raw.isascii()
                    or not raw.isdecimal()):
                raise ValidationError({name: "Ожидается целое число."})
            try:
                number = int(raw)
            except ValueError:
                raise ValidationError({name: "Число выходит за представимый диапазон."}) from None
            if not minimum <= number <= 2**63 - 1:
                raise ValidationError({name: "Число выходит за допустимый диапазон."})
            values[name] = number
        return values

    @bp.get("/admin/tests")
    def index():
        return render_template("admin/tests/index.html")

    @bp.get("/admin/tests/new")
    def new():
        return render_template("admin/tests/editor.html", test_id=None)

    @bp.get("/admin/tests/<int:test_id>/edit")
    def edit(test_id):
        service.get_draft(g.tests_db, test_id, actor())
        return render_template("admin/tests/editor.html", test_id=test_id)

    @bp.get("/admin/tests/attempts/<int:attempt_id>/review")
    def review(attempt_id):
        attempt = service.admin_attempt(g.tests_db, attempt_id, actor())
        return render_template("admin/tests/review.html", attempt_id=attempt_id, attempt=attempt)

    @bp.get("/api/admin/tests/review-queue")
    def review_queue():
        return jsonify(service.review_queue(g.tests_db, actor(), **pagination()))

    @bp.get("/api/admin/tests/attempts/<int:attempt_id>")
    def attempt(attempt_id):
        return jsonify(service.admin_attempt(g.tests_db, attempt_id, actor()))

    @bp.put("/api/admin/tests/attempts/<int:attempt_id>/grades/<int:question_id>")
    def grade(attempt_id, question_id):
        return jsonify(service.grade_attempt_answer(g.tests_db, attempt_id, question_id,
                                                    json_body(), actor()))

    @bp.get("/api/admin/users/<int:user_id>/tests")
    def user_tests(user_id):
        return jsonify(service.user_tests(g.tests_db, user_id, actor()))

    @bp.get("/api/admin/users/<int:user_id>/tests/<int:test_id>/attempts")
    def history(user_id, test_id):
        return jsonify(service.user_test_attempts(g.tests_db, user_id, test_id,
                                                  actor(), **pagination()))

    @bp.post("/api/admin/users/<int:user_id>/tests/<int:test_id>/grants")
    def grant(user_id, test_id):
        return jsonify(service.grant_attempts(g.tests_db, user_id, test_id,
                                              json_body(), actor()))

    @bp.route("/api/admin/tests", methods=["GET", "POST"])
    def catalog():
        if request.method == "GET":
            return jsonify(service.admin_catalog(g.tests_db, actor()))
        return jsonify(service.create_test(g.tests_db, json_body(), actor())), 201

    @bp.route("/api/admin/tests/<int:test_id>/draft", methods=["GET", "PUT"])
    def draft(test_id):
        if request.method == "GET":
            return jsonify(service.get_draft(g.tests_db, test_id, actor()))
        return jsonify(service.save_draft(g.tests_db, test_id, json_body(), actor()))

    @bp.post("/api/admin/tests/<int:test_id>/publish")
    def publish(test_id):
        return jsonify(service.publish_test(g.tests_db, test_id, json_body(), actor()))

    @bp.patch("/api/admin/tests/<int:test_id>/visibility")
    def visibility(test_id):
        return jsonify(service.set_visibility(g.tests_db, test_id, json_body(), actor()))

    @bp.post("/api/admin/tests/<int:test_id>/copy")
    def copy(test_id):
        return jsonify(service.copy_test(g.tests_db, test_id, json_body(), actor())), 201

    @bp.put("/api/admin/tests/order")
    def order():
        return jsonify(service.reorder_tests(g.tests_db, json_body(), actor()))

    @bp.delete("/api/admin/tests/<int:test_id>")
    def delete(test_id):
        return jsonify(service.delete_test(g.tests_db, test_id, json_body(), actor()))

    @bp.post("/api/admin/tests/<int:test_id>/media")
    def upload(test_id):
        if request.mimetype != "multipart/form-data":
            raise TestsError("INVALID_MEDIA_REQUEST", 415, "Ожидается загрузка изображения.")
        if (set(request.files) != {"file"} or len(request.files.getlist("file")) != 1
                or set(request.form) - {"alt_text", "request_key"}
                or any(len(request.form.getlist(key)) != 1 for key in request.form)):
            raise TestsError("INVALID_MEDIA_REQUEST", 422, "Проверьте поля загрузки.")
        # Check existence and current permissions before allocating private media.
        service.get_draft(g.tests_db, test_id, actor())
        root = app.config["TESTS_MEDIA_ROOT"]
        descriptor = media.stage_upload(root, request.files["file"], request.form.get("alt_text", ""))
        try:
            stored = service.add_media(g.tests_db, test_id, descriptor,
                                       {"request_key": request.form.get("request_key")}, actor())
        except Exception:
            media.remove_staged(root, descriptor["storage_key"])
            raise
        if stored["storage_key"] != descriptor["storage_key"]:
            media.remove_staged(root, descriptor["storage_key"])
        return jsonify({"media_id": stored["id"], "url": f"/api/admin/tests/{test_id}/media/{stored['id']}",
                        "alt_text": stored["alt_text"], "width": stored["width"], "height": stored["height"]}), 201

    @bp.get("/api/admin/tests/<int:test_id>/media/<int:media_id>")
    def image(test_id, media_id):
        stored = service.get_admin_media(g.tests_db, test_id, media_id, actor())
        response = send_file(media.resolve_media_path(app.config["TESTS_MEDIA_ROOT"], stored["storage_key"]),
                             mimetype=stored["mime_type"], conditional=False,
                             etag=False, max_age=0)
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    app.register_blueprint(bp)
    return bp
