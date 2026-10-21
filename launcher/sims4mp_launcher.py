# Lanceur Sims4MP : installe sims4mp_hello.ts4script dans le dossier Mods
# puis lance Les Sims 4 via Steam.
#
# Python 3.12, bibliotheque standard uniquement.
# Build :  py -3.12 -m PyInstaller --onefile --name Sims4MP_Launcher launcher/sims4mp_launcher.py
#
# Option de test : --sans-lancement  (fait tout sauf lancer le jeu)

import ctypes
import datetime
import os
import re
import shutil
import subprocess
import sys
import traceback
import uuid
import zipfile
from pathlib import Path

MOD_FILE = 'sims4mp_hello.ts4script'
GAME_PROCESS = 'TS4_x64.exe'
STEAM_URL = 'steam://rungameid/1222670'
BACKUP_DIR_NAME = 'sims4mp_backups'
LOG_NAME = 'launcher.log'

# FOLDERID_Documents
FOLDERID_DOCUMENTS = '{FDD39AD0-238F-46AF-ADB4-6C85480369C7}'


class LauncherError(Exception):
    """Erreur attendue : le message est affiche tel quel a l'utilisateur."""


def base_dir():
    # Dossier du .exe une fois compile, sinon dossier du script.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log(message):
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        # utf-8-sig : le BOM permet a Notepad/PowerShell de lire les accents
        # (le dossier "Les Sims 4" contient des espaces insecables).
        with open(base_dir() / LOG_NAME, 'a', encoding='utf-8-sig') as f:
            f.write('[{}] {}\n'.format(stamp, message))
    except OSError:
        pass


def say(message=''):
    print(message)
    if message:
        log(message)


# --- 1. Fichier du mod -------------------------------------------------------

def find_mod_source():
    here = base_dir()
    candidates = [here / MOD_FILE]
    # sims4mp\build\ depuis le dossier du .exe et ses parents
    # (le .exe compile se trouve dans dist\, le script dans launcher\).
    for folder in [here] + list(here.parents)[:3]:
        candidates.append(folder / 'sims4mp' / 'build' / MOD_FILE)
    for path in candidates:
        if path.is_file():
            return path
    raise LauncherError(
        'Fichier {} introuvable.\nEmplacements cherches :\n{}\n'
        'Placez {} a cote du lanceur.'.format(
            MOD_FILE, '\n'.join('  - {}'.format(p) for p in candidates), MOD_FILE))


def read_mod_version(path):
    # Le .ts4script est un zip contenant sims4mp_hello.pyc (Python 3.7).
    # On ne peut pas charger ce bytecode depuis Python 3.12 : on cherche la
    # chaine MOD_VERSION (forme X.Y.Z) dans les constantes marshal.
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read('sims4mp_hello.pyc')
    except (OSError, KeyError, zipfile.BadZipFile):
        return 'inconnue'
    # Chaine ASCII courte marshal : type 'z' (avec ou sans FLAG_REF), longueur, texte.
    for match in re.finditer(rb'[\x5a\x7a\xda\xfa]([\x05-\x0f])(\d+\.\d+\.\d+)', data):
        if match.group(1)[0] == len(match.group(2)):
            return match.group(2).decode('ascii')
    return 'inconnue'


# --- 2. Dossier Mods ---------------------------------------------------------

def documents_dir():
    # SHGetKnownFolderPath gere les Documents deplaces (OneDrive, autre disque...).
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                    ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_ubyte * 8)]

    raw = uuid.UUID(FOLDERID_DOCUMENTS).bytes_le
    guid = GUID.from_buffer_copy(raw)
    out = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(out))
    if result != 0 or not out.value:
        raise LauncherError('Impossible de trouver le dossier Documents (code {}).'.format(result))
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def find_mods_dir():
    ea_dir = documents_dir() / 'Electronic Arts'
    if not ea_dir.is_dir():
        raise LauncherError('Dossier introuvable : {}\n'
                            'Lancez Les Sims 4 une fois pour le creer.'.format(ea_dir))

    found = []
    for root, dirs, files in os.walk(ea_dir):
        if any(name.lower() == 'resource.cfg' for name in files):
            found.append(Path(root))

    mods = [p for p in found if p.name.lower() == 'mods']
    if len(mods) != 1:
        lines = '\n'.join('  - {}'.format(p / 'Resource.cfg') for p in found) or '  (aucun)'
        raise LauncherError(
            'Il faut exactement un dossier Mods contenant Resource.cfg, {} trouve(s).\n'
            'Fichiers Resource.cfg trouves dans {} :\n{}\n'
            'Aucune copie effectuee.'.format(len(mods), ea_dir, lines))
    return mods[0]


