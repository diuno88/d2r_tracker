"""
imghdr compatibility shim — Python 3.13에서 제거된 모듈 대체
paddleocr 등 구버전 패키지의 'import imghdr' 오류 방지
"""
import struct


def what(file, h=None):
    if h is None:
        if isinstance(file, str):
            with open(file, 'rb') as f:
                h = f.read(32)
        else:
            location = file.tell()
            h = file.read(32)
            file.seek(location)

    if h[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if h[:2] in (b'\xff\xd8',):
        return 'jpeg'
    if h[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if h[:4] in (b'II\x2a\x00', b'MM\x00\x2a'):
        return 'tiff'
    if h[:2] == b'BM':
        return 'bmp'
    if h[:4] == b'RIFF' and h[8:12] == b'WEBP':
        return 'webp'
    return None
