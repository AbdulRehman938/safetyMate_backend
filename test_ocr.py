"""Generate a test certificate JPG and POST it to the OCR API."""
import io
import json
import urllib.request

from PIL import Image, ImageDraw, ImageFont


def main():
    img = Image.new('RGB', (900, 500), 'white')
    draw = ImageDraw.Draw(img)
    lines = [
        'Certificate of Training',
        'Name: Ahmed Malik',
        'Course: Fire Safety Level 1',
        'Expiry: 2028-12-31',
    ]
    y = 40
    for line in lines:
        draw.text((40, y), line, fill='black')
        y += 50

    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    file_bytes = buf.getvalue()

    boundary = '----SafetyMateOcrTest'
    body = (
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="file"; filename="Ahmed Malik - Fire Safety Level 1 - 2028-12-31.jpg"\r\n'
        'Content-Type: image/jpeg\r\n\r\n'
    ).encode('utf-8') + file_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')

    req = urllib.request.Request('http://127.0.0.1:5000/ocr', data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
        print('OCR API status:', resp.status)
        print('OCR API response:', json.dumps(payload, indent=2))


if __name__ == '__main__':
    main()
