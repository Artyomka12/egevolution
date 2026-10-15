"""Admin-only routes. Import/registration never opens or initializes a database."""
from pathlib import Path
import hashlib
import sqlite3
from core.content_store import ContentError
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from .bank import Bank, safe_path
from . import media, service, attempts, student_views, repository


def register_admin(app, database_factory, bank_root, media_root):
    bp = Blueprint('thematic_admin', __name__)
    app.config.setdefault('THEMATIC_BANK_ROOT', str(bank_root))
    app.config.setdefault('THEMATIC_MEDIA_ROOT', str(media_root))

    @bp.before_request
    def require_admin():
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify(error='Требуется вход', code='UNAUTHORIZED'), 401
            return redirect(url_for('login', next=request.path))
        db = database_factory()
        db.isolation_level = None
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA recursive_triggers=ON')
        g.thematic_db = db
        user = db.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or user[0] != 1:
            return jsonify(error='Доступ только для администратора', code='FORBIDDEN'), 403
        try:
            row = db.execute("SELECT checksum FROM schema_migrations WHERE version='003_json_content.sql'").fetchone()
            expected = hashlib.sha256((Path(__file__).resolve().parents[2] / 'migrations/003_json_content.sql').read_bytes()).hexdigest()
            if row is None or row[0] != expected:
                raise ValueError('schema')
        except (sqlite3.OperationalError, ValueError):
            message = 'Раздел недоступен: схема тематических вариантов не подготовлена. Миграция автоматически не запускается.'
            if request.path.startswith('/api/'):
                return jsonify(error=message, code='SCHEMA_REQUIRED'), 503
            return render_template('admin/thematic/unavailable.html', message=message), 503
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify(error='Запрос слишком большой'), 413
        g.thematic_bank = Bank(app.config['THEMATIC_BANK_ROOT'])
        repository.row(db, 'catalog_state', 1)

    @bp.teardown_request
    def close_db(error):
        db = g.pop('thematic_db', None)
        if db is not None:
            db.close()

    @bp.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @bp.errorhandler(service.Conflict)
    def conflict(error):
        return jsonify(error=str(error), code='CONFLICT'), 409

    @bp.errorhandler(attempts.AttemptError)
    def attempt_error(error):
        return jsonify(error=str(error), code=error.code, **error.details), error.status

    @bp.errorhandler(ContentError)
    def unavailable_content(error):
        return jsonify(error='Учебные материалы временно недоступны', code='CONTENT_UNAVAILABLE'), 503

    @bp.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error), code='INVALID_INPUT'), 400

    @bp.errorhandler(LookupError)
    def missing(error):
        return jsonify(error='Вариант или задача недоступны', code='NOT_FOUND'), 404

    @bp.errorhandler(OSError)
    def storage(error):
        return jsonify(error='Не удалось прочитать банк или сохранить закрытые материалы. Публикация не изменена.', code='STORAGE_ERROR'), 503

    @bp.errorhandler(sqlite3.Error)
    def database_error(error):
        return jsonify(error='База недоступна или операция конфликтует с текущим состоянием. Обновите страницу и повторите.', code='DATABASE_ERROR'), 503

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Ожидается JSON-объект')
        return value

    @bp.get('/admin/thematic-variants')
    def index():
        return render_template('admin/thematic/index.html')

    @bp.get('/admin/thematic-variants/new')
    @bp.get('/admin/thematic-variants/<int:ident>/edit')
    def editor(ident=None):
        if ident is not None:
            service.variant(g.thematic_db, ident)
        return render_template('admin/thematic/editor.html', variant_id=ident or '')

    @bp.route('/api/admin/thematic-variants', methods=['GET', 'POST'])
    def variants():
        if request.method == 'POST':
            return jsonify(service.create(g.thematic_db, g.thematic_bank, body(), session['user_id']))
        return jsonify(service.catalog(g.thematic_db))

    @bp.route('/api/admin/thematic-variants/<int:ident>/draft', methods=['GET', 'PUT'])
    def draft(ident):
        if request.method == 'PUT':
            return jsonify(service.save(g.thematic_db, g.thematic_bank, ident, body(), session['user_id']))
        data = service.draft(g.thematic_db, ident)
        tasks = []
        for ref in data['document']['items']:
            try:
                task = g.thematic_bank.task(ref['source_task_num'], ref['source_task_id'])
                tasks.append(g.thematic_bank.dto(ref['source_task_num'], task))
            except (OSError, ValueError, KeyError):
                tasks.append(dict(ref, title='Исходная задача недоступна — удалите её из черновика', description_html=[], materials=[]))
        return jsonify(dict(data, tasks=tasks))

    @bp.post('/api/admin/thematic-variants/<int:ident>/publish')
    def publish(ident):
        return jsonify(service.publish(g.thematic_db, g.thematic_bank, app.config['THEMATIC_MEDIA_ROOT'], ident, body(), session['user_id']))

    @bp.patch('/api/admin/thematic-variants/<int:ident>/visibility')
    def visibility(ident):
        return jsonify(service.visibility(g.thematic_db, ident, body(), session['user_id']))

    @bp.put('/api/admin/thematic-variants/order')
    def order():
        return jsonify(service.reorder(g.thematic_db, body()))

    @bp.delete('/api/admin/thematic-variants/<int:ident>')
    def delete(ident):
        return jsonify(attempts.delete_variant(g.thematic_db, ident, body(), session['user_id']))

    @bp.get('/admin/user/<int:user_id>/thematic-attempt/<int:ident>')
    def student_result(user_id, ident):
        data = student_views.finished_result(g.thematic_db, ident, user_id, admin=True)
        return render_template('thematic/result.html', result=data, answer_text=student_views.answer_text, admin_view=True)

    @bp.get('/api/admin/thematic-bank/<int:number>')
    def bank(number):
        tasks = g.thematic_bank.tasks(number)
        return jsonify(tasks=[g.thematic_bank.dto(number, task) for task in tasks])

    @bp.get('/api/admin/thematic-bank/<int:number>/<int:ident>/media/<role>/<int:position>')
    def bank_media(number, ident, role, position):
        task = g.thematic_bank.task(number, ident)
        for item in g.thematic_bank.materials(number, task):
            if item['role'] == role and item['position'] == position:
                _, info = media.read_material(item['path'], role == 'condition')
                return send_file(item['path'], mimetype=info['mime_type'], as_attachment=role != 'condition', download_name=info['original_name'])
        abort(404)

    @bp.get('/api/admin/thematic-variants/<int:ident>/media/<int:media_id>')
    def version_media(ident, media_id):
        db = g.thematic_db
        row = next((material for version in repository.rows(db, 'versions')
                    if version['variant_id'] == ident and version['sealed'] == 1
                    for material in [repository.media_for_version(db, version['id'], media_id)] if material), None)
        if row is None:
            abort(404)
        path = safe_path(app.config['THEMATIC_MEDIA_ROOT'], row['storage_key'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Повреждена копия материала')
        return send_file(path, mimetype=row['mime_type'], as_attachment=row['role'] != 'condition', download_name=row['original_name'])

    app.register_blueprint(bp)
