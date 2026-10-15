"""Student pages and owner-only APIs for catalog, attempts, results and media."""
from pathlib import Path
from io import BytesIO
import hashlib
import sqlite3
from core.content_store import ContentError
from flask import Blueprint, g, jsonify, request, session, send_file, render_template, redirect, url_for
from . import attempts, repository, student_views
from .bank import safe_path


def register_student(app, database_factory):
    bp = Blueprint('thematic_student', __name__)

    @bp.before_request
    def authorize():
        if 'user_id' not in session:
            if not request.path.startswith('/api/'):
                return redirect(url_for('login', next=request.path))
            return jsonify(error='Требуется вход', code='UNAUTHORIZED'), 401
        db = database_factory()
        db.isolation_level = None
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA recursive_triggers=ON')
        g.thematic_attempt_db = db
        if not db.execute('SELECT id FROM users WHERE id=?', (session['user_id'],)).fetchone():
            return jsonify(error='Требуется вход', code='UNAUTHORIZED'), 401
        try:
            row = db.execute("SELECT checksum FROM schema_migrations WHERE version='003_json_content.sql'").fetchone()
            expected = hashlib.sha256((Path(__file__).resolve().parents[2] / 'migrations/003_json_content.sql').read_bytes()).hexdigest()
            if row is None or row[0] != expected:
                raise ValueError('schema')
        except (sqlite3.OperationalError, ValueError):
            return jsonify(error='Раздел не подготовлен', code='SCHEMA_REQUIRED'), 503
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify(error='Запрос слишком большой', code='REQUEST_TOO_LARGE'), 413

    @bp.teardown_request
    def close_db(error):
        db = g.pop('thematic_attempt_db', None)
        if db is not None:
            db.close()

    @bp.after_request
    def private(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
            if response.mimetype == 'text/html' else "default-src 'none'; frame-ancestors 'none'; sandbox")
        return response

    @bp.errorhandler(attempts.AttemptError)
    def attempt_error(error):
        if not request.path.startswith('/api/') and '/media/' not in request.path:
            return render_template('thematic/unavailable.html', message=str(error)), error.status
        return jsonify(error=str(error), code=error.code, **error.details), error.status

    @bp.errorhandler(repository.Conflict)
    def conflict(error):
        return jsonify(error=str(error), code='CONFLICT'), 409

    @bp.errorhandler(ContentError)
    def unavailable_content(error):
        return jsonify(error='Учебные материалы временно недоступны', code='CONTENT_UNAVAILABLE'), 503

    @bp.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error='Некорректный запрос или данные попытки', code='INVALID_INPUT'), 400

    @bp.errorhandler(sqlite3.Error)
    def unavailable(error):
        return jsonify(error='База занята или недоступна. Повторите запрос с прежним ключом.', code='DATABASE_UNAVAILABLE'), 503

    @bp.errorhandler(OSError)
    def missing_file(error):
        return jsonify(error='Материал недоступен', code='MEDIA_UNAVAILABLE'), 503

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('JSON object required')
        return value

    @bp.post('/api/thematic-variants/<int:ident>/attempts')
    def start(ident):
        return jsonify(attempts.start(g.thematic_attempt_db, ident, body(), session['user_id']))

    @bp.get('/api/thematic-attempts/<int:ident>')
    def view(ident):
        data = attempts.view(g.thematic_attempt_db, ident, session['user_id'])
        data['questions'] = [student_views.present_question(q) for q in data['questions']]
        return jsonify(data)

    @bp.get('/api/thematic-variants')
    def catalog():
        return jsonify(variants=student_views.catalog(g.thematic_attempt_db, session['user_id']))

    @bp.get('/thematic-variants/<int:ident>/solve')
    def solve(ident):
        db = g.thematic_attempt_db
        parent = repository.row(db, 'variants', ident)
        attempts.available(parent)
        return render_template('thematic/solve.html', variant_id=ident)

    @bp.get('/api/thematic-attempts/<int:ident>/result')
    def result_api(ident):
        return jsonify(student_views.finished_result(g.thematic_attempt_db, ident, session['user_id']))

    @bp.get('/thematic-attempts/<int:ident>/result')
    def result_page(ident):
        data = student_views.finished_result(g.thematic_attempt_db, ident, session['user_id'])
        return render_template('thematic/result.html', result=data, answer_text=student_views.answer_text, admin_view=False)

    @bp.put('/api/thematic-attempts/<int:ident>/answers/<int:item_id>')
    def save(ident, item_id):
        return jsonify(attempts.mutate(g.thematic_attempt_db, ident, item_id, body(), session['user_id']))

    @bp.post('/api/thematic-attempts/<int:ident>/check/<int:item_id>')
    def check(ident, item_id):
        return jsonify(attempts.mutate(g.thematic_attempt_db, ident, item_id, body(), session['user_id'], check=True))

    @bp.post('/api/thematic-attempts/<int:ident>/submit')
    def finish(ident):
        return jsonify(attempts.finish(g.thematic_attempt_db, ident, body(), session['user_id']))

    @bp.get('/thematic-attempts/<int:ident>/media/<int:media_id>')
    def material(ident, media_id):
        db = g.thematic_attempt_db
        with repository.transaction(db):
            attempt = attempts.owned(db, ident, session['user_id'])
            if attempt['state'] == 'active':
                attempts.active(db, attempt)
            row = repository.media_for_version(db, attempt['version_id'], media_id, finished=attempt['state'] == 'finished')
            if row is None:
                attempts.fail('NOT_FOUND', 404, 'Материал не найден')
            metadata = dict(row)
        path = safe_path(app.config['THEMATIC_MEDIA_ROOT'], metadata['storage_key'])
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != metadata['sha256']:
            attempts.fail('MEDIA_UNAVAILABLE', 503, 'Материал недоступен')
        return send_file(BytesIO(data), mimetype=metadata['mime_type'], as_attachment=metadata['role'] != 'condition', download_name=metadata['original_name'])

    app.register_blueprint(bp)
