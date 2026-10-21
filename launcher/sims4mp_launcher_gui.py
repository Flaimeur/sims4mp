# Lanceur Sims4MP, version fenetre (tkinter).
#
# Python 3.12, bibliotheque standard uniquement.
# Build :  py -3.12 -m PyInstaller --onefile --noconsole --noconfirm --name Sims4MP_Launcher_GUI launcher/sims4mp_launcher_gui.py
#
# Choix Heberger / Rejoindre, reglage sims4mp_settings.json, installation du
# mod local et mise a jour du mod depuis une Release GitHub (manifeste JSON).
# Pas de lancement du jeu, pas de pare-feu, aucune sauvegarde du jeu touchee.
#
# La logique d'installation reprend sims4mp_launcher.py (non modifie), avec
# des chemins passes en parametre pour pouvoir la tester sur un faux dossier
# Mods, une verification SHA-256 en plus de la taille, et un remplacement
# atomique (l'ancien mod reste en place si une etape echoue).

import collections
import ctypes
import datetime
import hashlib
import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

# --- Mise a jour depuis GitHub -----------------------------------------------
# URL HTTPS du manifeste JSON publie avec la Release (a remplir). Exemple :
#   https://github.com/<compte>/<depot>/releases/latest/download/sims4mp_manifest.json
# Contenu attendu (cles exactes, aucune autre) :
#   {"version": "0.4.0", "fichier": "sims4mp_hello.ts4script",
#    "url": "https://.../sims4mp_hello.ts4script", "sha256": "<64 hex>",
#    "taille": 37429, "statut": "stable"}            (statut : "stable" ou "test")
MANIFEST_URL = "À_REMPLIR"
DOWNLOAD_TIMEOUT = 15                    # secondes, pour tout le telechargement
MAX_MOD_SIZE = 5 * 1024 * 1024           # 5 Mo
MAX_MANIFEST_SIZE = 64 * 1024
MANIFEST_KEYS = {'version', 'fichier', 'url', 'sha256', 'taille', 'statut'}
STATUS_STABLE = 'stable'
STATUS_TEST = 'test'
USER_AGENT = 'Sims4MP-Launcher'
# Page OPTIONS : depot et tag enregistres a cote du .exe ; ils remplacent
# MANIFEST_URL quand ils sont renseignes.
CONFIG_NAME = 'sims4mp_launcher_config.json'
CONFIG_KEYS = {'depot', 'tag'}
MANIFEST_NAME = 'sims4mp_manifest.json'

MOD_FILE = 'sims4mp_hello.ts4script'
GAME_PROCESS = 'TS4_x64.exe'
STEAM_GAME_URL = 'steam://rungameid/1222670'     # Les Sims 4 sur Steam
BACKUP_DIR_NAME = 'sims4mp_backups'
LOG_NAME = 'launcher.log'
SETTINGS_NAME = 'sims4mp_settings.json'

ROLE_HOST = 'host'
ROLE_JOIN = 'join'
ROLES = (ROLE_HOST, ROLE_JOIN)
DEFAULT_PORT = 7777          # meme valeur que DEFAULT_PORT dans sims4mp_hello.py
PORT_MIN, PORT_MAX = 1024, 65535
SETTINGS_KEYS = {'role', 'ip', 'port'}

# FOLDERID_Documents
FOLDERID_DOCUMENTS = '{FDD39AD0-238F-46AF-ADB4-6C85480369C7}'


class LauncherError(Exception):
    """Erreur attendue : le message est affiche tel quel a l'utilisateur."""


# --- Journal -----------------------------------------------------------------

def base_dir():
    # Dossier du .exe une fois compile, sinon dossier du script.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log(message):
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        # utf-8-sig : lisible par Notepad/PowerShell (espaces insecables de "Les Sims 4").
        with open(base_dir() / LOG_NAME, 'a', encoding='utf-8-sig') as f:
            f.write('[{}] {}\n'.format(stamp, message))
    except OSError:
        pass


# --- Validation --------------------------------------------------------------

def validate_port(value):
    """Renvoie le port (int) ou leve ValueError avec un message en francais."""
    if isinstance(value, bool):
        raise ValueError('Port invalide : entier attendu.')
    if isinstance(value, int):
        port = value
    else:
        text = str(value).strip()
        if not text.isdigit() or not text.isascii():
            raise ValueError('Port invalide : « {} ». Entrez un nombre entier.'.format(text))
        port = int(text)
    if not PORT_MIN <= port <= PORT_MAX:
        raise ValueError('Port invalide : {}. Il doit etre entre {} et {}.'.format(port, PORT_MIN, PORT_MAX))
    return port


def validate_ipv4(value):
    """Renvoie l'adresse IPv4 normalisee ou leve ValueError."""
    text = str(value).strip()
    if not text:
        raise ValueError('Adresse IP manquante.')
    try:
        address = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        raise ValueError('Adresse IP invalide : « {} ». Format attendu : 192.168.1.20'.format(text)) from None
    if address.is_unspecified or address.is_multicast or address == ipaddress.IPv4Address('255.255.255.255'):
        raise ValueError('Adresse IP inutilisable pour se connecter : {}.'.format(text))
    return str(address)


def validate_settings(data):
    """Valide un reglage {role, ip, port} et renvoie une copie normalisee."""
    if not isinstance(data, dict):
        raise ValueError('Reglage invalide : objet JSON attendu.')
    extra = set(data) - SETTINGS_KEYS
    missing = SETTINGS_KEYS - set(data)
    if extra:
        raise ValueError('Reglage invalide : cles inconnues {}.'.format(sorted(extra)))
    if missing:
        raise ValueError('Reglage invalide : cles manquantes {}.'.format(sorted(missing)))
    role = data['role']
    if role not in ROLES:
        raise ValueError('Reglage invalide : role « {} » (attendu host ou join).'.format(role))
    if not isinstance(data['ip'], str):
        raise ValueError('Reglage invalide : ip doit etre une chaine.')
    if not isinstance(data['port'], int):
        raise ValueError('Reglage invalide : port doit etre un entier.')
    port = validate_port(data['port'])
    ip = data['ip'].strip()
    # L'IP est obligatoire pour rejoindre ; pour heberger on garde la derniere saisie.
    if role == ROLE_JOIN or ip:
        ip = validate_ipv4(ip)
    return {'role': role, 'ip': ip, 'port': port}


# --- Reglage sims4mp_settings.json ------------------------------------------

def settings_path(documents):
    return Path(documents) / 'Electronic Arts' / SETTINGS_NAME


def read_settings(path):
    """None si le fichier n'existe pas ; ValueError s'il est invalide."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Lecture impossible de {} : {}'.format(path, exc)) from None
    return validate_settings(data)


def write_settings(path, data):
    """Ecrit le reglage via un fichier temporaire puis renommage atomique."""
    clean = validate_settings(data)
    path = Path(path)
    if not path.parent.is_dir():
        raise LauncherError('Dossier introuvable : {}\n'
                            'Lancez Les Sims 4 une fois pour le creer.'.format(path.parent))
    _write_json_atomic(path, clean)
    return clean


def _write_json_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --- Options du lanceur (depot GitHub) ----------------------------------------
# Fichier a cote du .exe, separe de sims4mp_settings.json (que le mod lira).
# Il ne contient que le depot et le tag : aucun jeton ni mot de passe.

def validate_repo(value):
    """'compte/depot' GitHub, sinon ValueError."""
    text = str(value).strip()
    match = re.fullmatch(r'([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})', text)
    if not match or match.group(2) in ('.', '..'):
        raise ValueError('Depot invalide : « {} ». Format attendu : compte/depot '
                         '(par exemple Flaimeur/sims4mp).'.format(text))
    return text


def validate_tag(value):
    """Tag de Release ('' = derniere version stable), sinon ValueError."""
    text = str(value).strip()
    if text and (not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', text) or set(text) == {'.'}):
        raise ValueError('Tag invalide : « {} ». Exemple : v0.4.0'.format(text))
    return text


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('Options invalides : objet JSON attendu.')
    if set(data) != CONFIG_KEYS:
        raise ValueError('Options invalides : cles attendues {}.'.format(sorted(CONFIG_KEYS)))
    if not isinstance(data['depot'], str) or not isinstance(data['tag'], str):
        raise ValueError('Options invalides : depot et tag doivent etre des chaines.')
    return {'depot': validate_repo(data['depot']), 'tag': validate_tag(data['tag'])}


def manifest_url_for(repo, tag=''):
    """URL du manifeste joint a une Release : 'latest' (stable) ou un tag precis."""
    repo, tag = validate_repo(repo), validate_tag(tag)
    where = 'download/' + tag if tag else 'latest/download'
    return 'https://github.com/{}/releases/{}/{}'.format(repo, where, MANIFEST_NAME)


def config_path():
    return base_dir() / CONFIG_NAME


def read_config(path):
    """None si le fichier n'existe pas ; ValueError s'il est invalide."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Lecture impossible de {} : {}'.format(path, exc)) from None
    return validate_config(data)


def write_config(path, data):
    clean = validate_config(data)
    _write_json_atomic(Path(path), clean)
    return clean


def effective_manifest_url(config):
    """URL construite depuis les options, sinon la constante MANIFEST_URL."""
    if config:
        return manifest_url_for(config['depot'], config['tag'])
    return MANIFEST_URL


# --- IP locales --------------------------------------------------------------

