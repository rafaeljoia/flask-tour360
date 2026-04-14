from flask import Flask, request, render_template, redirect, url_for, send_from_directory, abort
import os
import zipfile

app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def home():
    projects = [d for d in os.listdir(UPLOAD_FOLDER) if os.path.isdir(os.path.join(UPLOAD_FOLDER, d))]
    return render_template('home.html', projects=projects)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        file = request.files['file']
        project_name = request.form['project_name']

        if not file or not project_name:
            return 'Arquivo e nome são obrigatórios', 400

        project_path = os.path.join(UPLOAD_FOLDER, project_name)
        os.makedirs(project_path, exist_ok=True)

        zip_path = os.path.join(project_path, 'project.zip')
        file.save(zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(project_path)

        os.remove(zip_path)

        return redirect(url_for('home'))

    return render_template('register.html')

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