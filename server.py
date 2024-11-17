from flask import Flask, send_from_directory, jsonify, Response, request
import os
from flask_cors import CORS
import email
import base64
import quopri
from bs4 import BeautifulSoup
import json
import codecs
import subprocess
import re
import chardet

app = Flask(__name__)
CORS(app)

# Пути к директориям
COURSE_DIR = "./course"
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

# Путь к файлу с прогрессом
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")


def load_progress():
    """Загружает прогресс пользователей"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"Вадим": {"completed": []}, "Дарья": {"completed": []}}
    return {"Вадим": {"completed": []}, "Дарья": {"completed": []}}


def save_progress(progress):
    """Сохраняет прогресс пользователей"""
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving progress: {e}")


def decode_content(content, encoding=None):
    """Декодирует контент с приоритетом русских кодировок"""
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')

    # Пробуем известные кодировки для русского языка
    encodings = ['cp1251', 'windows-1251', 'utf-8', 'koi8-r']

    for enc in encodings:
        try:
            decoded = content.decode(enc)
            # Проверяем наличие русских букв
            if any(ord('а') <= ord(c) <= ord('я') for c in decoded.lower()):
                return decoded
        except:
            continue

    # Пытаемся определить кодировку автоматически
    try:
        detected = chardet.detect(content)
        if detected['encoding']:
            return content.decode(detected['encoding'], errors='ignore')
    except:
        pass

    # Если ничего не сработало, используем cp1251 с игнорированием ошибок
    return content.decode('cp1251', errors='ignore')


def extract_mht_content(file_path):
    """Извлекает содержимое MHT файла с поддержкой русского языка"""
    try:
        with open(file_path, 'rb') as f:
            message = email.message_from_binary_file(f)

        # Находим HTML часть
        html_part = None
        for part in message.walk():
            if part.get_content_type() == 'text/html':
                html_part = part
                break

        if not html_part:
            return "<h1>Ошибка: HTML контент не найден в MHT файле</h1>"

        # Получаем контент и декодируем
        content = html_part.get_payload(decode=False)
        transfer_encoding = html_part.get('Content-Transfer-Encoding', '').lower()

        if transfer_encoding == 'base64':
            content = base64.b64decode(content)
        elif transfer_encoding == 'quoted-printable':
            content = quopri.decodestring(content)

        # Декодируем с поддержкой русского языка
        html_content = decode_content(content)

        # Создаем BeautifulSoup объект
        soup = BeautifulSoup(html_content, 'html.parser')

        # Обрабатываем кодировку
        if soup.meta:
            for meta in soup.find_all('meta'):
                if 'charset' in meta.attrs or 'content-type' in meta.attrs.get('http-equiv', '').lower():
                    meta.decompose()

        meta_charset = soup.new_tag('meta')
        meta_charset['charset'] = 'utf-8'
        if soup.head:
            soup.head.insert(0, meta_charset)
        else:
            head = soup.new_tag('head')
            head.append(meta_charset)
            if soup.html:
                soup.html.insert(0, head)
            else:
                html = soup.new_tag('html')
                html.append(head)
                soup.append(html)

        # Обрабатываем встроенные ресурсы
        resources = {}
        for part in message.walk():
            if 'Content-Location' in part:
                location = part['Content-Location']
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                if payload:
                    resources[location] = (content_type, payload)

        # Обновляем ссылки на картинки
        for img in soup.find_all('img'):
            src = img.get('src')
            if src in resources:
                content_type, payload = resources[src]
                data_url = f"data:{content_type};base64,{base64.b64encode(payload).decode()}"
                img['src'] = data_url

        # Добавляем стили
        style = soup.new_tag('style')
        style.string = """
            body { 
                font-family: Arial, sans-serif;
                line-height: 1.6;
                max-width: 100%;
                margin: 0;
                padding: 20px;
                box-sizing: border-box;
            }
            img {
                max-width: 100%;
                height: auto;
            }
            pre, code {
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: 'Courier New', Courier, monospace;
                background: #f5f5f5;
                padding: 10px;
                border-radius: 4px;
            }
            table {
                border-collapse: collapse;
                width: 100%;
                margin: 10px 0;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            th {
                background-color: #f5f5f5;
            }
        """
        if soup.head:
            soup.head.append(style)

        return str(soup)

    except Exception as e:
        return f"<h1>Ошибка при обработке MHT файла: {str(e)}</h1>"


def convert_pptx_to_pdf(file_path):
    """Конвертирует PPTX в PDF"""
    try:
        output_dir = os.path.dirname(file_path)
        subprocess.run(
            ['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', output_dir, file_path],
            timeout=60,
            check=True
        )
        pdf_path = file_path.rsplit('.', 1)[0] + '.pdf'
        return pdf_path if os.path.exists(pdf_path) else None
    except Exception as e:
        print(f"Error converting PPTX to PDF: {e}")
        return None


def scan_directory(path):
    """Сканирует директорию и возвращает структуру файлов"""
    result = {}
    try:
        for item in sorted(os.listdir(path)):
            item_path = os.path.join(path, item)
            # Декодируем имя файла из системной кодировки
            item_name = item
            if isinstance(item_name, bytes):
                item_name = item_name.decode('utf-8')

            if os.path.isdir(item_path):
                sub_items = scan_directory(item_path)
                if sub_items:  # Добавляем только непустые директории
                    result[item_name] = sub_items
            else:
                if item_name.lower().endswith(('.mht', '.mp4', '.pptx')):
                    rel_path = os.path.relpath(item_path, COURSE_DIR)
                    result[item_name] = rel_path.replace('\\', '/')
    except Exception as e:
        print(f"Error scanning directory {path}: {e}")
        return {}

    return result


# API endpoints
@app.route('/api/structure')
def get_structure():
    """Возвращает структуру файлов курса"""
    return jsonify(scan_directory(COURSE_DIR))


@app.route('/api/progress', methods=['GET'])
def get_progress():
    """Получает прогресс пользователя"""
    user = request.args.get('user')
    progress = load_progress()
    return jsonify(progress.get(user, {"completed": []}))


@app.route('/api/progress', methods=['POST'])
def update_progress():
    """Обновляет прогресс пользователя"""
    try:
        data = request.get_json()
        user = data.get('user')
        file_path = data.get('file_path')
        completed = data.get('completed', True)

        if not user or not file_path:
            return jsonify({"error": "Missing user or file_path"}), 400

        progress = load_progress()
        if user not in progress:
            progress[user] = {"completed": []}

        if completed and file_path not in progress[user]["completed"]:
            progress[user]["completed"].append(file_path)
        elif not completed and file_path in progress[user]["completed"]:
            progress[user]["completed"].remove(file_path)

        save_progress(progress)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/content/<path:filepath>')
def serve_file(filepath):
    """Отдает файлы из директории курса"""
    try:
        full_path = os.path.join(COURSE_DIR, filepath)

        # Проверяем существование файла
        if not os.path.exists(full_path):
            return "Файл не найден", 404

        # Обработка PPTX файлов
        if filepath.lower().endswith('.pptx'):
            pdf_path = convert_pptx_to_pdf(full_path)
            if pdf_path:
                return send_from_directory(
                    os.path.dirname(pdf_path),
                    os.path.basename(pdf_path),
                    mimetype='application/pdf'
                )
            return "Ошибка конвертации PPTX", 500

        # Обработка MHT файлов
        elif filepath.lower().endswith('.mht'):
            html_content = extract_mht_content(full_path)
            response = Response(html_content, mimetype='text/html; charset=utf-8')
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
            return response

        # Для остальных файлов
        return send_from_directory(COURSE_DIR, filepath)

    except Exception as e:
        return f"Ошибка при обработке файла: {str(e)}", 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)