from flask import Flask, request, render_template, redirect, url_for, send_from_directory, abort, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import zipfile
import shutil
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bravia360-secret-key-change-in-production')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

THUMB_FILENAME = 'thumbnail.jpg'
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}

USERS = {
    'admin': {
        'password_hash': generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'bravia360')),
        'role': 'admin'
    },
    'viewer': {
        'password_hash': generate_password_hash(os.environ.get('VIEWER_PASSWORD', 'bravia123')),
        'role': 'user'
    },
}


# ── helpers ──────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get('user')
        if not user:
            return redirect(url_for('login'))
        if USERS.get(user, {}).get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


def find_thumbnail_in_project(project_path):
    candidates = ['thumbnail.jpg', 'thumbnail.jpeg', 'thumbnail.png', 'thumb.jpg',
                  'preview.jpg', 'preview.png', 'cover.jpg', 'cover.png']
    for name in candidates:
        if os.path.isfile(os.path.join(project_path, name)):
            return name
    for f in os.listdir(project_path):
        ext = os.path.splitext(f)[1].lower()
        if ext in ALLOWED_IMAGE_EXTS:
            return f
    return None


def get_project_meta(project_path):
    """Read optional meta.json for display name; fall back to folder name."""
    meta_path = os.path.join(project_path, 'meta.json')
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def folder_to_display(name):
    return name.replace('-', ' ').replace('_', ' ').title()


# ── routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def home():
    projects = []
    for d in sorted(os.listdir(UPLOAD_FOLDER)):
        path = os.path.join(UPLOAD_FOLDER, d)
        if os.path.isdir(path):
            thumb = find_thumbnail_in_project(path)
            meta = get_project_meta(path)
            projects.append({
                'name': d,
                'display_name': meta.get('display_name') or folder_to_display(d),
                'thumbnail': thumb
            })
    current_user = session.get('user')
    current_role = USERS.get(current_user, {}).get('role') if current_user else None
    return render_template('home.html', projects=projects, current_user=current_user, current_role=current_role)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = USERS.get(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = username
            next_url = request.form.get('next') or url_for('home')
            return redirect(next_url)
        error = 'Usuario ou senha invalidos'
    return render_template('login.html', error=error)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if request.method == 'POST':
        file = request.files.get('file')
        project_name = secure_filename(request.form.get('project_name', '').strip())
        display_name = request.form.get('display_name', '').strip()
        thumbnail_file = request.files.get('thumbnail')
        if not file or not project_name:
            return 'Arquivo e nome sao obrigatorios', 400
        project_path = os.path.join(UPLOAD_FOLDER, project_name)
        os.makedirs(project_path, exist_ok=True)
        # Save and extract ZIP
        zip_path = os.path.join(project_path, 'project.zip')
        file.save(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(project_path)
        os.remove(zip_path)
        # Save thumbnail if provided
        if thumbnail_file and thumbnail_file.filename:
            ext = os.path.splitext(thumbnail_file.filename)[1].lower()
            if ext in ALLOWED_IMAGE_EXTS:
                thumbnail_file.save(os.path.join(project_path, THUMB_FILENAME))
        # Save meta.json with display name
        meta = {'display_name': display_name or folder_to_display(project_name)}
        with open(os.path.join(project_path, 'meta.json'), 'w', encoding='utf-8') as fh:
            json.dump(meta, fh, ensure_ascii=False)
        return redirect(url_for('home'))
    return render_template('register.html')


@app.route('/admin/delete/<project>', methods=['POST'])
@admin_required
def delete_project(project):
    project_path = os.path.join(UPLOAD_FOLDER, project)
    if not os.path.exists(project_path):
        abort(404)
    shutil.rmtree(project_path)
    return redirect(url_for('home'))


@app.route('/admin/rename/<project>', methods=['POST'])
  @admin_required
  def rename_project(project):
      new_name = request.form.get('new_name', '').strip()
      display_name = request.form.get('display_name', '').strip()
      if not new_name or not new_name.replace('-', '').replace('_', '').isalnum():
          return 'Nome invalido', 400
      old_path = os.path.join(UPLOAD_FOLDER, project)
      new_path = os.path.join(UPLOAD_FOLDER, new_name)
      if not os.path.exists(old_path):
          abort(404)
      if new_name != project and os.path.exists(new_path):
          return 'Ja existe um projeto com esse nome', 409
      if new_name != project:
          os.rename(old_path, new_path)
      target_path = new_path if new_name != project else old_path
      meta = get_project_meta(target_path)
      meta['display_name'] = display_name or folder_to_display(new_name)
      with open(os.path.join(target_path, 'meta.json'), 'w', encoding='utf-8') as fh:
          json.dump(meta, fh, ensure_ascii=False)
      return redirect(url_for('home'))


# ── share page (Open Graph for WhatsApp / Telegram / social) ─────────────────

@app.route('/<project>')
def share_page(project):
    """Landing page with OG meta tags — shared link goes here."""
    project_path = os.path.join(UPLOAD_FOLDER, project)
    if not os.path.exists(project_path) or not os.path.isdir(project_path):
        abort(404)
    thumb_file = find_thumbnail_in_project(project_path)
    meta = get_project_meta(project_path)
    display_name = meta.get('display_name') or folder_to_display(project)
    base = request.host_url.rstrip('/')
    thumbnail_url = '{}/{}/{}'.format(base, project, thumb_file) if thumb_file else None
    share_url = '{}/{}'.format(base, project)
    return render_template(
        'share.html',
        project_name=project,
        display_name=display_name,
        thumbnail_url=thumbnail_url,
        share_url=share_url
    )


# ── static tour files ─────────────────────────────────────────────────────────

@app.route('/<project>/')
def serve_project(project):
    project_path = os.path.join(UPLOAD_FOLDER, project)
    if not os.path.exists(project_path):
        abort(404)
    return send_from_directory(project_path, 'index.html')


@app.route('/<project>/<path:path>')
def serve_static(project, path):
    project_path = os.path.join(UPLOAD_FOLDER, project)
    return send_from_directory(project_path, path)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