def local_ipv4_addresses():
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    # Interface de la route par defaut : connect() UDP n'envoie aucun paquet.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('192.0.2.1', 9))
            found.insert(0, s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    result = []
    for ip in found:
        address = ipaddress.IPv4Address(ip)
        if address.is_loopback or address.is_link_local or address.is_unspecified:
            continue
        if ip not in result:
            result.append(ip)
    return result


# --- Installation du mod (reprise de sims4mp_launcher.py) -------------------

def documents_dir():
    # SHGetKnownFolderPath gere les Documents deplaces (OneDrive, autre disque...).
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                    ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_ubyte * 8)]

    guid = GUID.from_buffer_copy(uuid.UUID(FOLDERID_DOCUMENTS).bytes_le)
    out = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(out))
    if result != 0 or not out.value:
        raise LauncherError('Impossible de trouver le dossier Documents (code {}).'.format(result))
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def find_mod_source(start=None):
    here = Path(start) if start else base_dir()
    candidates = [here / MOD_FILE]
    # sims4mp\build\ depuis le dossier du .exe et ses parents.
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
    # Le .pyc 3.7 ne se charge pas en 3.12 : on cherche la chaine X.Y.Z
    # (chaine ASCII courte marshal : type 'z', longueur, texte).
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read('sims4mp_hello.pyc')
    except (OSError, KeyError, zipfile.BadZipFile):
        return 'inconnue'
    for match in re.finditer(rb'[\x5a\x7a\xda\xfa]([\x05-\x0f])(\d+\.\d+\.\d+)', data):
        if match.group(1)[0] == len(match.group(2)):
            return match.group(2).decode('ascii')
    return 'inconnue'


def find_mods_dir(documents):
    ea_dir = Path(documents) / 'Electronic Arts'
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


def game_is_running():
    proc = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq {}'.format(GAME_PROCESS), '/NH', '/FO', 'CSV'],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode != 0:
        raise LauncherError('tasklist a echoue (code {}), impossible de verifier '
                            'si le jeu tourne.'.format(proc.returncode))
    output = proc.stdout.decode('oem', errors='replace').lower()
    return '"{}"'.format(GAME_PROCESS.lower()) in output


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def install_mod(source, mods_dir, backup_dir):
    target = Path(mods_dir) / MOD_FILE
    backup = None
    if target.exists():
        # Sauvegarde HORS du dossier Mods : un .ts4script renomme dans Mods
        # (ou un sous-dossier) serait charge par le jeu en double.
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = backup_dir / 'sims4mp_hello_{}.ts4script'.format(stamp)
        n = 2
        while backup.exists():
            backup = backup_dir / 'sims4mp_hello_{}_{}.ts4script'.format(stamp, n)
            n += 1
        shutil.copy2(target, backup)
        if sha256_of(backup) != sha256_of(target):
            raise LauncherError('Sauvegarde de l\'ancien mod incorrecte : {}'.format(backup))

    # Copie dans un fichier .part (ignore par le jeu), verification, puis
    # remplacement atomique : en cas d'echec l'ancien mod reste intact et
    # le .part est supprime.
    part = Path(mods_dir) / ('.' + MOD_FILE + '.part')
    try:
        shutil.copy2(source, part)
        src_size, dst_size = Path(source).stat().st_size, part.stat().st_size
        if src_size != dst_size:
            raise LauncherError('Copie incorrecte : {} octets copies au lieu de {}.\n'
                                'Fichier : {}'.format(dst_size, src_size, target))
        src_hash, dst_hash = sha256_of(source), sha256_of(part)
        if src_hash != dst_hash:
            raise LauncherError('Copie incorrecte : empreinte SHA-256 differente.\n'
                                'Fichier : {}'.format(target))
        os.replace(part, target)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return target, backup, src_hash


def other_copies(mods_dir, target):
    # Autres sims4mp_hello*.ts4script dans Mods : risque de charger deux versions.
    return [p for p in Path(mods_dir).rglob('sims4mp_hello*.ts4script')
            if p.resolve() != Path(target).resolve()]


def run_install(source, documents, backup_dir, is_running=game_is_running):
    """Installation complete. Renvoie la liste des lignes de resume."""
    lines = []
    version = read_mod_version(source)
    lines.append('Mod trouve : {} (version {})'.format(source, version))
    mods_dir = find_mods_dir(documents)
    lines.append('Dossier Mods : {}'.format(mods_dir))
    if is_running():
        raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution), '
                            'puis recommencez.'.format(GAME_PROCESS))
    target, backup, digest = install_mod(source, mods_dir, backup_dir)
    lines.append('Mod copie : {} ({} octets, SHA-256 {}...)'.format(
        target, target.stat().st_size, digest[:16]))
    lines.append('Ancien mod sauvegarde : {}'.format(backup or 'aucun (pas de mod precedent)'))
    for path in other_copies(mods_dir, target):
        lines.append('ATTENTION : autre copie du mod dans Mods, a supprimer : {}'.format(path))
    lines.append('Version du mod installe : {}'.format(version))
    return lines


def launch_game(is_running=game_is_running, start=os.startfile, target=STEAM_GAME_URL):
    """Lance Les Sims 4 (Steam par defaut, ou le .exe detecte pour l'app EA),
    sans attendre le jeu. Refuse s'il tourne deja."""
    if is_running():
        raise LauncherError('Les Sims 4 est deja lance ({} en cours d\'execution).'.format(GAME_PROCESS))
    start(target)
    if target == STEAM_GAME_URL:
        return ['Lancement des Sims 4 via Steam ({}).'.format(STEAM_GAME_URL),
                'Si rien ne s\'ouvre, verifiez que Steam est installe et connecte.']
    return ['Lancement des Sims 4 : {}'.format(target),
            'Si rien ne s\'ouvre, ouvrez l\'app EA et lancez le jeu depuis celle-ci.']


# --- Restauration d'un ancien mod (sims4mp_backups) -------------------------

# Noms crees par install_mod : sims4mp_hello_AAAAMMJJ_HHMMSS[_n].ts4script
BACKUP_PATTERN = re.compile(r'sims4mp_hello_(\d{8})_(\d{6})(?:_\d+)?\.ts4script')


def list_backups(backup_dir):
    """Sauvegardes du mod, de la plus recente a la plus ancienne."""
    folder = Path(backup_dir)
    if not folder.is_dir():
        return []
    found = [p for p in folder.iterdir()
             if BACKUP_PATTERN.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    return sorted(found, key=lambda p: p.name, reverse=True)


def backup_label(path):
    """'21/10/2026 18:36:38 · version 0.4.0 · 37429 octets'"""
    match = BACKUP_PATTERN.fullmatch(Path(path).name)
    day, hour = match.group(1), match.group(2)
    when = '{}/{}/{} {}:{}:{}'.format(day[6:], day[4:6], day[:4], hour[:2], hour[2:4], hour[4:])
    return '{} · version {} · {} octets'.format(when, read_mod_version(path), Path(path).stat().st_size)


def run_restore(backup, documents, backup_dir, is_running=game_is_running):
    """Remet une sauvegarde dans Mods (copie .part puis os.replace), apres
    avoir sauvegarde le mod actuel. Renvoie (lignes, statut_court)."""
    backup, backup_dir = Path(backup), Path(backup_dir)
    # Uniquement un fichier de sims4mp_backups, avec un nom cree par le lanceur.
    if (not BACKUP_PATTERN.fullmatch(backup.name) or not backup.is_file()
            or backup.parent.resolve() != backup_dir.resolve()):
        raise LauncherError('Sauvegarde invalide : {}'.format(backup))
    if not zipfile.is_zipfile(backup):
        raise LauncherError('Sauvegarde illisible (pas une archive .ts4script) : {}'.format(backup.name))
    version = read_mod_version(backup)
    lines = ['Sauvegarde choisie : {} (version {})'.format(backup.name, version)]
    mods_dir = find_mods_dir(documents)
    lines.append('Dossier Mods : {}'.format(mods_dir))
    if is_running():
        raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution), '
                            'puis recommencez.'.format(GAME_PROCESS))
    current = mods_dir / MOD_FILE
    if current.is_file() and sha256_of(current) == sha256_of(backup):
        lines.append('Ce mod est deja en place (fichier identique) : rien a faire.')
        return lines, 'Déjà en place ({})'.format(version)
    target, saved, digest = install_mod(backup, mods_dir, backup_dir)
    lines.append('Mod remis : {} ({} octets, SHA-256 {}...)'.format(
        target, target.stat().st_size, digest[:16]))
    lines.append('Mod remplace sauvegarde : {}'.format(saved or 'aucun (pas de mod en place)'))
    lines.append('Version du mod installe : {}'.format(version))
    return lines, 'Ancien mod restauré ({})'.format(version)


# --- Detection de l'installation du jeu (lecture seule) ---------------------

STEAM_APP_ID = '1222670'
GameInstall = collections.namedtuple('GameInstall', 'kind exe')     # kind : 'steam', 'ea' ou None
GAME_KIND_LABELS = {'steam': 'Steam', 'ea': 'EA app', None: 'introuvable'}
_REGISTRY_HIVES = {'HKCU': 'HKEY_CURRENT_USER', 'HKLM': 'HKEY_LOCAL_MACHINE'}


def read_registry_value(hive, key, name):
    """Valeur texte du registre, ou None. Lecture seule."""
    try:
        import winreg
        root = getattr(winreg, _REGISTRY_HIVES[hive])
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ) as handle:
            value, kind = winreg.QueryValueEx(handle, name)
    except (OSError, ImportError, KeyError):
        return None
    return value if isinstance(value, str) and value.strip() else None


def _vdf_values(text, key):
    """Valeurs d'une cle dans un fichier texte Steam (.vdf / .acf)."""
    raw = re.findall(r'"{}"\s+"((?:[^"\\]|\\.)*)"'.format(re.escape(key)), text, re.IGNORECASE)
    return [re.sub(r'\\(.)', r'\1', value) for value in raw]


