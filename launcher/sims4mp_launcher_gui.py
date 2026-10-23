# Lanceur Sims4MP, version fenetre (tkinter).
#
# Python 3.12, bibliotheque standard uniquement.
# Build :  py -3.12 -m PyInstaller --onefile --noconsole --noconfirm --name Sims4MP_Launcher_GUI launcher/sims4mp_launcher_gui.py
# Mac :    python3 launcher/sims4mp_launcher_gui.py  (ou double-clic sur launcher/Sims4MP_Mac.command)
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

if __name__ == '__main__':
    # sims4mp_room importe « sims4mp_launcher_gui » : meme module, pas une seconde copie
    # (sinon ses erreurs ne seraient pas des LauncherError de cette copie-ci).
    sys.modules.setdefault('sims4mp_launcher_gui', sys.modules[__name__])

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
# Choix de la page Mod, gardes d'une ouverture a l'autre. Fichier a part : un ancien
# lanceur refuserait le fichier d'options s'il contenait des cles inconnues.
PREFS_NAME = 'sims4mp_launcher_prefs.json'
PREFS_DEFAULTS = {'version_test': False, 'retour_arriere': False}
MANIFEST_NAME = 'sims4mp_manifest.json'
# Icone de la roue (mod 0.16.0) : second manifeste, a cote du premier dans la meme release.
# Le manifeste du mod ne change pas : les anciens lanceurs le lisent toujours.
#   {"fichier": "sims4mp_icons.package", "url": "https://.../sims4mp_icons.package",
#    "sha256": "<64 hex>", "taille": 12345}
ICONS_FILE = 'sims4mp_icons.package'
ICONS_MANIFEST_NAME = 'sims4mp_icons_manifest.json'
ICONS_MANIFEST_KEYS = {'fichier', 'url', 'sha256', 'taille'}
MAX_ICONS_SIZE = 1024 * 1024             # 1 Mo

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
# Sans effet hors Windows (pas de console a cacher).
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

MOD_FILE = 'sims4mp_hello.ts4script'
WINDOWS_GAME_PROCESS = 'TS4_x64.exe'
MAC_GAME_PROCESS = 'The Sims 4'                   # executable dans The Sims 4.app/Contents/MacOS
MAC_GAME_APP = 'The Sims 4.app'
GAME_PROCESS = MAC_GAME_PROCESS if IS_MAC else WINDOWS_GAME_PROCESS
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

def mac_data_dir(home=None):
    """Dossier des donnees du lanceur compile sur Mac : l'interieur d'une .app
    peut etre en lecture seule (et y ecrire casserait sa signature)."""
    folder = Path(home or Path.home()) / 'Library' / 'Application Support' / 'Sims4MP'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def base_dir():
    # Dossier du .exe une fois compile (Application Support sur Mac), sinon dossier du script.
    if getattr(sys, 'frozen', False):
        if IS_MAC:
            return mac_data_dir()
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


def validate_prefs(data):
    """Choix de la page Mod : cles connues seulement, valeurs vrai/faux ; les absentes valent faux."""
    if not isinstance(data, dict):
        raise ValueError('Choix enregistrés invalides : objet JSON attendu.')
    unknown = set(data) - set(PREFS_DEFAULTS)
    if unknown:
        raise ValueError('Choix enregistrés invalides : clés inconnues {}.'.format(sorted(unknown)))
    if any(not isinstance(value, bool) for value in data.values()):
        raise ValueError('Choix enregistrés invalides : valeurs vrai/faux attendues.')
    return dict(PREFS_DEFAULTS, **data)


def prefs_path():
    return base_dir() / PREFS_NAME


def read_prefs(path):
    """Choix enregistres (valeurs par defaut si le fichier n'existe pas) ; ValueError s'il est invalide."""
    path = Path(path)
    if not path.is_file():
        return dict(PREFS_DEFAULTS)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Lecture impossible de {} : {}'.format(path, exc)) from None
    return validate_prefs(data)


def write_prefs(path, data):
    clean = validate_prefs(data)
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
    if not IS_WINDOWS:
        # Les Sims 4 sur Mac : ~/Documents/Electronic Arts/Les Sims 4.
        return Path.home() / 'Documents'
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
        capture_output=True, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise LauncherError('tasklist a echoue (code {}), impossible de verifier '
                            'si le jeu tourne.'.format(proc.returncode))
    output = proc.stdout.decode('oem', errors='replace').lower()
    return '"{}"'.format(GAME_PROCESS.lower()) in output


def game_is_running_mac(run=subprocess.run):
    """pgrep sur l'executable de The Sims 4.app (code 0 : trouve, 1 : aucun)."""
    # Motif fixe (regex de pgrep) : The Sims 4.app, The Sims™ 4.app, Les Sims 4.app...
    proc = run(['pgrep', '-f', 'Sims[^/]*4\\.app/Contents/MacOS/'], capture_output=True)
    if proc.returncode not in (0, 1):
        raise LauncherError('pgrep a echoue (code {}), impossible de verifier '
                            'si le jeu tourne.'.format(proc.returncode))
    return proc.returncode == 0


if IS_MAC:
    game_is_running = game_is_running_mac


def open_path(target):
    """Ouvre un fichier, un dossier, une app ou une URL steam:// avec le
    programme du systeme. Arguments en liste, jamais de shell."""
    if IS_WINDOWS:
        os.startfile(str(target))
    elif IS_MAC:
        subprocess.Popen(['open', str(target)])
    else:
        subprocess.Popen(['xdg-open', str(target)])


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def install_mod(source, mods_dir, backup_dir):
    return install_file(source, mods_dir, backup_dir, MOD_FILE)


def install_file(source, mods_dir, backup_dir, name):
    """Copie verifiee de source vers Mods/name (mod ou icone). Renvoie (cible, sauvegarde, sha256)."""
    target = Path(mods_dir) / name
    backup = None
    if target.exists():
        # Sauvegarde HORS du dossier Mods : un .ts4script (ou .package) renomme dans
        # Mods (ou un sous-dossier) serait charge par le jeu en double.
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        stem, suffix = Path(name).stem, Path(name).suffix
        backup = backup_dir / '{}_{}{}'.format(stem, stamp, suffix)
        n = 2
        while backup.exists():
            backup = backup_dir / '{}_{}_{}{}'.format(stem, stamp, n, suffix)
            n += 1
        shutil.copy2(target, backup)
        if sha256_of(backup) != sha256_of(target):
            raise LauncherError('Sauvegarde de l\'ancien fichier incorrecte : {}'.format(backup))

    # Copie dans un fichier .part (ignore par le jeu), verification, puis
    # remplacement atomique : en cas d'echec l'ancien fichier reste intact et
    # le .part est supprime.
    part = Path(mods_dir) / ('.' + name + '.part')
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
    icons = Path(source).parent / ICONS_FILE
    if icons.is_file():
        if not is_dbpf(icons):
            lines.append('ATTENTION : {} n\'est pas un fichier .package valide : icone non copiee.'.format(icons))
        else:
            icon_target, _, _ = install_file(icons, mods_dir, backup_dir, ICONS_FILE)
            lines.append('Icone copiee : {}'.format(icon_target))
    lines.append('Version du mod installe : {}'.format(version))
    return lines


