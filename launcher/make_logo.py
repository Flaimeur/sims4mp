# Genere le logo du lanceur a partir du dessin du mod (sims4mp/icon_package.py, logo
# « deux joueurs », formes simples, aucun element d'EA) :
#   - launcher/sims4mp_logo.py : images PNG en base64 (en-tete et icone de la fenetre) ;
#   - launcher/sims4mp.ico     : icone de l'exe (PyInstaller --icon), PNG de 16 a 256 px.
# A relancer seulement si le dessin change :  py -3.12 launcher/make_logo.py

import base64
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'sims4mp'))
import icon_package  # noqa: E402

HEADER_SIZE = 44          # en-tete de la barre laterale
WINDOW_SIZE = 64          # icone de la fenetre et de la barre des taches
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def logo_png(size):
    return icon_package.encode_png(icon_package.draw_logo(size), size, size)


def build_ico(pngs):
    """Fichier .ico (Windows Vista et plus) dont chaque image est un PNG."""
    header = struct.pack('<HHH', 0, 1, len(pngs))
    entries, data = b'', b''
    offset = 6 + 16 * len(pngs)
    for size, png in pngs:
        side = 0 if size >= 256 else size                 # 0 signifie 256 dans le format .ico
        entries += struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    return header + entries + data


def module_text(images):
    lines = ['# Fichier genere par launcher/make_logo.py : ne pas modifier a la main.',
             '# Logo Sims4MP « deux joueurs » (dessin original du projet, aucun element d\'EA).', '']
    for name, png in images:
        encoded = base64.b64encode(png).decode('ascii')
        lines.append('{} = ('.format(name))
        lines += ['    \'{}\''.format(encoded[i:i + 96]) for i in range(0, len(encoded), 96)]
        lines.append(')')
    return '\n'.join(lines) + '\n'


def main():
    (HERE / 'sims4mp_logo.py').write_text(module_text([
        ('LOGO_PNG_HEADER', logo_png(HEADER_SIZE)),
        ('LOGO_PNG_WINDOW', logo_png(WINDOW_SIZE)),
    ]), encoding='utf-8')
    (HERE / 'sims4mp.ico').write_bytes(build_ico([(size, logo_png(size)) for size in ICO_SIZES]))
    print('OK : launcher/sims4mp_logo.py et launcher/sims4mp.ico')


if __name__ == '__main__':
    main()
