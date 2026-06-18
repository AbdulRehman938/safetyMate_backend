import io
import os
import re
import shutil

import pytesseract
from flask import Flask, jsonify, request
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
CORS(app, origins='*')

TESSERACT_CMD = os.getenv('TESSERACT_CMD', 'tesseract')
POPPLER_PATH = os.getenv('POPPLER_PATH') or None

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

for candidate in (TESSERACT_CMD, shutil.which('tesseract'), '/usr/bin/tesseract', '/nix/var/nix/profiles/default/bin/tesseract'):
    if candidate and os.path.isfile(candidate):
        pytesseract.pytesseract.tesseract_cmd = candidate
        app.logger.info('Using Tesseract: %s', candidate)
        break
else:
    app.logger.warning('Tesseract not found on PATH; set TESSERACT_CMD if needed')

COURSE_KEYWORDS = [
    {'name': 'Working at Heights', 'keywords': ['heights', 'fall protection', 'height']},
    {'name': 'Confined Space Entry', 'keywords': ['confined space', 'confined spaces', 'confined']},
    {'name': 'Fire Safety Level 1', 'keywords': ['fire safety', 'fire level', 'fire level 1', 'fire']},
    {'name': 'Hazardous Materials LVE', 'keywords': ['hazardous', 'hazmat', 'lve', 'materials']},
    {'name': 'Emergency Responder Drill', 'keywords': ['emergency', 'responder', 'first aid', 'cpr']},
    {'name': 'High-Altitude Safety', 'keywords': ['altitude', 'high-altitude']},
]


def error_response(message, status=400):
    return jsonify({'error': message}), status


def tesseract_available():
    cmd = pytesseract.pytesseract.tesseract_cmd
    return os.path.isfile(cmd) or shutil.which('tesseract') is not None


def run_ocr_on_bytes(file_bytes, filename):
    if not tesseract_available():
        raise Exception('Tesseract not installed on server environment')

    lower_name = (filename or '').lower()

    if lower_name.endswith('.pdf'):
        try:
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError('PDF support requires pdf2image') from exc

        poppler_path = POPPLER_PATH
        if shutil.which('pdftoppm') is None and not poppler_path:
            for poppler_bin in ('/usr/bin', '/nix/var/nix/profiles/default/bin'):
                if os.path.isfile(os.path.join(poppler_bin, 'pdftoppm')):
                    poppler_path = poppler_bin
                    break
            else:
                raise RuntimeError(
                    'Poppler is not installed. Install Poppler or set POPPLER_PATH.'
                )

        convert_kwargs = {'first_page': 1, 'last_page': 1}
        if poppler_path:
            convert_kwargs['poppler_path'] = poppler_path

        pages = convert_from_bytes(file_bytes, **convert_kwargs)
        if not pages:
            raise RuntimeError('Could not read PDF pages')
        return pytesseract.image_to_string(pages[0])

    image = Image.open(io.BytesIO(file_bytes))
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    return pytesseract.image_to_string(image)


def extract_course(text):
    label_match = re.search(
        r'(?:course|training|competency|certification)\s*[:\-]\s*([^\n\r]{1,120})',
        text,
        re.IGNORECASE,
    )
    if label_match:
        return label_match.group(1).strip()

    text_lower = text.lower()
    for course_item in COURSE_KEYWORDS:
        if any(keyword in text_lower for keyword in course_item['keywords']):
            return course_item['name']
    return ''


def extract_expiry(text):
    iso_regex = re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})')
    common_regex = re.compile(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})')

    iso_match = iso_regex.search(text)
    if iso_match:
        year, month, day = iso_match.groups()
        return f'{year}-{int(month):02d}-{int(day):02d}'

    common_match = common_regex.search(text)
    if common_match:
        p1, p2, p3 = map(int, common_match.groups())
        if p1 > 12:
            day, month, year = p1, p2, p3
        else:
            month, day, year = p1, p2, p3
        return f'{year}-{month:02d}-{day:02d}'

    return ''


def extract_name(text, filename):
    label_match = re.search(
        r'(?:name|candidate|trainee|employee|holder)\s*[:\-]\s*([^\n\r]{1,80})',
        text,
        re.IGNORECASE,
    )
    if label_match:
        return label_match.group(1).strip()

    base = os.path.splitext(filename or '')[0]
    if base:
        parts = re.split(r'\s*-\s*', base)
        if parts and parts[0].strip():
            return parts[0].strip()

    for line in text.splitlines():
        cleaned = line.strip()
        if len(cleaned) < 4:
            continue
        if re.match(r'^[A-Za-z][A-Za-z\s.\'-]{2,60}$', cleaned):
            return cleaned

    return ''


@app.route('/', methods=['GET'])
def index():
    return jsonify({'status': 'OCR API running'})


@app.route('/ocr', methods=['POST'])
def ocr():
    if 'file' not in request.files:
        return error_response('No file provided', 400)

    uploaded = request.files['file']
    if not uploaded or not uploaded.filename:
        return error_response('Empty file upload', 400)

    filename = uploaded.filename
    file_bytes = uploaded.read()
    if not file_bytes:
        return error_response('Uploaded file is empty', 400)

    try:
        ocr_text = run_ocr_on_bytes(file_bytes, filename)
    except Exception as exc:
        app.logger.exception('OCR extraction failed')
        return error_response(f'OCR extraction failed: {exc}', 500)

    search_target = f'{filename} {ocr_text}'.lower()
    name = extract_name(ocr_text, filename)
    course = extract_course(search_target)
    expiry = extract_expiry(search_target)

    if not name or not course or not expiry:
        missing = []
        if not name:
            missing.append('name')
        if not course:
            missing.append('course')
        if not expiry:
            missing.append('expiry')
        return error_response(
            f'Could not extract required fields: {", ".join(missing)}',
            422,
        )

    return jsonify({'name': name, 'course': course, 'expiry': expiry})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