def is_dbpf(path):
    """Vrai si le fichier commence comme un .package du jeu (DBPF version 2)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8)
    except OSError:
        return False
    return head[:4] == b'DBPF' and head[4:8] == b'\x02\x00\x00\x00'


def launch_game(is_running=game_is_running, start=None, target=STEAM_GAME_URL):
    """Lance Les Sims 4 (Steam par defaut, ou le .exe / la .app detectee pour
    l'app EA), sans attendre le jeu. Refuse s'il tourne deja."""
    if is_running():
        raise LauncherError('Les Sims 4 est deja lance ({} en cours d\'execution).'.format(GAME_PROCESS))
    (start or open_path)(target)
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


def _plain_name(name):
    """Nom sans ™ / ® ni espace insecable, en minuscules : « The Sims™ 4 » -> « the sims 4 »."""
    return re.sub(r'\s+', ' ', re.sub('[™®]', '', name)).strip().lower()


def is_sims4_app(name):
    """The Sims 4.app, The Sims™ 4.app, Les Sims 4.app... (pas Sims 4 Studio.app)."""
    return re.fullmatch(r'((the|les) )?sims ?4\.app', _plain_name(name)) is not None


def is_game_process(name):
    return _plain_name(name) in {_plain_name(GAME_PROCESS), 'the sims 4', 'les sims 4'}


def _find_sims4_app(folder):
    """The Sims 4.app dans ce dossier, ou dans un de ses sous-dossiers (ex. « EA Games »)."""
    try:
        entries = sorted(Path(folder).iterdir())
    except OSError:
        return None
    for entry in entries:
        if is_sims4_app(entry.name) and entry.is_dir():
            return entry
    for entry in entries:
        if entry.suffix.lower() != '.app' and entry.is_dir() and not entry.is_symlink():
            try:
                for sub in sorted(entry.iterdir()):
                    if is_sims4_app(sub.name) and sub.is_dir():
                        return sub
            except OSError:
                continue
    return None


def detect_game_mac(home=None, applications=Path('/Applications')):
    """Cherche The Sims 4.app : bibliotheques Steam d'abord (~/Library/Application
    Support/Steam et libraryfolders.vdf), puis /Applications et ~/Applications
    (app EA, nom avec ou sans ™, ou dans un sous-dossier). Ne lance rien."""
    home = Path(home or Path.home())
    root = home / 'Library' / 'Application Support' / 'Steam'
    libraries = []
    vdf = root / 'steamapps' / 'libraryfolders.vdf'
    for folder in [root] + [Path(p) for p in _vdf_values(_read_text(vdf), 'path')]:
        if folder.is_dir() and folder not in libraries:
            libraries.append(folder)
    for library in libraries:
        acf = library / 'steamapps' / 'appmanifest_{}.acf'.format(STEAM_APP_ID)
        for installdir in _vdf_values(_read_text(acf), 'installdir'):
            if not re.fullmatch(r'[^/:]+', installdir) or installdir.strip('. ') == '':
                continue
            folder = library / 'steamapps' / 'common' / installdir
            apps = [folder / MAC_GAME_APP] + sorted(folder.glob('*.app')) if folder.is_dir() else []
            for app in apps:
                if app.is_dir():
                    return GameInstall('steam', app)
    for folder in (applications, home / 'Applications'):
        app = _find_sims4_app(folder)
        if app is not None:
            return GameInstall('ea', app)
    return GameInstall(None, None)


if IS_MAC:
    detect_game = detect_game_mac


def game_target(game):
    """Ce que launch_game ouvre pour l'installation detectee."""
    return str(game.exe) if game.kind == 'ea' else STEAM_GAME_URL


# --- Diagnostic (lecture seule) ----------------------------------------------

JOIN_HELP = ('le port ne répond pas : vérifiez que le host a lancé mp.host '
             'et que le pare-feu autorise le réseau privé')


def decode_console(data):
    """Sortie d'une commande : UTF-8 (netsh recent, macOS) sinon page de code OEM
    (latin-1 hors Windows, ou le codec 'oem' n'existe pas)."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('oem' if IS_WINDOWS else 'latin-1', errors='replace')


def _run_quiet(args, ok_codes=(0,)):
    """Commande systeme a arguments fixes (jamais construits depuis le reseau)."""
    proc = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, timeout=15)
    if proc.returncode not in ok_codes:
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


MAC_FIREWALL = '/usr/libexec/ApplicationFirewall/socketfilterfw'


def listening_pids_mac(port, run=_run_quiet):
    """PID des programmes qui ecoutent en TCP sur ce port (lsof ; code 1 : aucun)."""
    port = validate_port(port)
    output = run(['lsof', '-nP', '-iTCP:{}'.format(port), '-sTCP:LISTEN', '-Fp'], ok_codes=(0, 1))
    pids = []
    for line in output.splitlines():
        # -Fp : une ligne « p<pid> » par programme.
        if line.startswith('p') and line[1:].isdigit() and int(line[1:]) not in pids:
            pids.append(int(line[1:]))
    return pids


def process_name_mac(pid, run=_run_quiet):
    # ps donne le chemin complet de l'executable : on garde le dernier element.
    output = run(['ps', '-p', str(int(pid)), '-o', 'comm='], ok_codes=(0, 1)).strip()
    return output.rsplit('/', 1)[-1] if output else 'PID {}'.format(int(pid))


def firewall_profiles_mac(run=_run_quiet):
    """[('macOS', etat)] d'apres le pare-feu applicatif (socketfilterfw)."""
    output = run([MAC_FIREWALL, '--getglobalstate'])
    match = re.search(r'State\s*=\s*(\d)', output)
    if match:
        return [('macOS', 'désactivé' if match.group(1) == '0' else 'activé')]
    lowered = output.lower()
    if 'disabled' in lowered:
        return [('macOS', 'désactivé')]
    if 'enabled' in lowered:
        return [('macOS', 'activé')]
    return []


if IS_MAC:
    listening_pids, process_name, firewall_profiles = listening_pids_mac, process_name_mac, firewall_profiles_mac


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
                if is_game_process(name):
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


def validate_icons_manifest(data):
    """Valide le manifeste de l'icone et renvoie une copie normalisee, sinon LauncherError."""
    if not isinstance(data, dict):
        raise LauncherError('Manifeste de l\'icone invalide : objet JSON attendu.')
    if set(data) != ICONS_MANIFEST_KEYS:
        raise LauncherError('Manifeste de l\'icone invalide : cles attendues {}.'.format(
            sorted(ICONS_MANIFEST_KEYS)))
    if data['fichier'] != ICONS_FILE:
        raise LauncherError('Manifeste de l\'icone invalide : fichier « {} » (attendu {}).'.format(
            data['fichier'], ICONS_FILE))
    url = require_https(data['url'], 'URL de l\'icone')
    sha = data['sha256']
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', sha):
        raise LauncherError('Manifeste de l\'icone invalide : sha256 doit faire 64 caracteres hexadecimaux.')
    size = data['taille']
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ICONS_SIZE:
        raise LauncherError('Manifeste de l\'icone invalide : taille {} (1 a {} octets).'.format(
            size, MAX_ICONS_SIZE))
    return {'fichier': ICONS_FILE, 'url': url, 'sha256': sha.lower(), 'taille': size}


def icons_manifest_url(manifest_url):
    """Le manifeste de l'icone est range a cote de celui du mod (meme release)."""
    return manifest_url.strip().rsplit('/', 1)[0] + '/' + ICONS_MANIFEST_NAME


class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Suit les redirections (GitHub -> objects.githubusercontent.com) en HTTPS seulement."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_https(newurl, 'Redirection')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


MAC_SYSTEM_CA = Path('/etc/ssl/cert.pem')


def tls_context(mac=None, system_ca=MAC_SYSTEM_CA):
    """Contexte TLS verifie (certificat et nom d'hote). Le Python de python.org
    sur Mac n'a aucun certificat racine tant qu'« Install Certificates » n'a
    pas ete lance : on prend alors ceux de macOS (/etc/ssl/cert.pem)."""
    context = ssl.create_default_context()
    if (IS_MAC if mac is None else mac) and context.cert_store_stats()['x509_ca'] == 0 \
            and Path(system_ca).is_file():
        context.load_verify_locations(cafile=str(system_ca))
    return context


def make_https_opener():
    # Pas de HTTPHandler, FileHandler ni FTPHandler : seul https:// est ouvrable.
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.UnknownHandler(),      # http://, file:// -> URLError
                    urllib.request.HTTPSHandler(context=tls_context()),
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
    try:
        read_limited(url, buffer, MAX_MANIFEST_SIZE, timeout, opener)
    except LauncherError as exc:
        # GitHub ignore les pre-versions dans « latest » : 404 tant qu'aucune version stable n'existe.
        if '(HTTP 404)' in str(exc) and '/releases/latest/' in url:
            raise LauncherError('Aucune version stable publiée sur ce dépôt (HTTP 404). Pour une '
                                'pré-version, choisissez « Tag précis » dans Options.\n{}'.format(url)) from None
        raise
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


RELEASES_API = 'https://api.github.com/repos/{}/releases?per_page=30'
MAX_RELEASES_SIZE = 1024 * 1024


