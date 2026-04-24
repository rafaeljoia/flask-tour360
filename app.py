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
                'thumbnail': thumb,
                'header_enabled': meta.get('header_enabled', False)
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
        meta = {'display_name': display_name or folder_to_display(project_name),
                   'header_enabled': request.form.get('header_enabled') == 'on'}
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
    meta['header_enabled'] = request.form.get('header_enabled') == 'on'
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
      index_path = os.path.join(project_path, 'index.html')
      if not os.path.isfile(index_path):
          abort(404)
      import re
      meta = get_project_meta(project_path)
      with open(index_path, 'r', encoding='utf-8', errors='ignore') as fh:
          html = fh.read()
      # Rewrite absolute asset paths (/foo.css → ./foo.css) so they resolve
      # relative to /<project>/ instead of the domain root
      html = re.sub(r'((?:href|src|action)=")(/[^"#][^"]*)"', r'\1.\2"', html)
      # Inject Bravia header if enabled
      if meta.get('header_enabled'):
          header_css = (
              '<style>'
              '#bravia-header{position:fixed;top:0;left:0;right:0;height:56px;'
              'background:#0C0C0C;border-bottom:1px solid #1c1c1c;'
              'display:flex;align-items:center;justify-content:space-between;padding:0 20px;z-index:2147483647;'
              'font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;}'
              '#bravia-header .bh-logo{text-decoration:none;font-size:20px;font-weight:700;letter-spacing:-0.5px;flex-shrink:0;}'
              '#bravia-header .bh-cta{display:flex;align-items:center;gap:10px;}'
              '#bravia-header .bh-cta-text{font-size:13px;color:rgba(245,245,245,0.9);font-weight:500;white-space:nowrap;}'
              '@media(max-width:520px){#bravia-header .bh-cta-text{display:none;}}'
              '#bravia-header .bh-wa{display:inline-flex;align-items:center;gap:7px;background:#25D366;'
              'color:#fff;font-size:13px;font-weight:600;padding:7px 14px;border-radius:8px;'
              'text-decoration:none;white-space:nowrap;transition:opacity 0.2s;flex-shrink:0;}'
              '#bravia-header .bh-wa:hover{opacity:0.88}'
              'body{margin-top:56px!important;padding-top:0!important;}'
              '</style>'
          )
          header_html = (
              '<div id="bravia-header">'
              '<a href="/" class="bh-logo">'
              '<span style="color:#F5C700">Bravia</span>'
              '<span style="color:rgba(245,245,245,0.9)"> 360</span>'
              '</a>'
              '<div class="bh-cta">'
              '<span class="bh-cta-text">Quer criar seu <span style="color:#F5C700;font-weight:700">Tour 360°</span>?</span>'
              '<a href="https://wa.me/5535984344266?text=Ol%C3%A1%21%20Vi%20o%20Tour%20360%C2%B0%20e%20gostaria%20de%20saber%20mais." target="_blank" rel="noopener" class="bh-wa">'
              '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">'
              '<path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>'
              '</svg>'
              'WhatsApp'
              '</a>'
              '</div>'
              '</div>'
          )
          if '</head>' in html:
              html = html.replace('</head>', header_css + '</head>', 1)
          else:
              html = header_css + html
          body_match = re.search(r'<body[^>]*>', html, re.IGNORECASE)
          if body_match:
              insert_pos = body_match.end()
              html = html[:insert_pos] + header_html + html[insert_pos:]
          else:
              html = header_html + html
      return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/<project>/<path:path>')
def serve_static(project, path):
    project_path = os.path.join(UPLOAD_FOLDER, project)
    return send_from_directory(project_path, path)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
