# Compile les modules du mod en .pyc Python 3.7 et les emballe dans
# build\sims4mp_hello.ts4script (une archive zip).
#
# A lancer OBLIGATOIREMENT avec Python 3.7 :  py -3.7 build.py
# Un .pyc compile avec une autre version ne sera pas charge par le jeu.

import os
import py_compile
import sys
import zipfile

ARCHIVE = 'sims4mp_hello'
# Modules embarques dans l'archive (test_transport.py n'en fait pas partie).
MODULES = ['sims4mp_hello', 'protocol', 'transport']

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(HERE, 'build')
OUTPUT = os.path.join(BUILD_DIR, ARCHIVE + '.ts4script')
# Icone de la roue (0.16.0) : a placer dans Mods a cote du .ts4script.
ICONS = os.path.join(BUILD_DIR, 'sims4mp_icons.package')
ICON_PREVIEW = os.path.join(BUILD_DIR, 'sims4mp_icon.png')


def main():
    if sys.version_info[:2] != (3, 7):
        print('ERREUR : Python 3.7 requis, version actuelle {}.{}.'.format(*sys.version_info[:2]))
        print('Installez Python 3.7 puis lancez :  py -3.7 build.py')
        return 1

    if not os.path.isdir(BUILD_DIR):
        os.makedirs(BUILD_DIR)

    # Les .pyc doivent etre a la racine de l'archive pour etre importes par le jeu.
    with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_STORED) as archive:
        for module in MODULES:
            source = os.path.join(HERE, module + '.py')
            pyc_path = os.path.join(BUILD_DIR, module + '.pyc')
            py_compile.compile(source, cfile=pyc_path, doraise=True)
            archive.write(pyc_path, module + '.pyc')
            print('  + ' + module + '.pyc')

    print('OK : ' + OUTPUT)

    sys.path.insert(0, HERE)
    import icon_package
    png = icon_package.icon_png()
    with open(ICON_PREVIEW, 'wb') as f:
        f.write(png)
    with open(ICONS, 'wb') as f:
        f.write(icon_package.build_package([(icon_package.PNG_TYPE, 0, icon_package.ICON_INSTANCE, png)]))
    print('OK : ' + ICONS + ' (icone {:016X})'.format(icon_package.ICON_INSTANCE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