def fetch_release_tags(repo, opener, timeout=DOWNLOAD_TIMEOUT):
    """Releases publiees du depot (API publique GitHub, sans jeton) : liste de
    {'tag', 'statut' ('stable' ou 'test'), 'date' (AAAA-MM-JJ)}, la plus recente d'abord.
    Les brouillons et les tags invalides sont ignores."""
    url = require_https(RELEASES_API.format(validate_repo(repo)), 'Liste des versions')
    buffer = _BytesSink()
    read_limited(url, buffer, MAX_RELEASES_SIZE, timeout, opener)
    try:
        data = json.loads(bytes(buffer.data).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LauncherError('Liste des versions illisible (JSON invalide) : {}'.format(exc)) from None
    if not isinstance(data, list):
        raise LauncherError('Liste des versions illisible : liste attendue.')
    tags = []
    for release in data:
        if not isinstance(release, dict) or release.get('draft') is True:
            continue
        tag = release.get('tag_name')
        try:
            if not isinstance(tag, str) or not validate_tag(tag):
                continue
        except ValueError:
            continue
        date = release.get('published_at')
        date = date[:10] if isinstance(date, str) and re.match(r'\d{4}-\d{2}-\d{2}', date) else ''
        tags.append({'tag': tag, 'statut': STATUS_TEST if release.get('prerelease') is True else STATUS_STABLE,
                     'date': date})
    return tags


def tag_label(entry):
    """Texte du menu deroulant : « v0.17.0 · test · 23/10/2026 »."""
    parts = [entry['tag'], entry['statut']]
    if entry['date']:
        year, month, day = entry['date'].split('-')
        parts.append('{}/{}/{}'.format(day, month, year))
    return ' · '.join(parts)


def fetch_icons_manifest(url, opener, timeout=DOWNLOAD_TIMEOUT):
    """Manifeste de l'icone, ou None si la release n'en a pas (HTTP 404, releases < 0.16.0)."""
    url = require_https(url, 'URL du manifeste de l\'icone')
    buffer = _BytesSink()
    try:
        read_limited(url, buffer, MAX_MANIFEST_SIZE, timeout, opener)
    except LauncherError as exc:
        if '(HTTP 404)' in str(exc):
            return None
        raise
    try:
        data = json.loads(bytes(buffer.data).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LauncherError('Manifeste de l\'icone illisible (JSON invalide) : {}'.format(exc)) from None
    return validate_icons_manifest(data)


def download_icons(icons, temp_dir, opener, timeout=DOWNLOAD_TIMEOUT):
    """Telecharge sims4mp_icons.package dans temp_dir et le verifie (taille, SHA-256, DBPF)."""
    url = require_https(icons['url'], 'URL de l\'icone')
    fd, tmp = tempfile.mkstemp(prefix='sims4mp_icons_', suffix='.part', dir=str(temp_dir))
    tmp = Path(tmp)
    try:
        with os.fdopen(fd, 'wb') as out:
            size = read_limited(url, out, min(icons['taille'], MAX_ICONS_SIZE), timeout, opener)
        if size != icons['taille']:
            raise LauncherError('Icone : taille incorrecte ({} octets recus, {} attendus).'.format(
                size, icons['taille']))
        digest = sha256_of(tmp)
        if digest != icons['sha256']:
            raise LauncherError('Icone : SHA-256 incorrect, fichier refuse.')
        if not is_dbpf(tmp):
            raise LauncherError('Icone : le fichier telecharge n\'est pas un .package valide.')
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return tmp


def update_icons(manifest_url, mods_dir, backup_dir, temp_dir, opener, timeout, is_running):
    """Installe ou met a jour l'icone de la roue. Ne leve jamais : renvoie des lignes de resume
    (une icone manquante ne doit pas faire echouer la mise a jour du mod)."""
    try:
        icons = fetch_icons_manifest(icons_manifest_url(manifest_url), opener, timeout)
        if icons is None:
            return ['Icone : aucune dans cette release (versions avant 0.16.0).']
        current = Path(mods_dir) / ICONS_FILE
        if current.is_file() and sha256_of(current) == icons['sha256']:
            return ['Icone deja installee (fichier identique).']
        tmp = download_icons(icons, temp_dir, opener, timeout)
        try:
            if is_running():
                raise LauncherError('Fermez Les Sims 4 ({} est en cours d\'execution).'.format(GAME_PROCESS))
            target, _, _ = install_file(tmp, mods_dir, backup_dir, ICONS_FILE)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        return ['Icone copiee : {} ({} octets).'.format(target, target.stat().st_size)]
    except (LauncherError, OSError) as exc:
        return ['ATTENTION : icone non installee ({}). Le mod fonctionne sans.'.format(
            str(exc).splitlines()[0])]


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
        lines += update_icons(manifest_url, mods_dir, backup_dir, temp_dir, opener, timeout, is_running)
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
    lines += update_icons(manifest_url, mods_dir, backup_dir, temp_dir, opener, timeout, is_running)
    lines.append('Version du mod installe : {}{}'.format(
        manifest['version'], ' (version de test)' if manifest['statut'] == STATUS_TEST else ''))
    return lines, 'Mod mis à jour ({})'.format(manifest['version'])


# --- Fenetre -----------------------------------------------------------------

FONT_FAMILY = 'Helvetica Neue' if IS_MAC else 'Segoe UI'
FONT_SIZE = 10
MONO_FAMILY = 'Menlo' if IS_MAC else 'Consolas'
# Tk sur Mac compte 72 points par pouce (96 sous Windows) : sans cela, tout le texte y est plus petit.
MAC_TK_SCALING = 96 / 72
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
    '1. Options : dépôt GitHub (compte/dépôt), « Tag précis » pour une version de test → Enregistrer.',
    '2. Mod → Installer / mettre à jour depuis GitHub, jeu fermé. L\'ancien mod est sauvegardé.',
    '3. Hôte (jeu fermé) : Héberger, choisissez une partie manuelle → Créer la room → Copier l\'invitation → Accepter.',
    '4. Invité (jeu fermé) : Connexion → Rejoindre, IP de l\'hôte et code → Rejoindre la room.',
    '5. Port : Options → Réseau, le même chez les deux joueurs (la room utilise le port + 1).',
    '6. Hôte : « Lancer pour tous » lance aussi le jeu des invités qui l\'ont permis. En jeu : mp.host / mp.join <ip>.',
    '7. Pare-feu : n\'autorisez le jeu et le lanceur que sur les réseaux privés.',
    '8. Un souci ? Options → Diagnostic, puis Ouvrir le journal.',
    '9. Revenir en arrière : Mod → Restaurer l\'ancien mod.',
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
    if IS_MAC:
        root.tk.call('tk', 'scaling', MAC_TK_SCALING)
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
    style.configure('RoomCode.TLabel', foreground=COLOR_ACCENT, font=(MONO_FAMILY, 26, 'bold'))
    style.configure('Warning.TLabel', foreground='#b45309')
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


def default_pseudo():
    """Nom d'utilisateur Windows, nettoye (pseudo modifiable, jamais enregistre)."""
    try:
        import getpass
        name = getpass.getuser()
    except Exception:
        name = ''
    name = ''.join(c for c in name if c.isprintable()).strip()[:24]
    return name or 'Joueur'


def load_logo(root, name='LOGO_PNG_HEADER'):
    """Logo Sims4MP « deux joueurs » (sims4mp_logo.py, genere par make_logo.py depuis le
    dessin du mod, aucun element d'EA) ; None si indisponible (l'en-tete garde le texte)."""
    try:
        import tkinter as tk
        import sims4mp_logo
        return tk.PhotoImage(master=root, data=getattr(sims4mp_logo, name), format='png')
    except Exception:
        log('Logo Sims4MP indisponible :\n' + traceback.format_exc())
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
        root.minsize(960, 760)
        root.report_callback_exception = self._on_callback_error

        # Barre laterale : logo, titre, navigation.
        side = ttk.Frame(root, style='Side.TFrame', width=SIDEBAR_WIDTH)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        header = ttk.Frame(side, style='Side.TFrame')
        header.pack(fill='x', padx=PAD + 6, pady=(PAD + 10, 2 * PAD + 4))
        self.logo_image = load_logo(root)
        if self.logo_image is not None:
            # Garder la reference : sans elle, tkinter efface l'image.
            ttk.Label(header, image=self.logo_image, style='Side.TLabel').pack(side='left')
        # Icone de la fenetre et de la barre des taches (l'exe a aussi sims4mp.ico).
        self.window_icon = load_logo(root, 'LOGO_PNG_WINDOW')
        if self.window_icon is not None:
            try:
                root.iconphoto(True, self.window_icon)
            except tk.TclError:
                log('Icone de fenetre refusee :\n' + traceback.format_exc())
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
                   command=self._quit).pack(side='left', fill='x', expand=True)
        root.protocol('WM_DELETE_WINDOW', self._quit)        # la croix ferme aussi la room
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

        # Page CONNEXION (« Partie a deux ») : le mode, puis la room de l'hote ou de l'invite.
        # Les IP locales et le port sont dans Options → Reseau.
        page = self.pages['connexion']
        self.role = tk.StringVar(value=ROLE_HOST)
        self.ip = tk.StringVar()
        self.port = tk.StringVar(value=str(DEFAULT_PORT))
        mode = self._card(page, 'Mode de jeu', row=0)
        toggles = ttk.Frame(mode)
        toggles.grid(row=1, column=0, sticky='w')
        ttk.Radiobutton(toggles, text='Héberger', value=ROLE_HOST, variable=self.role,
                        style='Toggle.TRadiobutton', command=self._on_role).pack(side='left')
        ttk.Radiobutton(toggles, text='Rejoindre', value=ROLE_JOIN, variable=self.role,
                        style='Toggle.TRadiobutton', command=self._on_role).pack(side='left', padx=(GAP, 0))

        # Room : une seule carte, dont le contenu depend du mode.
        room_card = self._card(page, 'Room', row=1)
        room_card.columnconfigure(0, weight=1)
        self.room = None                 # RoomServer ouvert (hote)
        self.saves = []                  # sauvegardes proposees, dans l'ordre de la liste
        self._after_task = None
        self._join_info = None

        # Hote : room fermee (choix de la partie) ou ouverte (code en grand).
        host = self.host_room = ttk.Frame(room_card)
        host.grid(row=1, column=0, sticky='nsew')
        host.columnconfigure(0, weight=1)
        closed = self.host_closed = ttk.Frame(host)
        closed.grid(row=0, column=0, sticky='ew')
        closed.columnconfigure(1, weight=1)
        ttk.Label(closed, text='Partie à partager', style='Muted.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, PAD))
        self.save_choice = tk.StringVar()
        self.save_box = ttk.Combobox(closed, textvariable=self.save_choice, state='readonly')
        self.save_box.grid(row=0, column=1, sticky='ew')
        self.create_room_button = ttk.Button(closed, text='Créer la room', style='Accent.TButton',
                                             command=self._create_room)
        self.create_room_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(PAD, 0))
        self.room_hint = ttk.Label(closed, style='Muted.TLabel', wraplength=400, justify='left',
                                   text='Le jeu doit être fermé. L\'invité recevra une copie de cette partie.')
        self.room_hint.grid(row=2, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        self.save_warning = ttk.Label(closed, style='Warning.TLabel', wraplength=400, justify='left')
        self.save_warning.grid(row=3, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        self.save_box.bind('<<ComboboxSelected>>', lambda event: self._update_save_warning())

        opened = self.host_opened = ttk.Frame(host)
        opened.grid(row=0, column=0, sticky='ew')
        opened.columnconfigure(0, weight=1)
        opened.columnconfigure(1, weight=1)
        ttk.Label(opened, text='Code de la room', style='Muted.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.room_code_label = ttk.Label(opened, style='RoomCode.TLabel')
        self.room_code_label.grid(row=1, column=0, columnspan=2, sticky='w')
        self.room_label = ttk.Label(opened, style='Muted.TLabel')
        self.room_label.grid(row=2, column=0, columnspan=2, sticky='w', pady=(0, PAD))
        # Etat du partage de la partie (ferme quand chaque invite accepte l'a recue).
        self.sharing_label = ttk.Label(opened, style='Muted.TLabel')
        self.sharing_label.grid(row=7, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        self.copy_room_button = ttk.Button(opened, text='Copier l\'invitation', style='Accent.TButton',
                                           command=self._copy_room)
        self.copy_room_button.grid(row=3, column=0, sticky='ew', padx=(0, GAP // 2))
        self.close_room_button = ttk.Button(opened, text='Fermer la room', command=self._close_room)
        self.close_room_button.grid(row=3, column=1, sticky='ew', padx=(GAP // 2, 0))
        ttk.Label(opened, text='Joueurs', style='Muted.TLabel').grid(row=4, column=0, columnspan=2,
                                                                    sticky='w', pady=(PAD, 0))
        self.players_label = ttk.Label(opened, justify='left', text='En attente d\'un joueur…')
        self.players_label.grid(row=5, column=0, columnspan=2, sticky='w')
        # Demandes en attente : une ligne « pseudo · IP  [Accepter] [Refuser] » par invite.
        self.pending_frame = ttk.Frame(opened)
        self.pending_frame.grid(row=6, column=0, columnspan=2, sticky='ew')
        self.pending_frame.columnconfigure(0, weight=1)
        self._pending_key = None
        self.launch_all_button = ttk.Button(opened, text='▶  Lancer pour tous', style='Play.TButton',
                                            command=self._launch_all)
        self.launch_all_button.grid(row=9, column=0, columnspan=2, sticky='ew', pady=(GAP, 0))

        # Invite : pseudo, adresse de l'hote et code.
        join = self.join_room_frame = ttk.Frame(room_card)
        join.grid(row=1, column=0, sticky='nsew')
        join.columnconfigure(1, weight=1)
        self.pseudo = tk.StringVar(value=default_pseudo())
        for row, (text, var, width) in enumerate([('Pseudo', self.pseudo, 18), ('IP de l\'hôte', self.ip, 18),
                                                  ('Code de room', None, 12)]):
            ttk.Label(join, text=text, style='Muted.TLabel').grid(row=row, column=0, sticky='w',
                                                                   pady=GAP // 2, padx=(0, PAD))
            if var is None:
                self.room_code = var = tk.StringVar()
            entry = ttk.Entry(join, textvariable=var, width=width)
            entry.grid(row=row, column=1, sticky='w', pady=GAP // 2)
            if var is self.ip:
                self.ip_entry = entry
        buttons = ttk.Frame(join)
        buttons.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(PAD, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.check_room_button = ttk.Button(buttons, text='Vérifier sans copier', command=self._check_room)
        self.check_room_button.grid(row=0, column=0, sticky='ew', padx=(0, GAP // 2))
        self.join_room_button = ttk.Button(buttons, text='Rejoindre la room', style='Accent.TButton',
                                           command=self._join_room)
        self.join_room_button.grid(row=0, column=1, sticky='ew', padx=(GAP // 2, 0))
        self.sync_mods_button = ttk.Button(buttons, text='Copier les mods de l\'hôte', command=self._sync_mods)
        self.sync_mods_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(GAP, 0))
        ttk.Label(join, style='Muted.TLabel', wraplength=400, justify='left',
                  text='La partie reçue va dans un slot réservé Sims4MP ; vos sauvegardes sont '
                       'copiées avant. Port : Options → Réseau (le même que l\'hôte).').grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        # Presence (9b) : decochee par defaut ; l'hote ne peut lancer que le jeu detecte ici.
        self.allow_host_launch = tk.BooleanVar(value=False)
        ttk.Checkbutton(join, text='Laisser l\'hôte lancer mon jeu', variable=self.allow_host_launch).grid(
            row=5, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        status = ttk.Frame(join)
        status.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(GAP, 0))
        status.columnconfigure(0, weight=1)
        self.presence_label = ttk.Label(status, style='Muted.TLabel', text='Non connecté à une room.')
        self.presence_label.grid(row=0, column=0, sticky='w')
        self.leave_room_button = ttk.Button(status, text='Quitter la room', command=self._leave_room,
                                            state='disabled')
        self.leave_room_button.grid(row=0, column=1, sticky='e')
        self.presence = None                 # connexion de l'invite a une room (presence)
        self.received_this_session = False   # partie de l'hote recue depuis l'ouverture du lanceur
        self.presence_results = queue.Queue()

        # Page MOD : le mod est toujours telecharge depuis GitHub (aucun fichier local).
        page = self.pages['mod']
        update = self._card(page, 'Mod Sims4MP', row=0)
        update.columnconfigure(0, weight=1)
        ttk.Label(update, style='Muted.TLabel', wraplength=400, justify='left',
                  text='Télécharge le mod depuis GitHub, le vérifie (taille et SHA-256) puis l\'installe '
                       'dans Mods. Le jeu doit être fermé ; l\'ancien mod est sauvegardé.').grid(
            row=1, column=0, sticky='w')
        self.source_label = ttk.Label(update, wraplength=400, justify='left')
        self.source_label.grid(row=2, column=0, sticky='w', pady=(GAP, 0))
        self.update_button = ttk.Button(update, text='Installer / mettre à jour depuis GitHub',
                                        style='Accent.TButton', command=self._update)
        self.update_button.grid(row=3, column=0, sticky='ew', pady=(PAD, GAP))
        self.allow_test = tk.BooleanVar(value=False)
        ttk.Checkbutton(update, text='Installer une version de test', variable=self.allow_test).grid(
            row=4, column=0, sticky='w', pady=(GAP, 0))
        self.allow_downgrade = tk.BooleanVar(value=False)
        ttk.Checkbutton(update, text='Autoriser le retour à une version plus ancienne',
                        variable=self.allow_downgrade).grid(row=5, column=0, sticky='w', pady=(GAP, 0))

        restore = self._card(page, 'Restaurer l\'ancien mod', row=1)
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
        tag_row = ttk.Frame(gh)
        tag_row.grid(row=4, column=1, sticky='w', pady=GAP)
        # Menu deroulant des versions publiees (on peut aussi taper un tag a la main).
        self.tag_entry = ttk.Combobox(tag_row, textvariable=self.tag, width=30)
        self.tag_entry.pack(side='left')
        self.tag_entry.bind('<<ComboboxSelected>>', self._on_tag_selected)
        self.tags_button = ttk.Button(tag_row, text='Actualiser la liste', command=self._refresh_tags)
        self.tags_button.pack(side='left', padx=(GAP, 0))
        self.tag_labels = {}                 # texte du menu -> tag
        self.tags_loaded_for = None          # depot dont la liste a deja ete lue

        ttk.Label(gh, text='Manifeste', style='Muted.TLabel').grid(row=5, column=0, sticky='nw', pady=GAP, padx=(0, PAD))
        self.manifest_preview = ttk.Label(gh, wraplength=330, justify='left')
        self.manifest_preview.grid(row=5, column=1, sticky='w', pady=GAP)
        ttk.Label(gh, style='Muted.TLabel', wraplength=400, justify='left',
                  text='Dépôt : compte/dépôt (ex. Flaimeur/sims4mp), Release publique, aucun jeton stocké. '
                       'Une pré-version demande « Tag précis ».').grid(
            row=6, column=0, columnspan=2, sticky='w', pady=(GAP, 0))
        buttons = ttk.Frame(gh)
        buttons.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(PAD, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text='Enregistrer et vérifier', style='Accent.TButton', command=self._save_config).grid(
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
                  text='Le diagnostic ne modifie rien ; en Rejoindre, il essaie l\'hôte 3 s.').grid(
            row=3, column=0, columnspan=2, sticky='w', pady=(GAP, 0))

        # Reseau : IP locales et port du jeu (la room utilise le port + 1).
        net = self._card(page, 'Réseau', row=2)
        net.columnconfigure(1, weight=1)
        ttk.Label(net, text='IP locales', style='Muted.TLabel').grid(row=1, column=0, sticky='nw', padx=(0, PAD))
        self.ip_list = ttk.Frame(net)
        self.ip_list.grid(row=1, column=1, columnspan=2, sticky='nw')
        ttk.Label(net, text='Port du jeu', style='Muted.TLabel').grid(row=2, column=0, sticky='w',
                                                                     padx=(0, PAD), pady=(GAP, 0))
        line = ttk.Frame(net)
        line.grid(row=2, column=1, sticky='w', pady=(GAP, 0))
        ttk.Entry(line, textvariable=self.port, width=8).pack(side='left')
        ttk.Label(line, text='room = port + 1', style='Muted.TLabel').pack(side='left', padx=(PAD, 0))
        self.copy_button = ttk.Button(net, text='Copier l\'IP', command=self._copy_ips)
        self.copy_button.grid(row=2, column=2, sticky='e', pady=(GAP, 0))

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
        self._load_prefs()
        self._refresh_source_label()
        self._on_role()
        self._on_tag_mode()
        self._refresh_backups()
        self.game = detect_game()
        self._apply_game_state()
        center_window(root, 1040, 790)

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
        if key == 'options' and hasattr(self, 'tags_loaded_for') and not self.installing:
            # Premiere visite (ou depot change) : la liste des versions se remplit seule.
            try:
                repo = validate_repo(self.repo.get())
            except ValueError:
                repo = None
            if repo is not None and repo != self.tags_loaded_for:
                self.tags_loaded_for = repo          # un seul essai automatique ; le bouton reste la
                self._refresh_tags()
        for name, (bar, button) in self.nav.items():
            active = name == key
            bar.configure(style='NavBarOn.TFrame' if active else 'NavBarOff.TFrame')
            button.configure(style='NavActive.TButton' if active else 'Nav.TButton')

    # -- messages --
    def show(self, text, tag=None, log_line=True):
        self.messages.configure(state='normal')
        self.messages.insert('end', text + '\n', tag or ())
        self.messages.see('end')
        self.messages.configure(state='disabled')
        if log_line:
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

    # -- choix de la page Mod (enregistres des qu'une case change) --
    def _load_prefs(self):
        try:
            data = read_prefs(prefs_path())
        except ValueError as exc:
            self.show('Choix de la page Mod ignorés : {}'.format(exc), 'error')
            data = dict(PREFS_DEFAULTS)
        self._prefs_loading = True
        self.allow_test.set(data['version_test'])
        self.allow_downgrade.set(data['retour_arriere'])
        self._prefs_loading = False
        if not getattr(self, '_prefs_traced', False):
            self.allow_test.trace_add('write', lambda *args: self._save_prefs())
            self.allow_downgrade.trace_add('write', lambda *args: self._save_prefs())
            self._prefs_traced = True

    def _save_prefs(self):
        if getattr(self, '_prefs_loading', False):
            return
        try:
            write_prefs(prefs_path(), {'version_test': bool(self.allow_test.get()),
                                       'retour_arriere': bool(self.allow_downgrade.get())})
        except (ValueError, OSError) as exc:
            self.show('Choix non enregistré : {}'.format(exc), 'error')
            return
        self.set_status('Choix enregistré', 'ok')

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
        state = 'normal' if self.tag_mode.get() == 'tag' else 'disabled'
        self.tag_entry.configure(state=state)
        self.tags_button.configure(state=state)
        self._refresh_manifest_preview()

    def _on_tag_selected(self, event=None):
        # Le menu montre « v0.17.0 · test · 23/10/2026 » ; seul le tag est garde.
        tag = self.tag_labels.get(self.tag.get())
        if tag is not None:
            self.tag.set(tag)

    def _refresh_tags(self):
        try:
            repo = validate_repo(self.repo.get())
        except ValueError as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        found = {}

        def task():
            tags = fetch_release_tags(repo, make_https_opener())
            found['tags'] = tags
            tests = sum(1 for t in tags if t['statut'] == STATUS_TEST)
            return (['Versions publiées sur {} : {} ({} de test)'.format(repo, len(tags), tests)],
                    '{} version(s) trouvée(s)'.format(len(tags)))

        def after():
            self._fill_tags(repo, found.get('tags', []))
        self._start_task('Lecture des versions publiées...', lambda: self._run_worker(task), after=after)

    def _fill_tags(self, repo, tags):
        self.tag_labels = {tag_label(t): t['tag'] for t in tags}
        self.tag_entry.configure(values=[tag_label(t) for t in tags])
        self.tags_loaded_for = repo

    def _save_config(self):
        try:
            data = write_config(config_path(), self._form_config())
        except (ValueError, OSError) as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        self.show('Options enregistrees : {}'.format(manifest_url_for(data['depot'], data['tag'])), 'ok')
        self.set_status('Options enregistrées', 'ok')
        self._refresh_source_label()
        self._check_manifest()                       # verification juste apres l'enregistrement

    def _refresh_source_label(self):
        """Page Mod : d'ou le mod sera telecharge, d'apres les options enregistrees."""
        try:
            data = read_config(config_path())
        except ValueError:
            data = None
        if data:
            version = 'tag {}'.format(data['tag']) if data['tag'] else 'dernière version stable'
            self.source_label.configure(text='Source : {} ({})'.format(data['depot'], version), style='TLabel')
        else:
            self.source_label.configure(text='Source non configurée : renseignez le dépôt dans Options.',
                                        style='Muted.TLabel')

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
            open_path(path)
        except OSError as exc:
            self.show('Impossible d\'ouvrir le journal : {}'.format(exc), 'error')
            self.set_status('Impossible d\'ouvrir le journal', 'error')

    def _open_launcher_dir(self):
        open_path(base_dir())

    def _open_mods_dir(self):
        try:
            open_path(find_mods_dir(self._documents()))
        except LauncherError as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')

    def _on_role(self):
        joining = self.role.get() == ROLE_JOIN
        self.ip_entry.configure(state='normal' if joining else 'disabled')
        (self.host_room if joining else self.join_room_frame).grid_remove()
        (self.join_room_frame if joining else self.host_room).grid()
        if not joining:
            self._refresh_saves()

    # -- room --
    def _room_port(self):
        """Port de la room : port du jeu + 1 (valide)."""
        import sims4mp_room as room
        port = validate_port(self.port.get()) + room.ROOM_PORT_OFFSET
        try:
            return validate_port(port)
        except ValueError:
            raise ValueError('Port trop grand : la room utilise le port du jeu + 1 ({}).'.format(port)) from None

    def _refresh_saves(self):
        """Liste rapide (nom, date, taille) ; partie et foyer sont lus a la creation."""
        import sims4mp_room as room
        try:
            self.saves = room.list_saves(room.saves_dir(self._documents()))
        except (LauncherError, OSError):
            self.saves = []
        labels = []
        for path in self.saves:
            stat = path.stat()
            labels.append('{}{} · {} · {:.1f} Mo'.format(
                path.name, ' (automatique)' if path.name.lower() == 'slot_ffffffff.save' else '',
                datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'), stat.st_size / 1e6))
        self.save_box.configure(values=labels)
        if self.save_box.current() < 0 or self.save_box.current() >= len(labels):
            # list_saves met les parties manuelles d'abord : l'automatique n'est jamais le choix par defaut.
            self.save_choice.set(labels[0] if labels else '')
        self._update_save_warning()
        self._apply_room_state()

    def _update_save_warning(self):
        import sims4mp_room as room
        index = self.save_box.current()
        auto = 0 <= index < len(self.saves) and room.is_auto_save(self.saves[index])
        self.save_warning.configure(text='Sauvegarde automatique (Slot_ffffffff) : préférez une partie '
                                         'sauvegardée à la main.' if auto else '')

    def _apply_room_state(self):
        busy = self.installing
        opened = self.room is not None
        self.create_room_button.configure(state='disabled' if busy or opened or not self.saves else 'normal')
        self.save_box.configure(state='disabled' if opened else 'readonly')
        self.close_room_button.configure(state='normal' if opened else 'disabled')
        self.copy_room_button.configure(state='normal' if opened else 'disabled')
        for button in (self.check_room_button, self.join_room_button, self.sync_mods_button):
            button.configure(state='disabled' if busy else 'normal')
        # Room fermee : choix de la partie ; ouverte : le code en grand. Une seule vue
        # affichee (superposees, la plus grande depasserait de l'autre).
        (self.host_closed if opened else self.host_opened).grid_remove()
        (self.host_opened if opened else self.host_closed).grid()
        if opened:
            self.room_code_label.configure(text=self.room.code)
            self.room_label.configure(text='IP {} · port {}'.format(self.room.bind_ip, self.room.port))
            self.sharing_label.configure(text='Partage de la partie : ouvert aux invités acceptés'
                                         if getattr(self.room, 'sharing_open', True) else
                                         'Partage fermé : chaque invité accepté a reçu la partie')
        else:
            self.room_code_label.configure(text='')
            self.room_label.configure(text='')
            self.sharing_label.configure(text='')

    def _create_room(self):
        import sims4mp_room as room
        index = self.save_box.current()
        bind_ip = primary_ip(self.ips)
        try:
            if index < 0 or index >= len(self.saves):
                raise ValueError('Choisissez une sauvegarde dans la liste.')
            if not bind_ip:
                raise ValueError('Aucune IP locale utilisable pour ouvrir la room.')
            port = self._room_port()
        except ValueError as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        save, documents = self.saves[index], self._documents()

        def task():
            mod = find_mods_dir(documents) / MOD_FILE
            version = read_mod_version(mod) if mod.is_file() else None
            if version in (None, 'inconnue'):
                raise LauncherError('Installez le mod Sims4MP (page Mod) avant de créer la room.')
            # Liste des mods avec SHA-256 (cache a cote du lanceur) : l'invite peut comparer et copier.
            server = room.RoomServer(save, room.saves_dir(documents), base_dir() / 'sims4mp_room',
                                     version, bind_ip, port, mods_dir=find_mods_dir(documents), mods_sha=True,
                                     mods_cache=base_dir() / 'sims4mp_mods_cache.json')
            info = server.prepare()
            try:
                server.start()
            except OSError as exc:
                server.stop()
                raise LauncherError('Impossible d\'ouvrir la room sur {}:{} ({}). Le port est peut-être '
                                    'déjà utilisé.'.format(bind_ip, port, exc)) from None
            self._pending_room = server
            lines = ['Partie : {} ({})'.format(info['partie'] or 'nom non lu', info['fichier']),
                     'Foyer(s) : {}'.format(', '.join(info['foyers']) or 'non lu'),
                     'Taille : {:.1f} Mo, SHA-256 {}...'.format(info['taille'] / 1e6, info['sha256'][:16]),
                     'Envoyez à l\'invité : IP {} · port {} · code {}'.format(bind_ip, server.port, server.code),
                     'Chaque invité devra être accepté (Joueurs → Accepter) avant de voir ou recevoir la partie.']
            if room.is_auto_save(save):
                lines.append('ATTENTION : vous partagez la sauvegarde automatique (Slot_ffffffff).')
            lines.append('Room ouverte. Gardez le lanceur ouvert jusqu\'à ce que l\'invité ait reçu la partie.')
            return lines, 'Room ouverte (code {})'.format(server.code)
        self._pending_room = None
        self._start_task('Création de la room...', lambda: self._run_worker(task), after=self._room_opened)

    def _room_opened(self):
        self.room, self._pending_room = self._pending_room, None
        self._apply_room_state()
        self._auto_save(ROLE_HOST)
        self.root.after(500, self._poll_room)

    def _auto_save(self, role):
        """Enregistre le reglage (role, IP, port) sans bouton ; une erreur ne bloque pas la room."""
        try:
            ip = validate_ipv4(self.ip.get()) if role == ROLE_JOIN else ''
            data = write_settings(self._settings_file(), {'role': role, 'ip': ip,
                                                          'port': validate_port(self.port.get())})
        except (ValueError, LauncherError, OSError) as exc:
            self.show('Reglage non enregistre : {}'.format(exc), 'error')
            return
        self.show('Reglage enregistre automatiquement ({}, port {}).'.format(
            'Heberger' if role == ROLE_HOST else 'Rejoindre {}'.format(data['ip']), data['port']))

    def _poll_room(self):
        if self.room is None:
            return
        self._refresh_players()
        for event in self.room.take_events():
            self.show('Room : ' + event, 'ok' if event.startswith('Sauvegarde envoyée') else None,
                      log_line=False)                     # deja ecrit dans launcher.log par la room
        self._apply_room_state()                          # le partage a pu se fermer
        self.root.after(500, self._poll_room)

    def _refresh_players(self):
        """Joueurs acceptes (texte) et demandes en attente (une ligne avec Accepter / Refuser)."""
        import sims4mp_room as room
        guests = self.room.guests_snapshot() if self.room is not None else []
        guests.sort(key=lambda g: g['pseudo'].casefold())
        accepted = [g for g in guests if g['accord'] == 'accepte']
        waiting = [g for g in guests if g['accord'] == 'attente']
        lines = ['{} · {} · {} · {}'.format(g['pseudo'], g['ip'], room.GUEST_STATES[g['etat']],
                                            'lancement autorisé' if g['autorise'] else 'lancement non autorisé')
                 for g in accepted]
        if not lines:
            lines = ['Aucun joueur accepté.' if waiting else 'En attente d\'un joueur…']
        self.players_label.configure(text='\n'.join(lines))
        # Ne reconstruire les boutons que si les demandes changent (un clic n'est jamais perdu).
        key = tuple((g['session'], g['pseudo'], g['ip']) for g in waiting)
        if key == self._pending_key:
            return
        self._pending_key = key
        for child in self.pending_frame.winfo_children():
            child.destroy()
        for row, guest in enumerate(waiting):
            self.ttk.Label(self.pending_frame, style='Warning.TLabel', text='{} · {} · demande'.format(
                guest['pseudo'], guest['ip'])).grid(row=row, column=0, sticky='w', pady=(GAP // 2, 0))
            self.ttk.Button(self.pending_frame, text='Accepter', style='Accent.TButton',
                            command=lambda s=guest['session']: self._answer_guest(s, True)).grid(
                row=row, column=1, padx=(GAP, 0), pady=(GAP // 2, 0))
            self.ttk.Button(self.pending_frame, text='Refuser',
                            command=lambda s=guest['session']: self._answer_guest(s, False)).grid(
                row=row, column=2, padx=(GAP // 2, 0), pady=(GAP // 2, 0))

    def _answer_guest(self, session, accept):
        if self.room is None:
            return
        if accept:
            self.room.accept_guest(session)
        else:
            self.room.refuse_guest(session)
        self._refresh_players()
        for event in self.room.take_events():
            self.show('Room : ' + event, log_line=False)
        self._apply_room_state()

    def _launch_all(self):
        """Signal aux invites, puis lancement du jeu de l'hote (s'il est detecte et ferme)."""
        if self.room is None:
            return
        self.room.request_launch()
        self.show('Signal « Lancer pour tous » envoyé : les invités qui l\'ont autorisé lancent leur jeu.')
        try:
            running = game_is_running()
        except LauncherError:
            running = False
        if self.game.kind is None:
            self.show('Jeu introuvable sur ce PC : seuls les invités sont prévenus.', 'error')
        elif running:
            self.show('Votre jeu est déjà lancé : seuls les invités sont prévenus.')
        else:
            self._launch_game()

    # -- presence de l'invite (9b) --
    def _start_presence(self, ip, port, code):
        """Se signale a l'hote (meme room : garde la session et donc l'accord deja obtenu)."""
        import sims4mp_room as room
        current = self.presence
        if current and (current['ip'], current['port'], current['code']) == (ip, port, code):
            return
        self.presence = {'ip': ip, 'port': port, 'code': code, 'session': room.new_session_id(),
                         'etat': 'connecte', 'accord': 'attente', 'pending': None,
                         'handled': None, 'primed': False, 'failures': 0, 'busy': False}
        self._apply_presence_state()
        self.root.after(0, self._presence_tick)

    def _apply_presence_state(self):
        import sims4mp_room as room
        if self.presence is None:
            self.presence_label.configure(text='Non connecté à une room.', style='Muted.TLabel')
            self.leave_room_button.configure(state='disabled')
        else:
            state = ('en attente de l\'accord' if self.presence['accord'] == 'attente'
                     else room.GUEST_STATES[self.presence['etat']])
            self.presence_label.configure(style='TLabel', text='Connecté à {} · {}'.format(
                self.presence['ip'], state))
            self.leave_room_button.configure(state='normal')

    def _on_agreement(self, agreement):
        """Reponse de l'hote a notre demande ; lance l'action en attente une fois accepte."""
        presence = self.presence
        previous, presence['accord'] = presence['accord'], agreement
        if agreement == 'refuse':
            self.show('L\'hôte a refusé votre demande : rien n\'a été lu ni écrit.', 'error')
            self.set_status('Refusé par l\'hôte', 'error')
            self.presence = None
            self._apply_presence_state()
            return
        if agreement == 'accepte' and previous != 'accepte':
            self.show('L\'hôte a accepté votre demande.', 'ok')
        if agreement == 'accepte' and presence['pending']:
            action, presence['pending'] = presence['pending'], None
            self._room_actions()[action]()

    def _presence_tick(self):
        """Toutes les 2 s : traite la derniere reponse, puis envoie la presence (tache de fond)."""
        import sims4mp_room as room
        presence = self.presence
        if presence is None:
            return
        while True:
            try:
                session, kind, value = self.presence_results.get_nowait()
            except queue.Empty:
                break
            if self.presence is not presence or session != presence['session']:
                continue                                   # reponse d'une ancienne connexion
            presence['busy'] = False
            if kind == 'ok':
                presence['failures'] = 0
                self._on_agreement(value['accord'])
                if self.presence is not presence:
                    return                                 # refuse : presence arretee
                token = value['lancer']
                if presence['accord'] != 'accepte':
                    pass                                   # aucun signal avant l'accord
                elif not presence['primed']:
                    # Un signal emis avant notre accord ne nous concerne pas.
                    presence['handled'], presence['primed'] = token, True
                elif token and token != presence['handled']:
                    presence['handled'] = token
                    self._on_launch_signal()
            else:
                presence['failures'] += 1
                if presence['failures'] >= 3:
                    self.show('Room perdue après 3 échecs : {}'.format(value), 'error')
                    self.set_status('Room perdue : hôte injoignable', 'error')
                    self.presence = None
                    self._apply_presence_state()
                    return
        if self.presence is None:
            return
        if not presence['busy']:
            presence['busy'] = True
            args = (presence['ip'], presence['port'], presence['code'], presence['session'],
                    self.pseudo.get(), presence['etat'], bool(self.allow_host_launch.get()))

            def worker():
                try:
                    self.presence_results.put((args[3], 'ok', room.send_presence(*args)))
                except LauncherError as exc:
                    self.presence_results.put((args[3], 'error', str(exc)))
            self._spawn(worker)
        self._apply_presence_state()
        self.root.after(int(room.PRESENCE_INTERVAL * 1000), self._presence_tick)

    def _on_launch_signal(self):
        """Signal « Lancer pour tous » recu : lance le jeu d'ici, si toutes les conditions sont reunies."""
        reason = None
        if not self.allow_host_launch.get():
            reason = 'vous n\'avez pas coché « Laisser l\'hôte lancer mon jeu »'
        elif not self.received_this_session:
            reason = 'la partie de l\'hôte n\'a pas été reçue pendant cette session'
        elif self.game.kind is None:
            reason = 'jeu introuvable sur ce PC'
        if reason is None:
            target = game_target(self.game)
            try:
                lines = launch_game() if target == STEAM_GAME_URL else launch_game(target=target)
            except LauncherError as exc:
                reason = str(exc).splitlines()[0]
            else:
                self.presence['etat'] = 'jeu_lance'
                for line in lines:
                    self.show(line)
                self.show('L\'hôte a lancé la partie : jeu lancé.', 'ok')
                self.set_status('Jeu lancé par l\'hôte', 'ok')
        if reason is not None:
            self.presence['etat'] = 'lancement_refuse'
            self.show('L\'hôte a demandé le lancement, refusé : {}.'.format(reason), 'error')
            self.set_status('Lancement demandé par l\'hôte : refusé', 'error')
        self._apply_presence_state()

    def _leave_room(self):
        if self.presence is None:
            return
        self.presence = None
        self._apply_presence_state()
        self.show('Room quittée.')
        self.set_status('Room quittée')

    def _join_done(self):
        """Partie de l'hote installee : elle peut maintenant etre lancee par l'hote."""
        self.received_this_session = True
        if self.presence is not None:
            self.presence['etat'] = 'partie_recue'
            self._apply_presence_state()

    def _close_room(self):
        if self.room is None:
            return
        server, self.room = self.room, None
        server.stop()
        for event in server.take_events():
            self.show('Room : ' + event, log_line=False)
        self.set_status('Room fermée', 'ok')
        self._apply_room_state()

    def _copy_room(self):
        if self.room is None:
            return
        text = 'Sims4MP · IP {} · port {} · code {}'.format(self.room.bind_ip, self.room.port, self.room.code)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status('Invitation copiée', 'ok')

    def _join_params(self):
        import sims4mp_room as room
        return validate_ipv4(self.ip.get()), self._room_port(), room.validate_room_code(self.room_code.get())

    def _request_room(self, action):
        """Verifier ou Rejoindre : se signale d'abord a l'hote, puis agit une fois accepte."""
        try:
            ip, port, code = self._join_params()
        except (ValueError, LauncherError) as exc:
            self.show(str(exc), 'error')
            self.set_status(str(exc), 'error')
            return
        if action == 'join':
            self._auto_save(ROLE_JOIN)
        self._start_presence(ip, port, code)
        if self.presence['accord'] == 'accepte':
            self._room_actions()[action]()
            return
        self.presence['pending'] = action
        self.show('Demande envoyée à l\'hôte : en attente de son accord (rien n\'est lu avant).')
        self.set_status('En attente de l\'accord de l\'hôte')

    def _check_room(self):
        """« Verifier sans copier » : lit la room et decrit ce qui serait fait, sans rien ecrire."""
        self._request_room('check')

    def _join_room(self):
        self._request_room('join')

    def _sync_mods(self):
        self._request_room('mods')

    def _room_actions(self):
        return {'check': self._run_check, 'join': self._run_join, 'mods': self._run_mods}

    def _run_mods(self):
        import sims4mp_room as room
        p, documents = self.presence, self._documents()

        def task():
            lines, plan = room.plan_mods_sync(p['ip'], p['port'], p['code'], p['session'], documents, base_dir())
            self._mods_plan = (p['ip'], p['port'], p['code'], p['session'], plan, lines)
            if not plan['copier']:
                return lines + ['Rien à copier : vos mods sont ceux de l\'hôte.'], 'Mods identiques à l\'hôte'
            return lines, 'Mods comparés : confirmation demandée'
        self._mods_plan = None
        self._start_task('Comparaison des mods (SHA-256)...', lambda: self._run_worker(task),
                         after=self._confirm_mods)

    def _confirm_mods(self):
        """Rien n'est copie dans Mods sans un « Oui » explicite."""
        import sims4mp_room as room
        ip, port, code, session, plan, lines = self._mods_plan
        if not plan['copier']:
            return
        warning = ('\n\nATTENTION : {} script(s) .ts4script, c\'est du code qui s\'exécutera dans votre jeu. '
                   'Ne copiez que les mods d\'un hôte de confiance.'.format(plan['scripts'])
                   if plan['scripts'] else '')
        text = ('{} fichier(s) à copier depuis l\'hôte ({:.1f} Mo).{}\n\nChaque fichier est vérifié '
                '(taille, SHA-256) ; vos fichiers remplacés sont d\'abord rangés dans sims4mp_backups. '
                'Vos mods en plus ne sont pas touchés.\n\nCopier les mods ?').format(
            len(plan['copier']), plan['total'] / 1e6, warning)
        if not self._confirm('Copier les mods de l\'hôte', text):
            self.show('Copie des mods : annulée, rien n\'a été écrit.')
            self.set_status('Annulé : rien n\'a été écrit')
            return
        self.task_progress = None
        self._start_task('Copie des mods...', lambda: self._run_worker(
            lambda: room.apply_mods_sync(ip, port, code, session, plan, base_dir() / BACKUP_DIR_NAME, base_dir(),
                                         progress=self._set_progress)))

    def _run_check(self):
        import sims4mp_room as room
        p, documents = self.presence, self._documents()

        def task():
            info = room.fetch_room_info(p['ip'], p['port'], p['code'], p['session'])
            lines, plan = room.plan_join(info, documents)
            return lines + ['Vérification seulement : rien n\'a été écrit.'], 'Vérification OK : rien n\'a été écrit'
        self._start_task('Vérification de la room...', lambda: self._run_worker(task))

    def _run_join(self):
        import sims4mp_room as room
        p, documents = self.presence, self._documents()

        def task():
            info = room.fetch_room_info(p['ip'], p['port'], p['code'], p['session'])
            lines, plan = room.plan_join(info, documents)
            self._join_info = (p['ip'], p['port'], p['code'], p['session'], info, lines)
            return lines, 'Room trouvée : confirmation demandée'
        self._join_info = None
        self._start_task('Connexion à la room...', lambda: self._run_worker(task), after=self._confirm_join)

    def _confirm_join(self):
        """Rien n'est ecrit sans un « Oui » explicite ; la copie datee est faite par apply_join."""
        import sims4mp_room as room
        ip, port, code, session, info, lines = self._join_info
        text = '\n'.join(lines) + ('\n\nVos sauvegardes seront d\'abord copiées dans sims4mp_backups\\saves_… '
                                   '\nLes actions en jeu ne sont pas encore synchronisées : '
                                   'les deux parties évolueront séparément après le chargement.')
        if not self._confirm('Rejoindre la room', text + '\n\nInstaller cette partie ?'):
            self.show('Rejoindre la room : annulé, rien n\'a été écrit.')
            self.set_status('Annulé : rien n\'a été écrit')
            return
        documents = self._documents()
        self._start_task('Téléchargement de la partie...', lambda: self._run_worker(
            lambda: room.apply_join(ip, port, code, session, info, documents,
                                    base_dir() / BACKUP_DIR_NAME, base_dir())),
            after=self._join_done)

    def _quit(self):
        self._close_room()
        self.presence = None                 # l'hote retirera l'invite apres 10 s sans nouvelles
        self.root.destroy()

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
    def _start_task(self, message, worker, after=None):
        """Lance worker dans un thread ; after() est appele (fenetre) si la tache reussit."""
        if self.installing:
            return
        self.installing = True
        self._after_task = after
        for button in (self.update_button, self.check_button, self.play_button,
                       self.restore_button, self.diag_button):
            button.configure(state='disabled')
        self._apply_room_state()
        self.show(message)
        self.set_status(message)
        self._spawn(worker)
        self.root.after(100, self._poll_install)

    def _spawn(self, worker):
        threading.Thread(target=worker, daemon=True).start()

    def _update(self):
        self._start_task('Installation depuis GitHub...', self._update_worker)

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

    def _update_worker(self):
        allow_test = bool(self.allow_test.get())
        allow_downgrade = bool(self.allow_downgrade.get())

        manifest_url = self._manifest_url()

        def task():
            return run_update(manifest_url, self._documents(), base_dir() / BACKUP_DIR_NAME,
                              base_dir(), allow_test=allow_test, allow_downgrade=allow_downgrade)
        self._run_worker(task)

    def _set_progress(self, text):
        # Appele depuis le thread de la tache : simple affectation, lue par _poll_install.
        self.task_progress = text

    def _poll_install(self):
        try:
            kind, lines, summary = self.results.get_nowait()
        except queue.Empty:
            progress = getattr(self, 'task_progress', None)
            if progress:
                self.set_status(progress)                    # pourcentage pendant la copie
            self.root.after(100, self._poll_install)
            return
        self.task_progress = None
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
        for button in (self.update_button, self.check_button, self.diag_button):
            button.configure(state='normal')
        # Ces boutons dependent d'un etat : jeu detecte, sauvegardes presentes, room ouverte.
        self._apply_game_state()
        self._refresh_backups()
        self._apply_room_state()
        after, self._after_task = self._after_task, None
        if kind == 'ok' and after is not None:
            after()


def main():
    try:
        import tkinter as tk
        root = tk.Tk()
        LauncherApp(root)
        root.mainloop()
    except Exception:
        log('ERREUR au demarrage :\n' + traceback.format_exc())
        if not IS_WINDOWS:
            # Sur Mac le lanceur est ouvert depuis Terminal (ou le .command) : le message s'y affiche.
            sys.stderr.write('Le lanceur n\'a pas pu demarrer.\nDetail dans {}\n'.format(base_dir() / LOG_NAME))
            return 1
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
