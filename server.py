from flask import Flask, send_from_directory, jsonify, Response
import os
from flask_cors import CORS
import email
import base64
import quopri
from bs4 import BeautifulSoup
import codecs

app = Flask(__name__)
CORS(app)

# Путь к директории с курсом
COURSE_DIR = "./course"


def decode_content(content, encoding=None):
    """Простое декодирование с приоритетом русских кодировок"""
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

    # Если ничего не сработало, используем cp1251 с игнорированием ошибок
    return content.decode('cp1251', errors='ignore')


def extract_mht_content(file_path):
    """Извлекает содержимое MHT файла с фокусом на русский язык"""
    with open(file_path, 'rb') as f:
        # Читаем файл с помощью codecs для поддержки русских символов
        raw_content = f.read()
        message = email.message_from_bytes(raw_content)

    # Находим HTML часть
    html_part = None
    for part in message.walk():
        if part.get_content_type() == 'text/html':
            html_part = part
            break

    if not html_part:
        return "<h1>Ошибка: HTML контент не найден в MHT файле</h1>"

    # Получаем контент и обрабатываем кодировку
    content = html_part.get_payload(decode=False)

    # Декодируем в зависимости от типа кодирования
    transfer_encoding = html_part.get('Content-Transfer-Encoding', '').lower()
    if transfer_encoding == 'base64':
        content = base64.b64decode(content)
    elif transfer_encoding == 'quoted-printable':
        content = quopri.decodestring(content)

    # Декодируем контент с приоритетом русских кодировок
    html_content = decode_content(content)

    # Создаем BeautifulSoup объект
    soup = BeautifulSoup(html_content, 'html.parser')

    # Устанавливаем правильную кодировку
    if soup.meta:
        for meta in soup.find_all('meta'):
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
        }
    """
    if soup.head:
        soup.head.append(style)

    return str(soup)


def scan_directory(path):
    """Сканирует директорию и возвращает структуру файлов"""
    result = {}
    try:
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            # Декодируем имя файла из системной кодировки
            item_name = item
            if isinstance(item_name, bytes):
                item_name = item_name.decode('utf-8')

            if os.path.isdir(item_path):
                result[item_name] = scan_directory(item_path)
            else:
                if item_name.lower().endswith(('.mht', '.mp4')):
                    rel_path = os.path.relpath(item_path, COURSE_DIR)
                    result[item_name] = rel_path.replace('\\', '/')
    except Exception as e:
        print(f"Ошибка при сканировании директории {path}: {str(e)}")
        return {}

    return result


@app.route('/api/structure')
def get_structure():
    """Возвращает структуру файлов курса"""
    return jsonify(scan_directory(COURSE_DIR))


@app.route('/content/<path:filepath>')
def serve_file(filepath):
    """Отдает файлы из директории курса"""
    try:
        full_path = os.path.join(COURSE_DIR, filepath)

        # Если это MHT файл, конвертируем его
        if filepath.lower().endswith('.mht'):
            html_content = extract_mht_content(full_path)
            response = Response(html_content, mimetype='text/html; charset=utf-8')
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
            return response

        # Для остальных файлов отдаем как есть
        return send_from_directory(COURSE_DIR, filepath)
    except Exception as e:
        return f"Ошибка при обработке файла: {str(e)}", 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)