# --- 3. Jeu en cours ---------------------------------------------------------

def game_is_running():
    proc = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq {}'.format(GAME_PROCESS), '/NH', '/FO', 'CSV'],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode != 0:
        raise LauncherError('tasklist a echoue (code {}), impossible de verifier '
                            'si le jeu tourne.'.format(proc.returncode))
    output = proc.stdout.decode('oem', errors='replace').lower()
    return '"{}"'.format(GAME_PROCESS.lower()) in output


# --- 4. Installation ---------------------------------------------------------

def install_mod(source, mods_dir):
    target = mods_dir / MOD_FILE
    backup = None
    if target.exists():
        # Sauvegarde HORS du dossier Mods : un .ts4script renomme dans Mods
        # (ou un sous-dossier) serait charge par le jeu en double.
        backup_dir = base_dir() / BACKUP_DIR_NAME
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = backup_dir / 'sims4mp_hello_{}.ts4script'.format(stamp)
        shutil.copy2(target, backup)
        if backup.stat().st_size != target.stat().st_size:
            raise LauncherError('Sauvegarde de l\'ancien mod incomplete : {}'.format(backup))

    shutil.copy2(source, target)
    src_size = source.stat().st_size
    dst_size = target.stat().st_size
    if src_size != dst_size:
        raise LauncherError('Copie incorrecte : {} octets copies au lieu de {}.\n'
                            'Fichier : {}'.format(dst_size, src_size, target))
    return target, backup


def other_copies(mods_dir, target):
    # Autres sims4mp_hello*.ts4script dans Mods : risque de charger deux versions.
    result = []
    for path in mods_dir.rglob('sims4mp_hello*.ts4script'):
        if path.resolve() != target.resolve():
            result.append(path)
    return result


# --- Programme principal -----------------------------------------------------

def run(launch_game):
    say('=== Lanceur Sims4MP ===')

    source = find_mod_source()
    version = read_mod_version(source)
    say('Mod trouve : {} (version {})'.format(source, version))

    mods_dir = find_mods_dir()
    say('Dossier Mods : {}'.format(mods_dir))

    if game_is_running():
        raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution), '
                            'puis relancez ce programme.'.format(GAME_PROCESS))

    target, backup = install_mod(source, mods_dir)
    say('Mod copie : {} ({} octets)'.format(target, target.stat().st_size))

    for path in other_copies(mods_dir, target):
        say('ATTENTION : autre copie du mod dans Mods, a supprimer : {}'.format(path))

    if launch_game:
        say('Lancement des Sims 4 via Steam...')
        os.startfile(STEAM_URL)
    else:
        say('Lancement du jeu ignore (--sans-lancement).')

    say()
    say('--- Resume ---')
    say('Version du mod installe : {}'.format(version))
    say('Dossier Mods            : {}'.format(mods_dir))
    if backup:
        say('Ancien mod sauvegarde   : {}'.format(backup))
    else:
        say('Ancien mod sauvegarde   : aucun (pas de mod precedent)')


def wait_key():
    try:
        input('\nAppuyez sur Entree pour fermer...')
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    # Sortie redirigee : ne jamais planter sur un caractere non affichable.
    try:
        sys.stdout.reconfigure(errors='replace')
    except AttributeError:
        pass
    launch_game = '--sans-lancement' not in sys.argv[1:]
    code = 0
    try:
        run(launch_game)
    except LauncherError as exc:
        say()
        say('ERREUR : {}'.format(exc))
        code = 1
    except Exception:
        print('\nERREUR inattendue. Detail ecrit dans {}'.format(base_dir() / LOG_NAME))
        print(traceback.format_exc())
        log('ERREUR inattendue :\n' + traceback.format_exc())
        code = 2
    wait_key()
    return code


if __name__ == '__main__':
    sys.exit(main())