def _read_text(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def steam_libraries(reg=read_registry_value):
    """Dossiers de bibliotheques Steam, d'apres le registre et libraryfolders.vdf."""
    roots = [reg('HKCU', r'Software\Valve\Steam', 'SteamPath'),
             reg('HKLM', r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
             reg('HKLM', r'SOFTWARE\Valve\Steam', 'InstallPath')]
    libraries = []
    for root in [r for r in roots if r]:
        root = Path(root)
        vdf = root / 'steamapps' / 'libraryfolders.vdf'
        for folder in [root] + [Path(p) for p in _vdf_values(_read_text(vdf), 'path')]:
            if folder.is_dir() and all(os.path.normcase(str(folder)) != os.path.normcase(str(f))
                                       for f in libraries):
                libraries.append(folder)
    return libraries


def _is_within(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def detect_game(reg=read_registry_value):
    """Cherche TS4_x64.exe : bibliotheques Steam d'abord, puis la cle Maxis
    (installation EA app). Ne lance rien."""
    libraries = steam_libraries(reg)
    for library in libraries:
        acf = library / 'steamapps' / 'appmanifest_{}.acf'.format(STEAM_APP_ID)
        for installdir in _vdf_values(_read_text(acf), 'installdir'):
            if not re.fullmatch(r'[^\\/:*?"<>|]+', installdir) or installdir.strip('. ') == '':
                continue
            exe = library / 'steamapps' / 'common' / installdir / 'Game' / 'Bin' / GAME_PROCESS
            if exe.is_file():
                return GameInstall('steam', exe)
    for key in (r'SOFTWARE\Maxis\The Sims 4', r'SOFTWARE\WOW6432Node\Maxis\The Sims 4'):
        folder = reg('HKLM', key, 'Install Dir')
        if not folder:
            continue
        exe = Path(folder) / 'Game' / 'Bin' / GAME_PROCESS
        if exe.is_file():
            # La cle Maxis existe aussi pour Steam : on classe d'apres l'emplacement.
            steam = any(_is_within(exe, library) for library in libraries)
            return GameInstall('steam' if steam else 'ea', exe)
    return GameInstall(None, None)


def game_target(game):
    """Ce que launch_game ouvre pour l'installation detectee."""
    return str(game.exe) if game.kind == 'ea' else STEAM_GAME_URL


# --- Diagnostic (lecture seule) ----------------------------------------------

JOIN_HELP = ('le port ne répond pas : vérifiez que le host a lancé mp.host '
             'et que le pare-feu autorise le réseau privé')


def decode_console(data):
    """Sortie d'une commande Windows : UTF-8 (netsh recent) sinon page de code OEM."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('oem', errors='replace')


def _run_quiet(args):
    """Commande Windows a arguments fixes (jamais construits depuis le reseau)."""
    proc = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    if proc.returncode != 0:
        raise LauncherError('{} a echoue (code {}).'.format(args[0], proc.returncode))
    return decode_console(proc.stdout)


def listening_pids(port, run=_run_quiet):
    """PID des programmes qui ecoutent deja en TCP sur ce port (netstat, sans ouvrir de port)."""
    port = validate_port(port)
    pids = []
    for line in run(['netstat', '-ano', '-p', 'TCP']).splitlines():
        parts = line.split()
        # TCP <local> <distante> <etat> <pid> ; une ecoute a une adresse distante en :0.
        if (len(parts) == 5 and parts[0].upper() == 'TCP' and parts[1].endswith(':{}'.format(port))
                and parts[2].endswith(':0') and parts[4].isdigit() and int(parts[4]) not in pids):
            pids.append(int(parts[4]))
    return pids


def process_name(pid, run=_run_quiet):
    output = run(['tasklist', '/FI', 'PID eq {}'.format(int(pid)), '/FO', 'CSV', '/NH'])
    match = re.match(r'\s*"([^"]+)"', output)
    return match.group(1) if match else 'PID {}'.format(int(pid))


def firewall_profiles(run=_run_quiet):
    """[(profil, etat)] d'apres netsh advfirewall, quelle que soit la langue de Windows."""
    profiles, current = [], None
    for line in run(['netsh', 'advfirewall', 'show', 'allprofiles', 'state']).splitlines():
        text = line.strip()
        if not text or set(text) <= {'-'}:
            continue
        if text.endswith(':'):
            current = text.rstrip(': ').strip()
        elif current:
            pieces = re.split(r'\s{2,}', text)
            if len(pieces) >= 2:
                profiles.append((current, pieces[-1]))
                current = None
    return profiles


def tcp_probe(ip, port, timeout=3, connect=socket.create_connection):
    """(True, 'Joignable') ou (False, message d'aide). Un seul essai, sans envoyer de donnees."""
    try:
        sock = connect((validate_ipv4(ip), validate_port(port)), timeout=timeout)
    except (OSError, ValueError):
        return False, JOIN_HELP
    sock.close()
    return True, 'Joignable'


def run_diagnostic(documents, is_running=game_is_running, list_ips=local_ipv4_addresses,
                   listeners=listening_pids, proc_name=process_name, firewall=firewall_profiles,
                   probe=tcp_probe):
    """Resume en lecture seule. Le test TCP n'a lieu qu'en mode Rejoindre."""
    lines, warnings = [], 0

    def warn(text):
        nonlocal warnings
        warnings += 1
        lines.append('ATTENTION : ' + text)

    try:
        mods_dir = find_mods_dir(documents)
        mod = mods_dir / MOD_FILE
        if mod.is_file():
            lines.append('Mod : present, version {} ({})'.format(read_mod_version(mod), mod))
        else:
            warn('mod absent du dossier Mods ({})'.format(mods_dir))
    except LauncherError as exc:
        warn('dossier Mods : {}'.format(str(exc).splitlines()[0]))

    try:
        lines.append('Jeu : {}'.format('ouvert' if is_running() else 'ferme'))
    except LauncherError as exc:
        warn(str(exc))

    try:
        settings = read_settings(settings_path(documents))
    except ValueError as exc:
        settings = None
        warn('reglage invalide : {}'.format(exc))
    else:
        if settings is None:
            warn('aucun reglage enregistre (page Connexion)')
        else:
            lines.append('Reglage : {}, IP {}, port {}'.format(
                'Heberger' if settings['role'] == ROLE_HOST else 'Rejoindre',
                settings['ip'] or '-', settings['port']))

    ips = list_ips()
    lines.append('IP locales : {}'.format(', '.join(ips) if ips else 'aucune'))

    if settings and settings['role'] == ROLE_HOST:
        try:
            pids = listeners(settings['port'])
        except (LauncherError, OSError, subprocess.SubprocessError) as exc:
            warn('ecoute du port {} : verification impossible ({})'.format(settings['port'], exc))
        else:
            if not pids:
                lines.append('Port {} : libre (aucune application n\'ecoute)'.format(settings['port']))
            for pid in pids:
                name = proc_name(pid)
                if name.lower() == GAME_PROCESS.lower():
                    lines.append('Port {} : ecoute par Les Sims 4 (mp.host actif)'.format(settings['port']))
                else:
                    warn('port {} deja utilise par {} (PID {})'.format(settings['port'], name, pid))

    try:
        profiles = firewall()
    except (LauncherError, OSError, subprocess.SubprocessError) as exc:
        warn('pare-feu : etat illisible ({})'.format(exc))
    else:
        for profile, state in profiles:
            lines.append('Pare-feu, {} : {}'.format(profile, state))
        if not profiles:
            warn('pare-feu : etat illisible')

    if settings and settings['role'] == ROLE_JOIN:
        ok, message = probe(settings['ip'], settings['port'])
        target = '{}:{}'.format(settings['ip'], settings['port'])
        if ok:
            lines.append('Hote {} : {}'.format(target, message))
        else:
            warn('hote {} : {}'.format(target, message))

    if warnings:
        lines.append('Resultat : {} point(s) a verifier.'.format(warnings))
        return lines, 'Diagnostic : {} point(s) à vérifier'.format(warnings)
    lines.append('Resultat : tout est en ordre.')
    return lines, 'Diagnostic : tout est en ordre'


# --- Mise a jour depuis une Release GitHub ----------------------------------

def require_https(url, what='URL'):
    if not isinstance(url, str):
        raise LauncherError('{} invalide.'.format(what))
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme != 'https' or not parts.hostname:
        raise LauncherError('{} refusee (HTTPS obligatoire) : {}'.format(what, url))
    if parts.username or parts.password:
        raise LauncherError('{} refusee (identifiants dans l\'URL) : {}'.format(what, url))
    return url.strip()


def validate_manifest(data):
    """Valide le manifeste et renvoie une copie normalisee, sinon LauncherError."""
    if not isinstance(data, dict):
        raise LauncherError('Manifeste invalide : objet JSON attendu.')
    extra, missing = set(data) - MANIFEST_KEYS, MANIFEST_KEYS - set(data)
    if extra:
        raise LauncherError('Manifeste invalide : cles inconnues {}.'.format(sorted(extra)))
    if missing:
        raise LauncherError('Manifeste invalide : cles manquantes {}.'.format(sorted(missing)))
    version = data['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise LauncherError('Manifeste invalide : version « {} » (format X.Y.Z).'.format(version))
    if data['fichier'] != MOD_FILE:
        raise LauncherError('Manifeste invalide : fichier « {} » (attendu {}).'.format(data['fichier'], MOD_FILE))
    url = require_https(data['url'], 'URL de telechargement')
    sha = data['sha256']
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', sha):
        raise LauncherError('Manifeste invalide : sha256 doit faire 64 caracteres hexadecimaux.')
    size = data['taille']
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_MOD_SIZE:
        raise LauncherError('Manifeste invalide : taille {} (1 a {} octets).'.format(size, MAX_MOD_SIZE))
    if data['statut'] not in (STATUS_STABLE, STATUS_TEST):
        raise LauncherError('Manifeste invalide : statut « {} » (stable ou test).'.format(data['statut']))
    return {'version': version, 'fichier': MOD_FILE, 'url': url, 'sha256': sha.lower(),
            'taille': size, 'statut': data['statut']}


class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Suit les redirections (GitHub -> objects.githubusercontent.com) en HTTPS seulement."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_https(newurl, 'Redirection')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_https_opener():
    # Pas de HTTPHandler, FileHandler ni FTPHandler : seul https:// est ouvrable.
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.UnknownHandler(),      # http://, file:// -> URLError
                    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                    HTTPSOnlyRedirectHandler(),
                    urllib.request.HTTPDefaultErrorHandler(),
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


def read_limited(url, out, max_size, timeout, opener):
    """Telecharge url dans le fichier binaire out. Renvoie le nombre d'octets.

    Limites : max_size octets et timeout secondes au total (pas seulement par
    lecture). L'appelant verifie le schema de l'URL.
    """
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    total = 0
    try:
        with opener.open(request, timeout=timeout) as response:
            length = response.headers.get('Content-Length')
            if length is not None and length.strip().isdigit() and int(length) > max_size:
                raise LauncherError('Fichier trop gros : {} octets (maximum {}).'.format(length, max_size))
            # read1 rend ce qui est disponible : le delai total est verifie
            # meme si le serveur envoie au compte-gouttes.
            read = getattr(response, 'read1', response.read)
            while True:
                if time.monotonic() > deadline:
                    raise LauncherError('Telechargement trop long (plus de {} s).'.format(timeout))
                block = read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > max_size:
                    raise LauncherError('Fichier trop gros : plus de {} octets.'.format(max_size))
                out.write(block)
    except LauncherError:
        raise
    except urllib.error.HTTPError as exc:
        raise LauncherError('Telechargement refuse par le serveur (HTTP {}) : {}'.format(exc.code, url)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise LauncherError('Telechargement impossible : {} ({})'.format(url, reason)) from None
    return total


def fetch_manifest(url, opener, timeout=DOWNLOAD_TIMEOUT):
    url = require_https(url, 'URL du manifeste')
    buffer = _BytesSink()
    read_limited(url, buffer, MAX_MANIFEST_SIZE, timeout, opener)
    try:
        data = json.loads(bytes(buffer.data).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LauncherError('Manifeste illisible (JSON invalide) : {}'.format(exc)) from None
    return validate_manifest(data)


class _BytesSink:
    def __init__(self):
        self.data = bytearray()

    def write(self, block):
        self.data += block


def download_mod(manifest, temp_dir, opener, timeout=DOWNLOAD_TIMEOUT):
    """Telecharge le mod dans un fichier temporaire de temp_dir et le verifie.

    Renvoie le chemin du fichier verifie ; le supprime en cas d'echec.
    """
    url = require_https(manifest['url'], 'URL de telechargement')
    fd, tmp = tempfile.mkstemp(prefix='sims4mp_download_', suffix='.part', dir=str(temp_dir))
    tmp = Path(tmp)
    try:
        with os.fdopen(fd, 'wb') as out:
            size = read_limited(url, out, min(manifest['taille'], MAX_MOD_SIZE), timeout, opener)
        if size != manifest['taille']:
            raise LauncherError('Taille incorrecte : {} octets recus, {} attendus.'.format(size, manifest['taille']))
        digest = sha256_of(tmp)
        if digest != manifest['sha256']:
            raise LauncherError('SHA-256 incorrect : fichier telecharge refuse.\n'
                                'Recu    : {}\nAttendu : {}'.format(digest, manifest['sha256']))
        if not zipfile.is_zipfile(tmp):
            raise LauncherError('Le fichier telecharge n\'est pas une archive .ts4script valide.')
        found = read_mod_version(tmp)
        if found != manifest['version']:
            raise LauncherError('Version incoherente : le fichier contient {}, le manifeste annonce {}.'.format(
                found, manifest['version']))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return tmp


def version_tuple(version):
    """'0.4.0' -> (0, 4, 0) ; None si la version est illisible."""
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        return None
    return tuple(int(part) for part in version.split('.'))


def run_update(manifest_url, documents, backup_dir, temp_dir, allow_test=False,
               is_running=game_is_running, opener=None, timeout=DOWNLOAD_TIMEOUT,
               allow_downgrade=False):
    """Mise a jour complete depuis le manifeste. Renvoie (lignes, statut_court)."""
    if not isinstance(manifest_url, str) or manifest_url.strip() in ('', 'À_REMPLIR'):
        raise LauncherError('URL du manifeste non configuree : renseignez le depot GitHub '
                            'dans la page OPTIONS.')
    opener = opener or make_https_opener()
    lines = []
    manifest = fetch_manifest(manifest_url, opener, timeout)
    lines.append('Manifeste : version {}, statut {}, {} octets.'.format(
        manifest['version'], manifest['statut'], manifest['taille']))
    if manifest['statut'] != STATUS_STABLE and not allow_test:
        raise LauncherError('Version {} en statut « {} » : non installee.\n'
                            'Cochez « Installer une version de test » pour l\'accepter.'.format(
                                manifest['version'], manifest['statut']))
    mods_dir = find_mods_dir(documents)
    lines.append('Dossier Mods : {}'.format(mods_dir))
    if is_running():
        raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution), '
                            'puis recommencez.'.format(GAME_PROCESS))
    current = mods_dir / MOD_FILE
    if current.is_file() and sha256_of(current) == manifest['sha256']:
        lines.append('Version {} deja installee (fichier identique) : rien a faire.'.format(manifest['version']))
        return lines, 'Déjà à jour ({})'.format(manifest['version'])
    if current.is_file():
        installed = read_mod_version(current)
        lines.append('Version installee : {}'.format(installed))
        old, new = version_tuple(installed), version_tuple(manifest['version'])
        # Un retour en arriere peut reintroduire un bug corrige : refus par defaut.
        if old is not None and new < old and not allow_downgrade:
            raise LauncherError('Version {} plus ancienne que la version installee {} : non installee.\n'
                                'Cochez « Autoriser le retour a une version plus ancienne » '
                                'pour l\'accepter.'.format(manifest['version'], installed))
        if old is None:
            lines.append('Version installee illisible : comparaison impossible, mise a jour autorisee.')

    tmp = download_mod(manifest, temp_dir, opener, timeout)
    try:
        lines.append('Telechargement verifie (taille et SHA-256).')
        # Le jeu a pu etre lance pendant le telechargement.
        if is_running():
            raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution), '
                                'puis recommencez.'.format(GAME_PROCESS))
        target, backup, digest = install_mod(tmp, mods_dir, backup_dir)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    lines.append('Mod copie : {} ({} octets, SHA-256 {}...)'.format(
        target, target.stat().st_size, digest[:16]))
    lines.append('Ancien mod sauvegarde : {}'.format(backup or 'aucun (pas de mod precedent)'))
    for path in other_copies(mods_dir, target):
        lines.append('ATTENTION : autre copie du mod dans Mods, a supprimer : {}'.format(path))
    lines.append('Version du mod installe : {}{}'.format(
        manifest['version'], ' (version de test)' if manifest['statut'] == STATUS_TEST else ''))
    return lines, 'Mod mis à jour ({})'.format(manifest['version'])


# --- Fenetre -----------------------------------------------------------------

FONT_FAMILY = 'Segoe UI'
FONT_SIZE = 10
MONO_FAMILY = 'Consolas'
PAD = 12                      # marge exterieure et entre les cadres
GAP = 6                       # espacement entre les lignes d'un cadre
SIDEBAR_WIDTH = 200

# Palette claire et sobre, aux couleurs des Sims 4 : panneaux blancs,
# bleu des boutons du jeu, vert du losange pour les succes.
COLOR_BG = '#f3f6fa'          # fond de la zone de contenu
COLOR_SIDEBAR = '#ffffff'
COLOR_CARD = '#ffffff'
COLOR_BORDER = '#e2e8f0'
COLOR_FIELD = '#f8fafc'       # champs de saisie, journal
COLOR_BUTTON = '#f1f5f9'
COLOR_BUTTON_HOVER = '#e2e8f0'
COLOR_TEXT = '#0f172a'
COLOR_MUTED = '#64748b'
COLOR_ACCENT = '#1f6fd6'      # bleu Sims
COLOR_ACCENT_HOVER = '#185fc0'
COLOR_ACCENT_TEXT = '#ffffff'
COLOR_NAV_ACTIVE = '#eaf2fd'
COLOR_PLUMBOB = '#45c745'
COLOR_OK = '#1e9e4a'
COLOR_ERROR = '#d93025'

LABEL_LAN = 'Wi-Fi/Ethernet'
LABEL_VIRTUAL = 'Virtuel'
LABEL_UNKNOWN = 'inconnu'
LAN_PREFIXES = ('192.168.1.',)
# Plages des cartes virtuelles connues (VMware, Wi-Fi Direct / partage de connexion).
VIRTUAL_PREFIXES = ('192.168.147.', '192.168.49.')


# Aide du bouton « ? » : 10 lignes au plus (le guide complet est launcher/README.md).
HELP_TEXT = '\n'.join([
    '1. Gardez l\'exe et sims4mp_hello.ts4script dans le même dossier (pas dans Program Files).',
    '2. Mod → Installer le mod, jeu fermé. L\'ancien mod est sauvegardé.',
    '3. Hôte : Connexion → Héberger → Enregistrer, puis copiez et envoyez votre IP.',
    '4. Invité : Connexion → Rejoindre, IP et port de l\'hôte → Enregistrer.',
    '5. Lancer Les Sims 4. En jeu (Ctrl+Maj+C) : l\'hôte tape mp.host, l\'invité mp.join <ip>.',
    '6. Pare-feu : n\'autorisez le jeu que sur les réseaux privés.',
    '7. Un souci ? Options → Diagnostic, puis Ouvrir le journal.',
    '8. Revenir en arrière : Mod → Restaurer l\'ancien mod.',
    'Projet de fan, non affilié à EA. Gardez une copie de vos sauvegardes.',
])


def ip_label(ip):
    if ip.startswith(VIRTUAL_PREFIXES):
        return LABEL_VIRTUAL
    if ip.startswith(LAN_PREFIXES):
        return LABEL_LAN
    return LABEL_UNKNOWN


def primary_ip(ips):
    """Premiere IP qui n'est pas une carte virtuelle, sinon None."""
    for ip in ips:
        if ip_label(ip) != LABEL_VIRTUAL:
            return ip
    return None


def apply_style(root):
    """Theme sombre construit sur 'clam' (le seul theme ttk dont on peut
    changer toutes les couleurs). Renvoie l'objet Style."""
    from tkinter import font as tkfont
    from tkinter import ttk
    style = ttk.Style(root)
    style.theme_use('clam')
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont',
                 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
        try:
            tkfont.nametofont(name, root=root).configure(family=FONT_FAMILY, size=FONT_SIZE)
        except Exception:
            pass
    bold = (FONT_FAMILY, FONT_SIZE, 'bold')
    root.configure(background=COLOR_BG)
    flat = dict(bordercolor=COLOR_BORDER, lightcolor=COLOR_CARD, darkcolor=COLOR_CARD)

    # Par defaut, frames et etiquettes sont posees sur une carte.
    style.configure('.', background=COLOR_CARD, foreground=COLOR_TEXT, focuscolor=COLOR_ACCENT,
                    troughcolor=COLOR_FIELD, selectbackground=COLOR_ACCENT,
                    selectforeground=COLOR_ACCENT_TEXT, **flat)
    style.configure('TFrame', background=COLOR_CARD)
    style.configure('Card.TFrame', background=COLOR_CARD, relief='solid', borderwidth=1,
                    bordercolor=COLOR_BORDER)
    style.configure('Bg.TFrame', background=COLOR_BG)
    style.configure('Side.TFrame', background=COLOR_SIDEBAR)
    style.configure('NavBarOn.TFrame', background=COLOR_ACCENT)
    style.configure('NavBarOff.TFrame', background=COLOR_SIDEBAR)

    style.configure('TLabel', background=COLOR_CARD, foreground=COLOR_TEXT)
    style.configure('Primary.TLabel', font=bold)
    style.configure('Muted.TLabel', foreground=COLOR_MUTED)
    style.configure('CardTitle.TLabel', foreground=COLOR_TEXT, font=(FONT_FAMILY, 11, 'bold'))
    style.configure('SideTitle.TLabel', background=COLOR_SIDEBAR, foreground=COLOR_TEXT,
                    font=(FONT_FAMILY, 13, 'bold'))
    style.configure('SideSub.TLabel', background=COLOR_SIDEBAR, foreground=COLOR_MUTED,
                    font=(FONT_FAMILY, 9))
    style.configure('Side.TLabel', background=COLOR_SIDEBAR)
    style.configure('SideSection.TLabel', background=COLOR_SIDEBAR, foreground='#94a3b8',
                    font=(FONT_FAMILY, 8, 'bold'))
    style.configure('SideMuted.TLabel', background=COLOR_SIDEBAR, foreground=COLOR_MUTED,
                    font=(FONT_FAMILY, 8))
    status = dict(background=COLOR_BG, padding=(PAD + 6, 6))
    style.configure('Status.TLabel', foreground=COLOR_MUTED, **status)
    style.configure('StatusOk.TLabel', foreground=COLOR_OK, **status)
    style.configure('StatusError.TLabel', foreground=COLOR_ERROR, **status)

    # Boutons
    style.configure('TButton', background=COLOR_BUTTON, foreground=COLOR_TEXT, padding=(14, 7),
                    borderwidth=1, bordercolor=COLOR_BORDER, lightcolor=COLOR_BUTTON,
                    darkcolor=COLOR_BUTTON, font=(FONT_FAMILY, FONT_SIZE))
    style.map('TButton',
              background=[('disabled', COLOR_CARD), ('pressed', COLOR_BORDER), ('active', COLOR_BUTTON_HOVER)],
              foreground=[('disabled', COLOR_MUTED)],
              lightcolor=[('active', COLOR_BUTTON_HOVER)], darkcolor=[('active', COLOR_BUTTON_HOVER)])
    style.configure('Accent.TButton', background=COLOR_ACCENT, foreground=COLOR_ACCENT_TEXT,
                    bordercolor=COLOR_ACCENT, lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT, font=bold)
    style.map('Accent.TButton',
              background=[('disabled', COLOR_BUTTON), ('active', COLOR_ACCENT_HOVER)],
              foreground=[('disabled', COLOR_MUTED)],
              lightcolor=[('active', COLOR_ACCENT_HOVER)], darkcolor=[('active', COLOR_ACCENT_HOVER)])
    style.configure('Help.TButton', background=COLOR_SIDEBAR, foreground=COLOR_MUTED, padding=(4, 1),
                    bordercolor=COLOR_BORDER, lightcolor=COLOR_SIDEBAR, darkcolor=COLOR_SIDEBAR, font=bold)
    style.map('Help.TButton', background=[('active', COLOR_NAV_ACTIVE)], foreground=[('active', COLOR_ACCENT)],
              bordercolor=[('active', COLOR_ACCENT)])
    # Bouton Jouer : vert du losange, pour le distinguer des actions bleues.
    style.configure('Play.TButton', background='#2fa83a', foreground='#ffffff', padding=(14, 10),
                    bordercolor='#2fa83a', lightcolor='#2fa83a', darkcolor='#2fa83a', font=bold)
    style.map('Play.TButton',
              background=[('disabled', COLOR_BUTTON), ('active', '#27932f')],
              foreground=[('disabled', COLOR_MUTED)],
              bordercolor=[('disabled', COLOR_BORDER), ('active', '#27932f')],
              lightcolor=[('active', '#27932f')], darkcolor=[('active', '#27932f')])
    nav = dict(background=COLOR_SIDEBAR, foreground=COLOR_MUTED, anchor='w', padding=(14, 9),
               borderwidth=0, bordercolor=COLOR_SIDEBAR, lightcolor=COLOR_SIDEBAR,
               darkcolor=COLOR_SIDEBAR, font=(FONT_FAMILY, FONT_SIZE))
    style.configure('Nav.TButton', **nav)
    style.map('Nav.TButton', background=[('active', COLOR_BUTTON)], foreground=[('active', COLOR_TEXT)],
              lightcolor=[('active', COLOR_BUTTON)], darkcolor=[('active', COLOR_BUTTON)],
              bordercolor=[('active', COLOR_BUTTON)])
    style.configure('NavActive.TButton', **dict(nav, background=COLOR_NAV_ACTIVE, foreground=COLOR_ACCENT,
                                                  bordercolor=COLOR_NAV_ACTIVE, lightcolor=COLOR_NAV_ACTIVE,
                                                  darkcolor=COLOR_NAV_ACTIVE, font=bold))
    style.map('NavActive.TButton', background=[('active', COLOR_NAV_ACTIVE)],
              bordercolor=[('active', COLOR_NAV_ACTIVE)])

    # Choix Heberger / Rejoindre : boutons radio sans indicateur, en bascule.
    style.layout('Toggle.TRadiobutton', [('Radiobutton.padding', {'sticky': 'nswe', 'children': [
        ('Radiobutton.label', {'sticky': 'nswe'})]})])
    style.configure('Toggle.TRadiobutton', background=COLOR_BUTTON, foreground=COLOR_MUTED,
                    padding=(20, 7), anchor='center', font=(FONT_FAMILY, FONT_SIZE))
    style.map('Toggle.TRadiobutton',
              background=[('selected', COLOR_ACCENT), ('active', COLOR_BUTTON_HOVER)],
              foreground=[('selected', COLOR_ACCENT_TEXT), ('active', COLOR_TEXT)])

    # Cases a cocher
    style.configure('TCheckbutton', background=COLOR_CARD, foreground=COLOR_TEXT,
                    indicatorbackground=COLOR_FIELD, indicatorforeground=COLOR_ACCENT_TEXT,
                    upperbordercolor='#94a3b8', lowerbordercolor='#94a3b8', indicatormargin=(0, 0, 8, 0))
    style.map('TCheckbutton', background=[('active', COLOR_CARD)],
              indicatorbackground=[('selected', COLOR_ACCENT), ('active', COLOR_BUTTON)])

    # Champs de saisie
    style.configure('TEntry', fieldbackground=COLOR_FIELD, foreground=COLOR_TEXT,
                    insertcolor=COLOR_TEXT, bordercolor=COLOR_BORDER, lightcolor=COLOR_FIELD,
                    darkcolor=COLOR_FIELD, padding=(8, 5))
    style.map('TEntry', fieldbackground=[('disabled', '#eef2f6')], foreground=[('disabled', COLOR_MUTED)],
              bordercolor=[('focus', COLOR_ACCENT)], lightcolor=[('focus', COLOR_FIELD)])

    style.configure('TCombobox', fieldbackground=COLOR_FIELD, foreground=COLOR_TEXT, background=COLOR_BUTTON,
                    bordercolor=COLOR_BORDER, lightcolor=COLOR_FIELD, darkcolor=COLOR_FIELD,
                    arrowcolor=COLOR_MUTED, padding=(8, 5))
    style.map('TCombobox', fieldbackground=[('readonly', COLOR_FIELD), ('disabled', '#eef2f6')],
              foreground=[('disabled', COLOR_MUTED)], bordercolor=[('focus', COLOR_ACCENT)],
              selectbackground=[('readonly', COLOR_FIELD)], selectforeground=[('readonly', COLOR_TEXT)])
    root.option_add('*TCombobox*Listbox.font', (FONT_FAMILY, FONT_SIZE))
    root.option_add('*TCombobox*Listbox.selectBackground', COLOR_ACCENT)
    style.configure('Vertical.TScrollbar', background='#cbd5e1', troughcolor=COLOR_FIELD,
                    bordercolor=COLOR_FIELD, arrowcolor=COLOR_MUTED, lightcolor='#cbd5e1',
                    darkcolor='#cbd5e1', arrowsize=12)
    style.map('Vertical.TScrollbar', background=[('active', '#94a3b8')])
    style.configure('TSeparator', background=COLOR_BORDER)
    return style


def draw_logo(canvas, cx, top, scale=1.0):
    """Losange vert a facettes, facon plumbob (dessin original du lanceur)."""
    w, h_up, h_down, depth = 18 * scale, 30 * scale, 44 * scale, 7 * scale
    mid = top + h_up
    left, right, front = (cx - w, mid), (cx + w, mid), (cx, mid + depth)
    apex, bottom = (cx, top), (cx, mid + h_down)
    for points, color in [((apex, left, front), '#9be86f'), ((apex, front, right), COLOR_PLUMBOB),
                          ((left, front, bottom), '#37a83a'), ((front, right, bottom), '#26872d')]:
        canvas.create_polygon(*[c for p in points for c in p], fill=color, outline='')


def load_plumbob(root):
    """Plumbob officiel embarque (sims4mp_assets.py) ; None si indisponible,
    l'en-tete utilise alors le losange dessine par draw_logo."""
    try:
        import tkinter as tk
        from sims4mp_assets import PLUMBOB_PNG
        return tk.PhotoImage(master=root, data=PLUMBOB_PNG, format='png')
    except Exception:
        log('Plumbob embarque indisponible, losange dessine utilise :\n' + traceback.format_exc())
        return None


def center_window(window, width=None, height=None):
    window.update_idletasks()
    width = width or max(window.winfo_width(), window.winfo_reqwidth())
    height = height or max(window.winfo_height(), window.winfo_reqheight())
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 3)
    window.geometry('{}x{}+{}+{}'.format(width, height, x, y))


class LauncherApp:
    def __init__(self, root, documents=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.documents = documents
        self.results = queue.Queue()
        self.installing = False
        self.ips = []

        apply_style(root)
        root.title('Sims4MP - Lanceur')
        root.minsize(960, 620)
        root.report_callback_exception = self._on_callback_error

        # Barre laterale : logo, titre, navigation.
        side = ttk.Frame(root, style='Side.TFrame', width=SIDEBAR_WIDTH)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        header = ttk.Frame(side, style='Side.TFrame')
        header.pack(fill='x', padx=PAD + 6, pady=(PAD + 10, 2 * PAD + 4))
        self.logo_image = load_plumbob(root)
        if self.logo_image is not None:
            # Garder la reference : sans elle, tkinter efface l'image.
            ttk.Label(header, image=self.logo_image, style='Side.TLabel').pack(side='left')
        else:
            logo = tk.Canvas(header, width=30, height=48, background=COLOR_SIDEBAR, highlightthickness=0)
            logo.pack(side='left')
            draw_logo(logo, 15, 2, scale=0.6)
        titles = ttk.Frame(header, style='Side.TFrame')
        titles.pack(side='left', padx=(GAP + 4, 0))
        ttk.Label(titles, text='Sims4MP', style='SideTitle.TLabel').pack(anchor='w')
        ttk.Label(titles, text='Lanceur multijoueur', style='SideSub.TLabel').pack(anchor='w')

        menu_row = ttk.Frame(side, style='Side.TFrame')
        menu_row.pack(fill='x', padx=(PAD + 8, PAD), pady=(0, GAP))
        ttk.Label(menu_row, text='MENU', style='SideSection.TLabel').pack(side='left')
        self.help_button = ttk.Button(menu_row, text='?', style='Help.TButton', width=2, takefocus=False,
                                      command=self._show_help)
        self.help_button.pack(side='right')
        self.nav = {}
        for key, text in [('connexion', 'Connexion'), ('mod', 'Mod'), ('options', 'Options')]:
            row = ttk.Frame(side, style='Side.TFrame')
            row.pack(fill='x', padx=PAD - 2, pady=1)
            bar = ttk.Frame(row, style='NavBarOff.TFrame', width=3)
            bar.pack(side='left', fill='y')
            button = ttk.Button(row, text=text, style='Nav.TButton', takefocus=False,
                                command=lambda k=key: self._show_page(k))
            button.pack(side='left', fill='x', expand=True)
            self.nav[key] = (bar, button)

        ttk.Label(side, text='Projet de fan, non affilié à EA', style='SideMuted.TLabel').pack(
            side='bottom', anchor='w', padx=PAD + 8, pady=(GAP, PAD + 4))
        quit_row = ttk.Frame(side, style='Side.TFrame')
        quit_row.pack(side='bottom', fill='x', padx=PAD - 2)
        # Explication sous le bouton Jouer quand le jeu est introuvable (vide sinon).
        self.play_hint = ttk.Label(side, style='SideMuted.TLabel', wraplength=SIDEBAR_WIDTH - 2 * PAD - 4,
                                   justify='left')
        self.play_hint.pack(side='bottom', fill='x', padx=PAD + 2, pady=(0, GAP))
        self.play_button = ttk.Button(side, text='▶  Lancer Les Sims 4', style='Play.TButton',
                                      command=self._launch_game)
        self.play_button.pack(side='bottom', fill='x', padx=PAD + 2, pady=(0, GAP))
        ttk.Frame(quit_row, style='NavBarOff.TFrame', width=3).pack(side='left', fill='y')
        ttk.Button(quit_row, text='Quitter', style='Nav.TButton', takefocus=False,
                   command=root.destroy).pack(side='left', fill='x', expand=True)
        tk.Frame(root, width=1, background=COLOR_BORDER).pack(side='left', fill='y')

        # Zone de droite : barre d'etat en bas, contenu au-dessus.
        right = ttk.Frame(root, style='Bg.TFrame')
        right.pack(side='left', fill='both', expand=True)
        status_bar = ttk.Frame(right, style='Bg.TFrame')
        status_bar.pack(side='bottom', fill='x')
        # A droite : l'installation du jeu detectee au demarrage.
        self.game_status = ttk.Label(status_bar, style='Status.TLabel', anchor='e')
        self.game_status.pack(side='right')
        self.status = ttk.Label(status_bar, text='Prêt', style='Status.TLabel', anchor='w')
        self.status.pack(side='left', fill='x', expand=True)
        ttk.Separator(right, orient='horizontal').pack(side='bottom', fill='x')

        content = ttk.Frame(right, style='Bg.TFrame', padding=PAD + 6)
        content.pack(fill='both', expand=True)
        content.columnconfigure(0, weight=3, uniform='col')
        content.columnconfigure(1, weight=2, uniform='col')
        content.rowconfigure(0, weight=1)

        pages = ttk.Frame(content, style='Bg.TFrame')
        pages.grid(row=0, column=0, sticky='nsew', padx=(0, PAD + 6))
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)
        self.pages = {key: ttk.Frame(pages, style='Bg.TFrame') for key in self.nav}
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky='nsew')
            page.columnconfigure(0, weight=1)

        # Page CONNEXION : mode, puis adresse et port.
        page = self.pages['connexion']
        self.role = tk.StringVar(value=ROLE_HOST)
        mode = self._card(page, 'Mode de jeu', row=0)
        toggles = ttk.Frame(mode)
        toggles.grid(row=1, column=0, sticky='w')
        ttk.Radiobutton(toggles, text='Héberger', value=ROLE_HOST, variable=self.role,
                        style='Toggle.TRadiobutton', command=self._on_role).pack(side='left')
        ttk.Radiobutton(toggles, text='Rejoindre', value=ROLE_JOIN, variable=self.role,
                        style='Toggle.TRadiobutton', command=self._on_role).pack(side='left', padx=(GAP, 0))

        conn = self._card(page, 'Connexion', row=1)
        conn.columnconfigure(1, weight=1)
        ttk.Label(conn, text='IP locales', style='Muted.TLabel').grid(
            row=1, column=0, sticky='nw', pady=GAP, padx=(0, PAD))
        self.ip_list = ttk.Frame(conn)
        self.ip_list.grid(row=1, column=1, sticky='nw', pady=GAP)
        self.copy_button = ttk.Button(conn, text='Copier l\'IP principale', command=self._copy_ips)
        self.copy_button.grid(row=2, column=1, sticky='w', pady=(0, GAP))

        ttk.Label(conn, text='IP de l\'hôte', style='Muted.TLabel').grid(
            row=3, column=0, sticky='w', pady=GAP, padx=(0, PAD))
        line = ttk.Frame(conn)
        line.grid(row=3, column=1, sticky='w', pady=GAP)
        self.ip = tk.StringVar()
        self.ip_entry = ttk.Entry(line, textvariable=self.ip, width=18)
        self.ip_entry.pack(side='left')
        self.ip_hint = ttk.Label(line, style='Muted.TLabel')
        self.ip_hint.pack(side='left', padx=(PAD, 0))

        ttk.Label(conn, text='Port', style='Muted.TLabel').grid(
            row=4, column=0, sticky='w', pady=GAP, padx=(0, PAD))
        line = ttk.Frame(conn)
        line.grid(row=4, column=1, sticky='w', pady=GAP)
        self.port = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(line, textvariable=self.port, width=8).pack(side='left')
        ttk.Label(line, text='{} à {}'.format(PORT_MIN, PORT_MAX), style='Muted.TLabel').pack(
            side='left', padx=(PAD, 0))
        ttk.Button(conn, text='Enregistrer le réglage', style='Accent.TButton', command=self._save).grid(
            row=5, column=0, columnspan=2, sticky='ew', pady=(PAD, 0))

        # Page MOD : installation locale et mise a jour.
        page = self.pages['mod']
        mod = self._card(page, 'Mod Sims4MP', row=0)
        mod.columnconfigure(0, weight=1)
        ttk.Label(mod, style='Muted.TLabel', wraplength=360, justify='left',
                  text='Installe sims4mp_hello.ts4script dans le dossier Mods. L\'ancien mod est '
                       'sauvegardé, et le jeu doit être fermé.').grid(row=1, column=0, sticky='w')
        self.install_button = ttk.Button(mod, text='Installer le mod', command=self._install)
        self.install_button.grid(row=2, column=0, sticky='ew', pady=(PAD, 0))

        update = self._card(page, 'Mise à jour', row=1)
        update.columnconfigure(0, weight=1)
        ttk.Label(update, style='Muted.TLabel', wraplength=360, justify='left',
                  text='Télécharge la dernière version publiée sur GitHub, vérifiée par '
                       'taille et SHA-256.').grid(row=1, column=0, sticky='w')
        self.update_button = ttk.Button(update, text='Mettre à jour depuis GitHub',
                                        style='Accent.TButton', command=self._update)
        self.update_button.grid(row=2, column=0, sticky='ew', pady=(PAD, GAP))
        self.allow_test = tk.BooleanVar(value=False)
        ttk.Checkbutton(update, text='Installer une version de test', variable=self.allow_test).grid(
            row=3, column=0, sticky='w', pady=(GAP, 0))
        self.allow_downgrade = tk.BooleanVar(value=False)
        ttk.Checkbutton(update, text='Autoriser le retour à une version plus ancienne',
                        variable=self.allow_downgrade).grid(row=4, column=0, sticky='w', pady=(GAP, 0))

        restore = self._card(page, 'Restaurer l\'ancien mod', row=2)
        restore.columnconfigure(0, weight=1)
        self.backup_choice = tk.StringVar()
        self.backup_box = ttk.Combobox(restore, textvariable=self.backup_choice, state='readonly')
        self.backup_box.grid(row=1, column=0, sticky='ew', padx=(0, GAP))
        self.restore_button = ttk.Button(restore, text='Restaurer', command=self._restore)
        self.restore_button.grid(row=1, column=1, sticky='e')
        self.backups = []              # chemins, dans l'ordre de la liste deroulante

        # Page OPTIONS : depot GitHub d'ou vient la mise a jour, et dossiers.
        page = self.pages['options']
        gh = self._card(page, 'GitHub', row=0)
        gh.columnconfigure(1, weight=1)
        ttk.Label(gh, text='Dépôt', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=GAP, padx=(0, PAD))
        self.repo = tk.StringVar()
        ttk.Entry(gh, textvariable=self.repo, width=30).grid(row=1, column=1, sticky='w', pady=GAP)
        ttk.Label(gh, text='compte/dépôt, par exemple Flaimeur/sims4mp', style='Muted.TLabel').grid(
            row=2, column=1, sticky='w')

        ttk.Label(gh, text='Version', style='Muted.TLabel').grid(row=3, column=0, sticky='w', pady=GAP, padx=(0, PAD))
        self.tag_mode = tk.StringVar(value='latest')
        modes = ttk.Frame(gh)
        modes.grid(row=3, column=1, sticky='w', pady=GAP)
        ttk.Radiobutton(modes, text='Dernière stable', value='latest', variable=self.tag_mode,
                        style='Toggle.TRadiobutton', command=self._on_tag_mode).pack(side='left')
        ttk.Radiobutton(modes, text='Tag précis', value='tag', variable=self.tag_mode,
                        style='Toggle.TRadiobutton', command=self._on_tag_mode).pack(side='left', padx=(GAP, 0))

        ttk.Label(gh, text='Tag', style='Muted.TLabel').grid(row=4, column=0, sticky='w', pady=GAP, padx=(0, PAD))
        self.tag = tk.StringVar()
        self.tag_entry = ttk.Entry(gh, textvariable=self.tag, width=16)
        self.tag_entry.grid(row=4, column=1, sticky='w', pady=GAP)

        ttk.Label(gh, text='Manifeste', style='Muted.TLabel').grid(row=5, column=0, sticky='nw', pady=GAP, padx=(0, PAD))
        self.manifest_preview = ttk.Label(gh, wraplength=330, justify='left')
        self.manifest_preview.grid(row=5, column=1, sticky='w', pady=GAP)
        ttk.Label(gh, style='Muted.TLabel', wraplength=400, justify='left',
                  text='Une pré-version n\'est jamais « Dernière stable » : pour la tester, choisissez '
                       '« Tag précis ». La Release doit être publique, le lanceur ne stocke aucun jeton.').grid(
            row=6, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        buttons = ttk.Frame(gh)
        buttons.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(PAD, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text='Enregistrer', style='Accent.TButton', command=self._save_config).grid(
            row=0, column=0, sticky='ew', padx=(0, GAP // 2))
        self.check_button = ttk.Button(buttons, text='Tester le manifeste', command=self._check_manifest)
        self.check_button.grid(row=0, column=1, sticky='ew', padx=(GAP // 2, 0))
        for var in (self.repo, self.tag, self.tag_mode):
            var.trace_add('write', lambda *args: self._refresh_manifest_preview())

        tools = self._card(page, 'Outils', row=1)
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        self.diag_button = ttk.Button(tools, text='Diagnostic', command=self._diagnostic)
        self.diag_button.grid(row=1, column=0, sticky='ew', padx=(0, GAP // 2), pady=(0, GAP))
        ttk.Button(tools, text='Ouvrir le journal', command=self._open_log).grid(
            row=1, column=1, sticky='ew', padx=(GAP // 2, 0), pady=(0, GAP))
        ttk.Button(tools, text='Dossier du lanceur', command=self._open_launcher_dir).grid(
            row=2, column=0, sticky='ew', padx=(0, GAP // 2))
        ttk.Button(tools, text='Dossier Mods', command=self._open_mods_dir).grid(
            row=2, column=1, sticky='ew', padx=(GAP // 2, 0))
        ttk.Label(tools, style='Muted.TLabel', wraplength=400, justify='left',
                  text='Le diagnostic ne modifie rien. En mode Rejoindre, il tente une connexion '
                       'de 3 s vers l\'hôte enregistré.').grid(
            row=3, column=0, columnspan=2, sticky='w', pady=(GAP, 0))

        # Journal, toujours visible a droite.
        box = ttk.Frame(content, style='Card.TFrame', padding=PAD + 2)
        box.grid(row=0, column=1, sticky='nsew')
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        ttk.Label(box, text='Journal', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, PAD))
        # tk.Text n'a pas d'equivalent ttk ; la barre de defilement est ttk.
        self.messages = tk.Text(box, height=8, wrap='word', state='disabled',
                                font=(MONO_FAMILY, 9), relief='flat', borderwidth=0,
                                padx=PAD, pady=PAD, background=COLOR_FIELD, foreground='#334155',
                                highlightthickness=1, highlightbackground=COLOR_BORDER,
                                highlightcolor=COLOR_BORDER, cursor='arrow', spacing3=3)
        self.messages.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.messages.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.messages.configure(yscrollcommand=scroll.set)
        self.messages.tag_configure('error', foreground=COLOR_ERROR)
        self.messages.tag_configure('ok', foreground=COLOR_OK)

        self._show_page('connexion')
        self._refresh_ips()
        self._load_settings()
        self._load_config()
        self._on_role()
        self._on_tag_mode()
        self._refresh_backups()
        self.game = detect_game()
        self._apply_game_state()
        center_window(root, 1040, 700)

    def _card(self, parent, title, row):
        """Carte sombre avec un titre vert ; renvoie le cadre interieur (grid)."""
        card = self.ttk.Frame(parent, style='Card.TFrame', padding=PAD + 4)
        card.grid(row=row, column=0, sticky='ew', pady=(0 if row == 0 else PAD + 6, 0))
        self.ttk.Label(card, text=title, style='CardTitle.TLabel').grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, PAD))
        return card

    def _show_page(self, key):
        self.pages[key].tkraise()
        if key == 'mod' and hasattr(self, 'backups'):
            self._refresh_backups()
        for name, (bar, button) in self.nav.items():
            active = name == key
            bar.configure(style='NavBarOn.TFrame' if active else 'NavBarOff.TFrame')
            button.configure(style='NavActive.TButton' if active else 'Nav.TButton')

    # -- messages --
    def show(self, text, tag=None):
        self.messages.configure(state='normal')
        self.messages.insert('end', text + '\n', tag or ())
        self.messages.see('end')
        self.messages.configure(state='disabled')
        log(('ERREUR : ' if tag == 'error' else '') + text)

    def set_status(self, text, kind=None):
        style = {'ok': 'StatusOk.TLabel', 'error': 'StatusError.TLabel'}.get(kind, 'Status.TLabel')
        # Une seule ligne dans la barre ; le detail reste dans Messages.
        self.status.configure(text=text.splitlines()[0] if text else 'Prêt', style=style)

    def _on_callback_error(self, exc_type, exc, tb):
        detail = ''.join(traceback.format_exception(exc_type, exc, tb))
        log('ERREUR inattendue :\n' + detail)
        self.show('ERREUR inattendue : {}\nDetail dans {}'.format(exc, base_dir() / LOG_NAME), 'error')
        self.set_status('Erreur inattendue (voir Messages)', 'error')

    # -- reglage --
    def _documents(self):
        if self.documents is None:
            self.documents = documents_dir()
        return self.documents

    def _settings_file(self):
        return settings_path(self._documents())

    def _load_settings(self):
        try:
            path = self._settings_file()
            data = read_settings(path)
        except (ValueError, LauncherError) as exc:
            self.show('Reglage ignore (valeurs par defaut utilisees) : {}'.format(exc), 'error')
            self.set_status('Réglage invalide ignoré (voir Messages)', 'error')
            return
        if data is None:
            self.show('Aucun reglage enregistre : valeurs par defaut.')
            return
        self.role.set(data['role'])
        self.ip.set(data['ip'])
        self.port.set(str(data['port']))
        self.show('Reglage charge : {}'.format(path))

    def _form_settings(self):
        port = validate_port(self.port.get())
        role = self.role.get()
        ip = self.ip.get().strip()
        if role == ROLE_JOIN or ip:
            ip = validate_ipv4(ip)
        return {'role': role, 'ip': ip, 'port': port}

    def _save(self):
        try:
            data = write_settings(self._settings_file(), self._form_settings())
        except (ValueError, LauncherError, OSError) as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        role = 'Heberger' if data['role'] == ROLE_HOST else 'Rejoindre {}'.format(data['ip'])
        self.show('Reglage enregistre ({}, port {}) : {}'.format(role, data['port'], self._settings_file()), 'ok')
        self.set_status('Réglage enregistré', 'ok')

    # -- options GitHub --
    def _load_config(self):
        try:
            data = read_config(config_path())
        except ValueError as exc:
            self.show('Options ignorees : {}'.format(exc), 'error')
            self.set_status('Options invalides ignorées (voir Journal)', 'error')
            return
        if data:
            self.repo.set(data['depot'])
            self.tag.set(data['tag'])
            self.tag_mode.set('tag' if data['tag'] else 'latest')

    def _form_config(self):
        tag = self.tag.get() if self.tag_mode.get() == 'tag' else ''
        if self.tag_mode.get() == 'tag' and not tag.strip():
            raise ValueError('Tag manquant : entrez le tag de la Release (par exemple v0.4.0).')
        return {'depot': validate_repo(self.repo.get()), 'tag': validate_tag(tag)}

    def _manifest_url(self):
        try:
            return effective_manifest_url(read_config(config_path()))
        except ValueError:
            return MANIFEST_URL

    def _refresh_manifest_preview(self):
        try:
            data = self._form_config()
            text, style = manifest_url_for(data['depot'], data['tag']), 'TLabel'
        except ValueError:
            text, style = '(renseignez le dépôt)', 'Muted.TLabel'
        self.manifest_preview.configure(text=text, style=style)

    def _on_tag_mode(self):
        self.tag_entry.configure(state='normal' if self.tag_mode.get() == 'tag' else 'disabled')
        self._refresh_manifest_preview()

    def _save_config(self):
        try:
            data = write_config(config_path(), self._form_config())
        except (ValueError, OSError) as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        self.show('Options enregistrees : {}'.format(manifest_url_for(data['depot'], data['tag'])), 'ok')
        self.set_status('Options enregistrées', 'ok')

    def _check_manifest(self):
        try:
            data = self._form_config()
        except ValueError as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        url = manifest_url_for(data['depot'], data['tag'])

        def task():
            manifest = fetch_manifest(url, make_https_opener())
            lines = ['Manifeste valide : {}'.format(url),
                     'Version {}, statut {}, {} octets, SHA-256 {}...'.format(
                         manifest['version'], manifest['statut'], manifest['taille'], manifest['sha256'][:16])]
            return lines, 'Manifeste valide ({}, {})'.format(manifest['version'], manifest['statut'])
        self._start_task('Lecture du manifeste...', lambda: self._run_worker(task))

    def _launch_game(self):
        if self.game.kind is None:
            return
        target = game_target(self.game)
        summary = 'Jeu lancé via {}'.format(GAME_KIND_LABELS[self.game.kind])
        if target == STEAM_GAME_URL:
            start = launch_game                     # cible par defaut : Steam
        else:
            def start():
                return launch_game(target=target)
        self._start_task('Lancement des Sims 4...',
                         lambda: self._run_worker(lambda: (start(), summary)))

    # -- installation du jeu --
    def _apply_game_state(self):
        """Barre d'etat et bouton Jouer d'apres l'installation detectee."""
        found = self.game.kind is not None
        self.game_status.configure(text='Jeu : {}'.format(
            GAME_KIND_LABELS[self.game.kind] if found else 'introuvable'))
        self.play_button.configure(state='normal' if found and not self.installing else 'disabled')
        self.play_hint.configure(text='' if found else
                                 'Jeu introuvable : installez Les Sims 4 avec Steam ou l\'app EA, '
                                 'puis rouvrez le lanceur.')

    # -- restauration --
    def _refresh_backups(self):
        try:
            self.backups = list_backups(base_dir() / BACKUP_DIR_NAME)
            labels = [backup_label(p) for p in self.backups]
        except OSError as exc:
            self.backups, labels = [], []
            self.show('Sauvegardes illisibles : {}'.format(exc), 'error')
        self.backup_box.configure(values=labels)
        self.backup_choice.set(labels[0] if labels else '')
        self.restore_button.configure(state='normal' if labels and not self.installing else 'disabled')

    def _show_help(self):
        from tkinter import messagebox
        messagebox.showinfo('Aide Sims4MP', HELP_TEXT, parent=self.root)

    def _confirm(self, title, text):
        from tkinter import messagebox
        return messagebox.askyesno(title, text, parent=self.root, icon='warning')

    def _restore(self):
        index = self.backup_box.current()
        if index < 0 or index >= len(self.backups):
            self.show('Choisissez une sauvegarde dans la liste.', 'error')
            self.set_status('Aucune sauvegarde choisie', 'error')
            return
        backup = self.backups[index]
        if not self._confirm('Restaurer l\'ancien mod',
                             'Remettre ce mod dans le dossier Mods ?\n\n{}\n\n'
                             'Le mod actuel sera d\'abord sauvegardé.'.format(self.backup_choice.get())):
            self.show('Restauration annulee.')
            return
        documents = self._documents()
        self._start_task('Restauration du mod...', lambda: self._run_worker(
            lambda: run_restore(backup, documents, base_dir() / BACKUP_DIR_NAME)))

    # -- outils --
    def _diagnostic(self):
        documents = self._documents()
        self._start_task('Diagnostic en cours...',
                         lambda: self._run_worker(lambda: run_diagnostic(documents)))

    def _open_log(self):
        path = base_dir() / LOG_NAME
        if not path.exists():
            log('Journal cree.')
        try:
            os.startfile(str(path))
        except OSError as exc:
            self.show('Impossible d\'ouvrir le journal : {}'.format(exc), 'error')
            self.set_status('Impossible d\'ouvrir le journal', 'error')

    def _open_launcher_dir(self):
        os.startfile(str(base_dir()))

    def _open_mods_dir(self):
        try:
            os.startfile(str(find_mods_dir(self._documents())))
        except LauncherError as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')

    def _on_role(self):
        joining = self.role.get() == ROLE_JOIN
        self.ip_entry.configure(state='normal' if joining else 'disabled')
        self.ip_hint.configure(text='' if joining else 'inutile pour héberger')

    # -- IP locales --
    def _refresh_ips(self):
        self.ips = local_ipv4_addresses()
        main_ip = primary_ip(self.ips)
        for child in self.ip_list.winfo_children():
            child.destroy()
        if not self.ips:
            self.ttk.Label(self.ip_list, text='(aucune trouvée)', style='Muted.TLabel').pack(anchor='w')
        for ip in self.ips:
            line = self.ttk.Frame(self.ip_list)
            line.pack(anchor='w', fill='x')
            self.ttk.Label(line, text=ip, width=16,
                           style='Primary.TLabel' if ip == main_ip else 'TLabel').pack(side='left')
            suffix = ip_label(ip) + ('  · principale' if ip == main_ip else '')
            self.ttk.Label(line, text=suffix, style='Muted.TLabel').pack(side='left')
        self.copy_button.configure(state='normal' if main_ip else 'disabled')

    def _copy_ips(self):
        main_ip = primary_ip(self.ips)
        if not main_ip:
            self.show('Aucune IP locale a copier.', 'error')
            self.set_status('Aucune IP locale à copier', 'error')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(main_ip)
        self.show('Copie dans le presse-papiers : {}'.format(main_ip))
        self.set_status('IP copiée : {}'.format(main_ip), 'ok')

    # -- installation (thread : la recherche dans Documents peut etre lente) --
    def _start_task(self, message, worker):
        if self.installing:
            return
        self.installing = True
        for button in (self.install_button, self.update_button, self.check_button, self.play_button,
                       self.restore_button, self.diag_button):
            button.configure(state='disabled')
        self.show(message)
        self.set_status(message)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_install)

    def _install(self):
        self._start_task('Installation du mod...', self._install_worker)

    def _update(self):
        self._start_task('Mise à jour depuis GitHub...', self._update_worker)

    def _run_worker(self, func):
        # Execute dans le thread : le resultat passe par la file pour l'interface.
        try:
            lines, summary = func()
            self.results.put(('ok', lines, summary))
        except LauncherError as exc:
            self.results.put(('error', [str(exc)], None))
        except Exception as exc:
            log('ERREUR inattendue :\n' + traceback.format_exc())
            self.results.put(('error', ['Erreur inattendue : {}\nDetail dans {}'.format(
                exc, base_dir() / LOG_NAME)], None))

    def _install_worker(self):
        def task():
            source = find_mod_source()
            lines = run_install(source, self._documents(), base_dir() / BACKUP_DIR_NAME)
            return lines + ['Mod installe.'], 'Mod installé'
        self._run_worker(task)

    def _update_worker(self):
        allow_test = bool(self.allow_test.get())
        allow_downgrade = bool(self.allow_downgrade.get())

        manifest_url = self._manifest_url()

        def task():
            return run_update(manifest_url, self._documents(), base_dir() / BACKUP_DIR_NAME,
                              base_dir(), allow_test=allow_test, allow_downgrade=allow_downgrade)
        self._run_worker(task)

    def _poll_install(self):
        try:
            kind, lines, summary = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_install)
            return
        for i, line in enumerate(lines):
            tag = 'error' if kind == 'error' or line.startswith('ATTENTION') else None
            if kind == 'ok' and i == len(lines) - 1:
                tag = 'ok'
            self.show(line, tag)
        if kind == 'ok':
            self.set_status(summary, 'ok')
        else:
            self.set_status(lines[0] if lines else 'Échec', 'error')
        self.installing = False
        for button in (self.install_button, self.update_button, self.check_button, self.diag_button):
            button.configure(state='normal')
        # Ces deux boutons dependent d'un etat : jeu detecte, sauvegardes presentes.
        self._apply_game_state()
        self._refresh_backups()


def main():
    try:
        import tkinter as tk
        root = tk.Tk()
        LauncherApp(root)
        root.mainloop()
    except Exception:
        log('ERREUR au demarrage :\n' + traceback.format_exc())
        try:
            ctypes.windll.user32.MessageBoxW(
                None, 'Le lanceur n\'a pas pu demarrer.\nDetail dans {}'.format(base_dir() / LOG_NAME),
                'Sims4MP', 0x10)
        except Exception:
            pass
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
