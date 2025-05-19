from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import os
import uuid
from math import ceil

app = Flask(__name__)
app.secret_key = 'secret-key'

UPLOAD_FOLDER = 'uploads'
CLEANED_FOLDER = 'static/finished'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CLEANED_FOLDER, exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ------------------ DB INIT ------------------
def init_user_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_user_db()


# ------------------ USER MODEL ------------------
class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

def get_user_by_username(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(id=row[0], username=row[1], password_hash=row[2])
    return None

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, username, password FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(id=row[0], username=row[1], password_hash=row[2])
    return None

# ------------------ AUTH ROUTES ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = get_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Identifiants invalides', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    message = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            message = "Veuillez remplir tous les champs."
        elif get_user_by_username(username):
            message = "Nom d'utilisateur déjà utilisé."
        else:
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                      (username, generate_password_hash(password)))
            conn.commit()
            conn.close()
            message = "Utilisateur créé avec succès. Vous pouvez maintenant vous connecter."
    return render_template('register.html', message=message)

# ------------------------ Tes fonctions existantes
def detect_column_type(col, series):
    if pd.api.types.is_bool_dtype(series):
        return "booléen"
    elif series.dropna().unique().tolist() in ([0, 1], [1, 0]):
        return "binaire"
    elif pd.api.types.is_integer_dtype(series):
        return "entier"
    elif pd.api.types.is_float_dtype(series):
        return "float"
    elif pd.api.types.is_object_dtype(series):
        return "chaîne"
    else:
        return str(series.dtype)

def analyze_columns(df):
    analysis = []
    for col in df.columns:
        col_type = detect_column_type(col, df[col])
        total = len(df[col])
        missing = df[col].isna().sum()
        outliers = 0
        if pd.api.types.is_numeric_dtype(df[col]):
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            outliers = df[(df[col] < lower) | (df[col] > upper)].shape[0]
        analysis.append({
            'col': col,
            'type': col_type,
            'total': total,
            'missing': missing,
            'outliers': outliers
        })
    return analysis

def clean_data(df, outlier_action='remove'):
    original_df = df.copy()
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col].fillna('N/A', inplace=True)
        else:
            df[col].fillna(0, inplace=True)
    for col in df.select_dtypes(include='number').columns:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        if outlier_action == 'remove':
            df = df[(df[col] == 0) | ((df[col] >= lower) & (df[col] <= upper))]
        elif outlier_action == 'mean':
            mean_val = df[(df[col] >= lower) & (df[col] <= upper)][col].mean()
            df[col] = df[col].apply(lambda x: mean_val if (x < lower or x > upper and x != 0) else x)
        elif outlier_action == 'zero':
            df[col] = df[col].apply(lambda x: 0 if (x < lower or x > upper and x != 0) else x)
    df.drop_duplicates(inplace=True)
    return df, original_df

@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           deleted_rows=None,
                           modified_rows=None,
                           cleaned_file=None,
                           analysis=None,
                           current_page=1,
                           total_pages=1)

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    file = request.files['file']
    outlier_action = request.form.get('outlier_action', 'remove')
    filename = str(uuid.uuid4()) + '_' + file.filename
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    ext = filename.split('.')[-1].lower()
    try:
        if ext == 'csv':
            try:
                df = pd.read_csv(path, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding='latin1')
        elif ext == 'json':
            df = pd.read_json(path)
            df.to_csv(path, index=False)
            ext = 'csv'
        elif ext == 'xml':
            df = pd.read_xml(path)
            df.to_csv(path, index=False)
            ext = 'csv'
        else:
            return "Format de fichier non supporté", 400
    except Exception as e:
        return f"Erreur lors de la lecture du fichier : {e}", 500

    analysis = analyze_columns(df)
    df_cleaned, original_data = clean_data(df.copy(), outlier_action)
    modified_rows = sum(~df_cleaned.fillna('').eq(original_data.fillna('')).all(axis=1))
    deleted_rows = len(original_data) - len(df_cleaned)
    cleaned_filename = 'cleaned_' + filename.rsplit('.', 1)[0] + '.csv'
    cleaned_path = os.path.join(CLEANED_FOLDER, cleaned_filename)
    df_cleaned.to_csv(cleaned_path, index=False)

    page = int(request.args.get("page", 1))
    per_page = 10
    total_pages = ceil(len(analysis) / per_page)
    paginated_analysis = analysis[(page - 1) * per_page: page * per_page]

    return render_template('index.html',
                           deleted_rows=deleted_rows,
                           modified_rows=modified_rows,
                           original_filename=filename,
                           cleaned_file=cleaned_filename,
                           analysis=paginated_analysis,
                           current_page=page,
                           total_pages=total_pages)

@app.route('/download/<filename>')
@login_required
def download_file(filename):
    path = os.path.join(CLEANED_FOLDER, filename)
    return send_file(path, as_attachment=True)

@app.route('/rapport/<filename>')
@login_required
def rapport(filename):
    page = int(request.args.get('page', 1))
    per_page = 10
    try:
        df = pd.read_csv(os.path.join(UPLOAD_FOLDER, filename))
    except Exception as e:
        return f"Erreur lors de la lecture du fichier original : {e}", 500

    total = len(df)
    total_pages = ceil(total / per_page)
    df_page = df.iloc[(page - 1) * per_page: page * per_page]

    df_numeric = df.copy()
    for col in df_numeric.columns:
        if df_numeric[col].dtype == 'object':
            try:
                df_numeric[col] = pd.to_numeric(df_numeric[col], errors='coerce')
            except:
                continue
    df_numeric.fillna(0, inplace=True)

    outlier_bounds = {}
    for col in df_numeric.select_dtypes(include='number').columns:
        Q1 = df_numeric[col].quantile(0.25)
        Q3 = df_numeric[col].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        outlier_bounds[col] = (lower, upper)

    thresholds = {
        col: {"min": round(bounds[0], 2), "max": round(bounds[1], 2)}
        for col, bounds in outlier_bounds.items()
    }

    duplicate_mask = df.duplicated(keep=False)

    styled_rows = []
    for idx, row in df_page.iterrows():
        styled_row = []
        is_duplicate = duplicate_mask.iloc[idx]
        for col in df.columns:
            value = row[col]
            style = ""
            if pd.isna(value) or value == "":
                style = 'background-color: #ffc70f;'
            elif col in outlier_bounds:
                try:
                    numeric_value = pd.to_numeric(str(value).strip(), errors='coerce')
                    if pd.notna(numeric_value):
                        low, high = outlier_bounds[col]
                        if numeric_value < low or numeric_value > high:
                            style = 'background-color: #fd7883;'
                except:
                    pass
            if is_duplicate:
                style = 'background-color: #58cadf;'
            styled_row.append(f'<td style="{style}">{value}</td>')
        styled_rows.append(f"<tr>{''.join(styled_row)}</tr>")

    table_html = f"<table class='table table-bordered table-striped'><thead><tr>{''.join([f'<th>{c}</th>' for c in df.columns])}</tr></thead><tbody>{''.join(styled_rows)}</tbody></table>"

    return render_template("rapport.html",
                           table=table_html,
                           page=page,
                           total_pages=total_pages,
                           filename=filename,
                           thresholds=thresholds)

if __name__ == '__main__':
    app.run(debug=True)
