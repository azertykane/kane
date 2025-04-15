from flask import Flask, render_template, request, send_file, url_for
import pandas as pd
import os
import uuid

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
CLEANED_FOLDER = 'static/finished'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CLEANED_FOLDER, exist_ok=True)


def clean_data(df, outlier_action='remove'):
    original_df = df.copy()

    # Remplacer les valeurs manquantes
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col].fillna('N/A', inplace=True)
        else:
            df[col].fillna(0, inplace=True)

    # Gérer les valeurs aberrantes
    for col in df.select_dtypes(include='number').columns:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR

        if outlier_action == 'remove':
            df = df[(df[col] == 0) | ((df[col] >= lower_bound) & (df[col] <= upper_bound))]
        elif outlier_action == 'mean':
            mean_val = df[(df[col] >= lower_bound) & (df[col] <= upper_bound)][col].mean()
            df[col] = df[col].apply(lambda x: mean_val if (x < lower_bound or x > upper_bound and x != 0) else x)
        elif outlier_action == 'zero':
            df[col] = df[col].apply(lambda x: 0 if (x < lower_bound or x > upper_bound and x != 0) else x)

    # Supprimer les doublons
    df.drop_duplicates(inplace=True)

    return df, original_df


@app.route('/')
def index():
    return render_template('index.html',
                           deleted_rows=None,
                           modified_rows=None,
                           cleaned_file=None,
                           diff=None)

@app.route('/download/<filename>')
def download_file(filename):
    path = os.path.join(CLEANED_FOLDER, filename)
    return send_file(path, as_attachment=True)


@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    outlier_action = request.form.get('outlier_action', 'remove')

    filename = str(uuid.uuid4()) + '_' + file.filename
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    ext = filename.split('.')[-1].lower()

    if ext == 'csv':
        try:
            df = pd.read_csv(path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding='latin1')
    elif ext == 'json':
        df = pd.read_json(path)
    elif ext == 'xml':
        df = pd.read_xml(path)
    else:
        return "Format de fichier non supporté", 400

    df_cleaned, original_data = clean_data(df.copy(), outlier_action)

    # Comparaison ligne par ligne
    modified_rows = sum(~df_cleaned.fillna('').eq(original_data.fillna('')).all(axis=1))
    deleted_rows = len(original_data) - len(df_cleaned)

    cleaned_filename = 'cleaned_' + filename.rsplit('.', 1)[0] + '.csv'
    cleaned_path = os.path.join(CLEANED_FOLDER, cleaned_filename)
    df_cleaned.to_csv(cleaned_path, index=False)

    return render_template('index.html',
                           deleted_rows=deleted_rows,
                           modified_rows=modified_rows,
                           cleaned_file=cleaned_filename,
                           diff=None)


if __name__ == '__main__':
    app.run(debug=True)
