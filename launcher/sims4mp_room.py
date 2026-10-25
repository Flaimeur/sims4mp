# Room Sims4MP : partage d'une sauvegarde de l'hote vers l'invite, en reseau local.
#
# Python 3.12, bibliotheque standard uniquement. Aucune fenetre ici : l'interface
# (sims4mp_launcher_gui.py) appelle ces fonctions.
#
# Hote : RoomServer fige une copie de la sauvegarde choisie et la sert en HTTP sur
#   le reseau local, seulement a des adresses privees qui donnent le code de room.
#   Deux adresses : /info (JSON) et /save (le fichier). Aucun chemin ne vient de
#   la requete.
# Invite : fetch_room_info lit et valide /info, plan_join decrit ce qui serait fait
#   (« Verifier sans copier »), apply_join telecharge, verifie (taille, SHA-256),
#   copie toutes les sauvegardes dans sims4mp_backups\saves_AAAAMMJJ_HHMMSS\, puis
#   installe dans le slot reserve Sims4MP par remplacement atomique.
# Mods : /mods donne la liste (avec SHA-256) ; /modfile/<n> sert le n-ieme fichier.
#   plan_mods_sync compare, apply_mods_sync copie ce qui manque ou differe, apres
#   verification de chaque fichier et copie datee des fichiers remplaces.
#
# Format des sauvegardes (etape 7a) : conteneur DBPF 2.1, ressource 0x0D compressee
# en RefPack, message protobuf SaveGameData. Champs confirmes dans
# FileSerialization_pb2 (generated.zip du jeu) : SaveGameData.save_slot=2,
# SaveGameData.households=5, SaveSlotData.slot_name=9, HouseholdData.name=3,
# HouseholdData.is_player=31.

import datetime
import hashlib
import hmac
import http.client
import http.server
import ipaddress
import json
import os
import re
import secrets
import shutil
import struct
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

import sims4mp_launcher_gui as core
import sims4mp_mods as mods_cmp

ROOM_PROTOCOL = 2                        # 2 : accord de l'hote, un envoi par invite accepte
ROOM_PORT_OFFSET = 1                     # port de la room = port du jeu + 1
MAX_SAVE_SIZE = 1024 * 1024 * 1024       # 1 Go
MAX_INFO_SIZE = 64 * 1024
MAX_BAD_CODES = 5
CODE_HEADER = 'X-Sims4MP-Code'
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'     # sans 0/O ni 1/I/L
CODE_LENGTH = 8
SAVE_NAME_RE = re.compile(r'Slot_[0-9a-fA-F]{8}\.save')
RESERVED_SLOT = 'Slot_534d5000.save'     # slot de l'invite reserve a Sims4MP (« SMP »)
VERSION_SUFFIXES = tuple('.ver{}'.format(i) for i in range(5))
INFO_KEYS = {'protocole', 'version_mod', 'fichier', 'taille', 'sha256', 'partie', 'foyers'}
CONNECT_TIMEOUT = 5

# Presence (etape 9b) : l'invite se signale toutes les 2 s ; l'hote renvoie le
# dernier signal de lancement. Aucune commande ni aucun chemin n'est envoye.
PRESENCE_INTERVAL = 2.0
PRESENCE_TIMEOUT = 10.0                  # sans nouvelles depuis 10 s : l'invite a quitte
PRESENCE_REQUEST_TIMEOUT = 3
MAX_GUESTS = 8
# L'hote peut mettre son mod a jour sans fermer la room : version et liste des mods sont
# relues avant de servir /info et /mods, au plus une fois toutes les HOST_REFRESH_GAP s.
HOST_REFRESH_GAP = 5.0
PSEUDO_MAX = 24
PSEUDO_HEADER = 'X-Sims4MP-Pseudo'       # UTF-8 encode en %XX (en-tetes HTTP en latin-1)
SESSION_HEADER = 'X-Sims4MP-Session'
STATE_HEADER = 'X-Sims4MP-Etat'
ALLOW_HEADER = 'X-Sims4MP-Autorise'
GUEST_STATES = {'connecte': 'connecté', 'partie_recue': 'partie reçue',
                'jeu_lance': 'jeu lancé', 'lancement_refuse': 'lancement refusé'}
RECEIVED_STATES = ('partie_recue', 'jeu_lance')       # l'invite a verifie et installe la partie
AGREEMENTS = ('attente', 'accepte', 'refuse')        # accord de l'hote pour un invite
SESSION_RE = re.compile(r'[0-9a-f]{16,32}')
AUTO_SAVE_NAME = 'slot_ffffffff.save'                # sauvegarde automatique du jeu

# Copie des mods de l'hote vers l'invite : /modfile/<n> sert le n-ieme mod de la
# liste /mods (aucun chemin ne vient de la requete). L'invite verifie taille et
# SHA-256 de chaque fichier et range d'abord ses versions remplacees.
MODFILE_RE = re.compile(r'/modfile/(\d{1,6})')
MAX_SYNC_FILE = 2 * 1024 ** 3                         # 2 Go par fichier
MAX_SYNC_TOTAL = 20 * 1024 ** 3                       # 20 Go en tout
DISK_MARGIN = 1024 ** 3                               # garder 1 Go libre apres la copie
WINDOWS_RESERVED = re.compile(r'(con|prn|aux|nul|com\d|lpt\d)(\..*)?', re.IGNORECASE)


class RoomError(core.LauncherError):
    """Erreur de room : message affiche tel quel."""


# --- Lecture d'une sauvegarde (defensive : jamais d'exception vers l'appelant) ---

MAX_INDEX_ENTRIES = 100000
MAX_RESOURCE_SIZE = 256 * 1024 * 1024


def refpack_decompress(src, limit=MAX_RESOURCE_SIZE):
    """Decompression RefPack (QFS), compression 0xFFFF des paquets Sims 4."""
    if len(src) < 5 or src[1] != 0xFB:
        raise ValueError('pas du RefPack')
    size_len = 4 if src[0] & 0x80 else 3
    out_size = int.from_bytes(src[2:2 + size_len], 'big')
    if out_size > limit:
        raise ValueError('ressource trop grande')
    pos = 2 + size_len
    out = bytearray()
    while pos < len(src):
        b0 = src[pos]
        if b0 < 0x80:
            b1 = src[pos + 1]
            plain, copy, dist = b0 & 3, ((b0 >> 2) & 7) + 3, ((b0 & 0x60) << 3) + b1 + 1
            pos += 2
        elif b0 < 0xC0:
            b1, b2 = src[pos + 1], src[pos + 2]
            plain, copy, dist = (b1 >> 6) & 3, (b0 & 0x3F) + 4, ((b1 & 0x3F) << 8) + b2 + 1
            pos += 3
        elif b0 < 0xE0:
            b1, b2, b3 = src[pos + 1], src[pos + 2], src[pos + 3]
            plain, copy = b0 & 3, ((b0 & 0x0C) << 6) + b3 + 5
            dist = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
            pos += 4
        elif b0 < 0xFC:
            plain = ((b0 & 0x1F) << 2) + 4
            out += src[pos + 1:pos + 1 + plain]
            pos += 1 + plain
            if len(out) > out_size:
                raise ValueError('flux RefPack invalide')
            continue
        else:
            out += src[pos + 1:pos + 1 + (b0 & 3)]
            break
        out += src[pos:pos + plain]
        pos += plain
        start = len(out) - dist
        if start < 0 or len(out) + copy > out_size:
            raise ValueError('flux RefPack invalide')
        for i in range(copy):
            out.append(out[start + i])
    if len(out) != out_size:
        raise ValueError('taille {} au lieu de {}'.format(len(out), out_size))
    return bytes(out)


def _dbpf_entries(data):
    if data[:4] != b'DBPF' or len(data) < 96:
        raise ValueError('pas un paquet DBPF')
    count = struct.unpack_from('<I', data, 0x24)[0]
    if count > MAX_INDEX_ENTRIES:
        raise ValueError('index trop grand')
    pos = struct.unpack_from('<Q', data, 0x40)[0] or struct.unpack_from('<I', data, 0x28)[0]
    flags = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    const = {}
    for bit, name in enumerate(('type', 'group', 'inst_hi')):
        if flags & (1 << bit):
            const[name] = struct.unpack_from('<I', data, pos)[0]
            pos += 4
    entries = []
    for _ in range(count):
        rec = {}
        for name in ('type', 'group', 'inst_hi'):
            if name in const:
                rec[name] = const[name]
            else:
                rec[name] = struct.unpack_from('<I', data, pos)[0]
                pos += 4
        rec['inst_lo'], rec['offset'], size_raw, rec['usize'] = struct.unpack_from('<IIII', data, pos)
        pos += 16
        rec['size'] = size_raw & 0x7FFFFFFF
        rec['comp'] = 0
        if size_raw & 0x80000000:
            rec['comp'] = struct.unpack_from('<H', data, pos)[0]
            pos += 4
        entries.append(rec)
    return entries


def _varint(buf, pos):
    shift = value = 0
    while True:
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError('varint invalide')


def _proto_fields(buf):
    """Decodage protobuf generique : (numero, valeur) ; valeur bytes ou int."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        num, wire = key >> 3, key & 7
        if wire == 0:
            val, pos = _varint(buf, pos)
        elif wire == 2:
            size, pos = _varint(buf, pos)
            if pos + size > len(buf):
                raise ValueError('champ tronque')
            val, pos = buf[pos:pos + size], pos + size
        elif wire == 5:
            val, pos = buf[pos:pos + 4], pos + 4
        elif wire == 1:
            val, pos = buf[pos:pos + 8], pos + 8
        else:
            raise ValueError('type de champ {}'.format(wire))
        yield num, val


def _text(value, limit=200):
    return value.decode('utf-8', 'replace')[:limit] if isinstance(value, bytes) else None


def read_save_info(path):
    """{'partie': nom ou None, 'foyers': [foyers joueurs]} ; jamais d'exception."""
    info = {'partie': None, 'foyers': []}
    try:
        path = Path(path)
        if path.stat().st_size > MAX_SAVE_SIZE:
            return info
        data = path.read_bytes()
        entry = next(e for e in _dbpf_entries(data) if e['type'] == 0x0D)
        raw = data[entry['offset']:entry['offset'] + entry['size']]
        if entry['comp'] == 0xFFFF:
            blob = refpack_decompress(raw)
        elif entry['comp'] == 0:
            blob = raw
        else:
            return info
        for num, val in _proto_fields(blob):
            if num == 2 and isinstance(val, bytes):
                for n2, v2 in _proto_fields(val):
                    if n2 == 9:
                        info['partie'] = _text(v2)
            elif num == 5 and isinstance(val, bytes):
                house = dict(_proto_fields(val))
                if house.get(31) and isinstance(house.get(3), bytes) and len(info['foyers']) < 20:
                    info['foyers'].append(_text(house[3], 100))
    except (OSError, ValueError, IndexError, struct.error, StopIteration):
        pass
    return info


# --- Dossier des sauvegardes ---------------------------------------------------

def saves_dir(documents):
    """Dossier saves a cote du dossier Mods trouve (meme regle que l'installation)."""
    folder = core.find_mods_dir(documents).parent / 'saves'
    if not folder.is_dir():
        raise RoomError('Dossier des sauvegardes introuvable : {}'.format(folder))
    return folder


def is_auto_save(path):
    return Path(path).name.lower() == AUTO_SAVE_NAME


def list_saves(folder):
    """Sauvegardes Slot_XXXXXXXX.save : parties manuelles de la plus recente a la plus
    ancienne, puis la sauvegarde automatique (jamais proposee par defaut)."""
    folder = Path(folder)
    found = [p for p in folder.iterdir()
             if SAVE_NAME_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    return sorted(found, key=lambda p: (is_auto_save(p), -p.stat().st_mtime))


def save_label(path, info=None):
    info = info or read_save_info(path)
    stat = Path(path).stat()
    when = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M')
    name = info['partie'] or Path(path).name
    houses = ', '.join(info['foyers']) or 'foyer non lu'
    auto = ' (sauvegarde automatique)' if Path(path).name.lower() == 'slot_ffffffff.save' else ''
    return '{}{} · {} · {} · {:.1f} Mo'.format(name, auto, houses, when, stat.st_size / 1e6)


# --- Hote : serveur de room -----------------------------------------------------

def new_room_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def clean_pseudo(text):
    """Pseudo affichable : caracteres imprimables, 24 au plus, « Joueur » si vide."""
    text = ''.join(c for c in str(text) if c.isprintable()).strip()[:PSEUDO_MAX]
    return text or 'Joueur'


def new_session_id():
    return secrets.token_hex(8)


def is_allowed_client(address):
    """Seulement les adresses de reseau prive (et la boucle locale pour les tests)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback) and not ip.is_unspecified and not ip.is_multicast


class RoomServer:
    """Sert une copie figee d'une sauvegarde. start() / stop() ; events pour l'interface."""

    def __init__(self, save_path, saves_folder, snapshot_dir, mod_version, bind_ip, port, code=None,
                 mods_dir=None, mods_sha=False, mods_cache=None, packs=None):
        self.packs = list(packs) if packs is not None else None    # packs de l'hote (/packs), None : inconnus
        self.mods_dir = Path(mods_dir) if mods_dir else None
        self.mods_sha = mods_sha
        self.mods_cache = mods_cache
        self.mods = None                 # liste servie sur /mods (None : comparaison indisponible)
        self.save_path = Path(save_path)
        self.saves_folder = Path(saves_folder)
        self.snapshot_dir = Path(snapshot_dir)
        self.mod_version = mod_version
        self.bind_ip = bind_ip
        self.port = port
        self.code = code or new_room_code()
        self.bad_codes = 0
        self.locked = False
        self.events = []
        self.snapshot = None
        self.info = None
        self._httpd = None
        self._lock = threading.Lock()
        # session -> {'session', 'pseudo', 'ip', 'etat', 'autorise', 'vu', 'accord', 'recu'}
        self.guests = {}
        self.refused = set()             # sessions refusees jusqu'a la fermeture de la room
        self.sharing_open = True         # la partie est-elle encore telechargeable ?
        self.launch_token = None         # dernier signal « Lancer pour tous »
        self._clock = time.monotonic     # remplacable en test
        self._refreshed_at = None        # derniere relecture du mod et des mods de l'hote

    def update_guest(self, session, ip, pseudo, state, allowed):
        """Enregistre la presence d'un invite. Renvoie son accord ('attente', 'accepte',
        'refuse'), ou 'plein' / 'autre_ip' si la presence est refusee."""
        if session in self.refused:
            return 'refuse'
        received = None
        with self._lock:
            guest = self.guests.get(session)
            joined = guest is None
            if joined:
                if len(self.guests) >= MAX_GUESTS:
                    return 'plein'
                guest = self.guests[session] = {'session': session, 'ip': ip, 'etat': None,
                                                'accord': 'attente', 'recu': False}
            elif guest['ip'] != ip:
                return 'autre_ip'                        # l'accord vaut pour une seule adresse
            changed = guest['etat'] != state
            guest.update(pseudo=pseudo, etat=state, autorise=allowed, vu=self._clock())
            if guest['accord'] == 'accepte' and state in RECEIVED_STATES and not guest['recu']:
                guest['recu'] = received = True
            agreement = guest['accord']
        if joined:
            self._event('{} demande à rejoindre la room ({}) : en attente de votre accord'.format(pseudo, ip))
        elif changed:
            self._event('{} : {}'.format(pseudo, GUEST_STATES[state]))
        if received:
            self._event('{} a reçu et vérifié la partie'.format(pseudo))
            self._close_sharing_if_done()
        return agreement

    def accept_guest(self, session):
        with self._lock:
            guest = self.guests.get(session)
            if guest is None or guest['accord'] != 'attente':
                return False
            guest['accord'] = 'accepte'
            pseudo = guest['pseudo']
        self._event('{} accepté : il peut lire la room et recevoir la partie'.format(pseudo))
        return True

    def refuse_guest(self, session):
        with self._lock:
            guest = self.guests.pop(session, None)
            self.refused.add(session)
        if guest is not None:
            self._event('{} refusé'.format(guest['pseudo']))
            self._close_sharing_if_done()
        return guest is not None

    def _close_sharing_if_done(self):
        """Ferme le partage quand tous les invites acceptes ont recu la partie."""
        with self._lock:
            accepted = [g for g in self.guests.values() if g['accord'] == 'accepte']
            done = self.sharing_open and accepted and all(g['recu'] for g in accepted)
            if done:
                self.sharing_open = False
        if done:
            self._drop_snapshot()
            self._event('Partage fermé : chaque invité accepté a reçu la partie (la room reste ouverte)')

    def _drop_snapshot(self):
        if self.snapshot is not None:
            try:
                self.snapshot.unlink()
            except OSError:
                pass
            self.snapshot = None

    def authorize(self, session, ip, path):
        """(None, None) si l'invite peut lire path, sinon (statut HTTP, raison)."""
        with self._lock:
            guest = self.guests.get(session) if SESSION_RE.fullmatch(session or '') else None
            if session in self.refused:
                return 403, 'invité refusé'
            if guest is None or guest['ip'] != ip:
                return 409, 'invité inconnu : présence et accord requis'
            if guest['accord'] != 'accepte':
                return 409, 'en attente de l\'accord de l\'hôte'
            if path == '/save' and (not self.sharing_open or guest['recu']):
                return 410, 'partie déjà reçue ou partage fermé'
        return None, None

    def guests_snapshot(self):
        """Invites encore presents (les silencieux depuis 10 s sont retires)."""
        now = self._clock()
        with self._lock:
            gone = [s for s, g in self.guests.items() if now - g['vu'] > PRESENCE_TIMEOUT]
            left = [self.guests.pop(s)['pseudo'] for s in gone]
            current = [dict(g) for g in self.guests.values()]
        for pseudo in left:
            self._event('{} a quitté la room (plus de nouvelles)'.format(pseudo))
        return current

    def request_launch(self):
        """Publie un nouveau signal de lancement ; chaque invite ne le traite qu'une fois."""
        self.launch_token = secrets.token_hex(8)
        self._event('Signal « Lancer pour tous » envoyé')
        return self.launch_token

    def _event(self, text):
        with self._lock:
            self.events.append(text)
        core.log('Room : ' + text)

    def take_events(self):
        with self._lock:
            events, self.events = self.events, []
        return events

    def prepare(self, is_running=None):
        """Verifie la sauvegarde choisie et en fait une copie figee."""
        is_running = is_running or core.game_is_running      # resolu a l'appel (remplacable en test)
        if (not SAVE_NAME_RE.fullmatch(self.save_path.name) or not self.save_path.is_file()
                or self.save_path.parent.resolve() != self.saves_folder.resolve()):
            raise RoomError('Sauvegarde invalide : {}'.format(self.save_path))
        if is_running():
            raise RoomError('Fermez Les Sims 4 avant de créer la room '
                            '(la sauvegarde pourrait être en cours d\'écriture).')
        size = self.save_path.stat().st_size
        if size > MAX_SAVE_SIZE:
            raise RoomError('Sauvegarde trop grande : {:.0f} Mo (maximum {:.0f} Mo).'.format(
                size / 1e6, MAX_SAVE_SIZE / 1e6))
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='sims4mp_room_', suffix='.save', dir=str(self.snapshot_dir))
        os.close(fd)
        self.snapshot = Path(tmp)
        shutil.copyfile(self.save_path, self.snapshot)          # lecture seule de l'original
        info = read_save_info(self.snapshot)
        self.info = {
            'protocole': ROOM_PROTOCOL,
            'version_mod': self.mod_version,
            'fichier': self.save_path.name,
            'taille': self.snapshot.stat().st_size,
            'sha256': core.sha256_of(self.snapshot),
            'partie': info['partie'],
            'foyers': info['foyers'],
        }
        if self.mods_dir is not None:
            # Inventaire fait ici (tache de fond) : /mods repond ensuite sans attendre.
            self.mods = mods_cmp.mods_list(self.mods_dir, self.mods_sha, self.mods_cache)
        self._refreshed_at = self._clock()
        return self.info

    def refresh_host(self, force=False):
        """Relit la version du mod et la liste des mods de l'hote (mise a jour pendant que la
        room est ouverte). Au plus une fois toutes les HOST_REFRESH_GAP s, sauf force."""
        if self.mods_dir is None or self.info is None:
            return
        now = self._clock()
        with self._lock:
            if not force and self._refreshed_at is not None and now - self._refreshed_at < HOST_REFRESH_GAP:
                return
            self._refreshed_at = now
        mod = self.mods_dir / core.MOD_FILE
        version = core.read_mod_version(mod) if mod.is_file() else 'inconnue'
        mods = mods_cmp.mods_list(self.mods_dir, self.mods_sha, self.mods_cache)
        with self._lock:
            old = self.info['version_mod']
            self.mod_version = version
            self.info = dict(self.info, version_mod=version)
            self.mods = mods
        if version != old:
            self._event('Mod de l\'hôte mis à jour : version {} (avant : {})'.format(version, old))

    def mod_file(self, index):
        """(chemin, entree, None) pour le n-ieme mod de la liste, sinon (None, entree ou None, raison).
        Le fichier doit etre encore dans Mods, sans lien, avec la taille annoncee."""
        mods = self.mods['mods'] if self.mods is not None else []
        if self.mods_dir is None or not 0 <= index < len(mods):
            return None, None, 'mod inconnu'
        entry = mods[index]
        path = self.mods_dir / entry['chemin']
        try:
            inside = path.resolve().is_relative_to(self.mods_dir.resolve())
            ok = inside and not path.is_symlink() and path.is_file() and path.stat().st_size == entry['taille']
        except OSError:
            ok = False
        if not ok:
            return None, entry, 'mod modifié ou supprimé depuis la création de la room'
        return path, entry, None

    def start(self):
        if self.info is None:
            raise RoomError('Room non préparée.')
        room = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = 'Sims4MP-Room'
            sys_version = ''

            def log_message(self, *args):
                pass

            def _deny(self, code, text):
                self.send_response(code)
                self.send_header('Content-Length', '0')
                self.end_headers()
                room._event('{} refusé : {}'.format(self.client_address[0], text))

            def do_GET(self):
                client = self.client_address[0]
                if not is_allowed_client(client):
                    return self._deny(403, 'adresse hors réseau privé')
                if room.locked:
                    return self._deny(423, 'room verrouillée')
                given = self.headers.get(CODE_HEADER, '')
                if not hmac.compare_digest(given.encode('utf-8', 'replace'), room.code.encode()):
                    with room._lock:
                        room.bad_codes += 1
                        if room.bad_codes >= MAX_BAD_CODES:
                            room.locked = True
                    return self._deny(401, 'code de room faux')
                modfile = MODFILE_RE.fullmatch(self.path)
                if self.path in ('/info', '/save', '/mods', '/packs') or modfile:
                    # Rien n'est lisible sans l'accord de l'hote pour cette session et cette IP.
                    status, reason = room.authorize(self.headers.get(SESSION_HEADER, ''), client, self.path)
                    if status is not None:
                        return self._deny(status, reason)
                if self.path in ('/info', '/mods'):
                    room.refresh_host()                  # mod de l'hote peut-etre mis a jour depuis
                if self.path == '/info':
                    body = json.dumps(room.info).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    room._event('{} a lu les informations de la room'.format(client))
                elif self.path == '/save':
                    snapshot = room.snapshot
                    if snapshot is None:
                        return self._deny(410, 'partage fermé')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(room.info['taille']))
                    self.end_headers()
                    try:
                        with open(snapshot, 'rb') as f:
                            shutil.copyfileobj(f, self.wfile, 256 * 1024)
                    except OSError:
                        room._event('{} : envoi interrompu'.format(client))
                        return
                    room._event('Sauvegarde envoyée à {}'.format(client))
                elif self.path == '/presence':
                    session = self.headers.get(SESSION_HEADER, '')
                    state = self.headers.get(STATE_HEADER, '')
                    allowed = self.headers.get(ALLOW_HEADER, '')
                    if (not SESSION_RE.fullmatch(session) or state not in GUEST_STATES
                            or allowed not in ('0', '1')):
                        return self._deny(400, 'présence mal formée')
                    pseudo = clean_pseudo(urllib.parse.unquote(self.headers.get(PSEUDO_HEADER, ''),
                                                               errors='replace'))
                    agreement = room.update_guest(session, client, pseudo, state, allowed == '1')
                    if agreement == 'plein':
                        return self._deny(429, 'room pleine')
                    if agreement == 'autre_ip':
                        return self._deny(403, 'session déjà utilisée depuis une autre adresse')
                    # Le signal de lancement n'est transmis qu'aux invites acceptes.
                    token = room.launch_token if agreement == 'accepte' else None
                    body = json.dumps({'lancer': token, 'accord': agreement}).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == '/packs' and room.packs is not None:
                    body = json.dumps({'packs': room.packs}).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == '/mods' and room.mods is not None:
                    body = json.dumps(room.mods).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    room._event('{} a comparé ses mods ({} mods de l\'hôte)'.format(client, len(room.mods['mods'])))
                elif modfile and room.mods is not None:
                    path, entry, reason = room.mod_file(int(modfile.group(1)))
                    if path is None:
                        return self._deny(409 if entry is not None else 404, reason)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(entry['taille']))
                    self.end_headers()
                    try:
                        with open(path, 'rb') as f:
                            shutil.copyfileobj(f, self.wfile, 256 * 1024)
                    except OSError:
                        core.log('Room : {} : envoi du mod {} interrompu'.format(client, entry['chemin']))
                        return
                    # Journal seulement : des centaines de mods noieraient les evenements de la room.
                    core.log('Room : mod envoyé à {} : {}'.format(client, entry['chemin']))
                else:
                    self._deny(404, 'adresse inconnue {}'.format(self.path[:40]))

        self._httpd = http.server.ThreadingHTTPServer((self.bind_ip, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self._event('Room ouverte sur {}:{}'.format(self.bind_ip, self.port))
        return self.port

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._event('Room fermée')
        self._drop_snapshot()


# --- Invite ----------------------------------------------------------------------

def validate_room_code(code):
    text = str(code).strip().upper()
    if len(text) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in text):
        raise RoomError('Code de room invalide : {} caractères attendus (lettres et chiffres).'.format(
            CODE_LENGTH))
    return text


def validate_room_info(data):
    """Valide /info ; le nom de fichier est reduit a son nom de base et controle."""
    if not isinstance(data, dict) or set(data) != INFO_KEYS:
        raise RoomError('Réponse de la room invalide (champs inattendus).')
    if data['protocole'] != ROOM_PROTOCOL:
        raise RoomError('Version de room incompatible : {} (attendu {}).'.format(
            data['protocole'], ROOM_PROTOCOL))
    name = data['fichier']
    if not isinstance(name, str) or os.path.basename(name.replace('\\', '/')) != name \
            or not SAVE_NAME_RE.fullmatch(name):
        raise RoomError('Nom de sauvegarde refusé : {!r}'.format(name))
    size = data['taille']
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_SAVE_SIZE:
        raise RoomError('Taille de sauvegarde refusée : {} (maximum {:.0f} Mo).'.format(
            size, MAX_SAVE_SIZE / 1e6))
    sha = data['sha256']
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise RoomError('Empreinte SHA-256 invalide.')
    version = data['version_mod']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+|inconnue', version):
        raise RoomError('Version du mod de l\'hôte invalide.')
    partie = data['partie']
    if partie is not None and (not isinstance(partie, str) or len(partie) > 200):
        raise RoomError('Nom de partie invalide.')
    foyers = data['foyers']
    if not isinstance(foyers, list) or len(foyers) > 20 or \
            any(not isinstance(f, str) or len(f) > 100 for f in foyers):
        raise RoomError('Liste de foyers invalide.')
    return dict(data)


def _request(ip, port, code, path, timeout, extra_headers=None):
    ip, port = core.validate_ipv4(ip), core.validate_port(port)
    conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        headers = {CODE_HEADER: code, 'User-Agent': core.USER_AGENT}
        headers.update(extra_headers or {})
        conn.request('GET', path, headers=headers)
        return conn, conn.getresponse()
    except BaseException:
        conn.close()
        raise


def _check_status(response):
    if response.status == 401:
        raise RoomError('Code de room refusé par l\'hôte.')
    if response.status == 423:
        raise RoomError('Room verrouillée après trop de codes faux : l\'hôte doit la recréer.')
    if response.status == 403:
        raise RoomError('L\'hôte refuse cette connexion (refus de l\'hôte, ou adresse hors réseau privé).')
    if response.status == 409:
        raise RoomError('En attente de l\'accord de l\'hôte.')
    if response.status == 410:
        raise RoomError('Partie déjà reçue, ou partage fermé par l\'hôte : rien n\'a été écrit.')
    if response.status != 200:
        raise RoomError('Réponse inattendue de l\'hôte (HTTP {}).'.format(response.status))


def _session_headers(session):
    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
        raise RoomError('Session de room invalide.')
    return {SESSION_HEADER: session}


def fetch_room_info(ip, port, code, session, timeout=CONNECT_TIMEOUT):
    """Informations de la room ; lisibles seulement apres l'accord de l'hote pour cette session."""
    code = validate_room_code(code)
    headers = _session_headers(session)
    try:
        conn, response = _request(ip, port, code, '/info', timeout, headers)
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Room injoignable ({}:{}) : {}. Vérifiez l\'IP, le port, et que l\'hôte a '
                        'créé la room.'.format(ip, port, exc)) from None
    try:
        _check_status(response)
        body = response.read(MAX_INFO_SIZE + 1)
        if len(body) > MAX_INFO_SIZE:
            raise RoomError('Réponse de la room trop grande.')
        try:
            data = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RoomError('Réponse de la room illisible.') from None
        return validate_room_info(data)
    finally:
        conn.close()


def send_presence(ip, port, code, session, pseudo, state, allowed, timeout=PRESENCE_REQUEST_TIMEOUT):
    """Signale l'invite a l'hote ; renvoie {'lancer': signal ou None, 'accord': 'attente' |
    'accepte' | 'refuse'}."""
    code = validate_room_code(code)
    if not SESSION_RE.fullmatch(session) or state not in GUEST_STATES:
        raise RoomError('Présence invalide.')
    headers = {SESSION_HEADER: session, STATE_HEADER: state, ALLOW_HEADER: '1' if allowed else '0',
               PSEUDO_HEADER: urllib.parse.quote(clean_pseudo(pseudo), safe='')}
    try:
        conn, response = _request(ip, port, code, '/presence', timeout, headers)
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Hôte injoignable : {}'.format(exc)) from None
    try:
        if response.status == 404:
            raise RoomError('L\'hôte ne gère pas la présence (lanceur trop ancien).')
        if response.status == 429:
            raise RoomError('Room pleine ({} joueurs au maximum).'.format(MAX_GUESTS))
        _check_status(response)
        body = response.read(1025)
        try:
            data = json.loads(body.decode('utf-8')) if len(body) <= 1024 else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if not isinstance(data, dict) or set(data) != {'lancer', 'accord'} or data['accord'] not in AGREEMENTS:
            raise RoomError('Réponse de présence invalide.')
        token = data['lancer']
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{16}', token)):
            raise RoomError('Réponse de présence invalide.')
        return {'lancer': token, 'accord': data['accord']}
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Présence interrompue : {}'.format(exc)) from None
    finally:
        conn.close()


def fetch_mods_list(ip, port, code, session, timeout=15):
    """Liste des mods de l'hote (/mods), validee ; apres l'accord de l'hote."""
    code = validate_room_code(code)
    headers = _session_headers(session)
    try:
        conn, response = _request(ip, port, code, '/mods', timeout, headers)
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Room injoignable ({}:{}) : {}.'.format(ip, port, exc)) from None
    try:
        if response.status == 404:
            raise mods_cmp.ModsError('L\'hôte ne propose pas la comparaison des mods '
                                     '(lanceur trop ancien ou option désactivée).')
        _check_status(response)
        body = response.read(mods_cmp.MAX_LIST_SIZE + 1)
        if len(body) > mods_cmp.MAX_LIST_SIZE:
            raise mods_cmp.ModsError('Liste de mods de l\'hôte trop grande.')
        try:
            data = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise mods_cmp.ModsError('Liste de mods de l\'hôte illisible.') from None
        return mods_cmp.validate_mods_list(data)
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Lecture de la liste des mods interrompue : {}'.format(exc)) from None
    finally:
        conn.close()


def fetch_packs(ip, port, code, session, timeout=CONNECT_TIMEOUT):
    """Packs installes chez l'hote (/packs) ; None si son lanceur ne les donne pas (trop ancien)."""
    code = validate_room_code(code)
    headers = _session_headers(session)
    try:
        conn, response = _request(ip, port, code, '/packs', timeout, headers)
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Room injoignable ({}:{}) : {}.'.format(ip, port, exc)) from None
    try:
        if response.status == 404:
            return None
        _check_status(response)
        body = response.read(MAX_INFO_SIZE + 1)
        try:
            data = json.loads(body.decode('utf-8')) if len(body) <= MAX_INFO_SIZE else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        packs = data.get('packs') if isinstance(data, dict) and set(data) == {'packs'} else None
        if not isinstance(packs, list) or len(packs) > core.MAX_PACKS or \
                any(not isinstance(p, str) or not core.PACK_RE.fullmatch(p) for p in packs):
            raise RoomError('Liste des packs de l\'hôte invalide.')
        return sorted(set(packs))
    except (OSError, http.client.HTTPException) as exc:
        raise RoomError('Lecture des packs de l\'hôte interrompue : {}'.format(exc)) from None
    finally:
        conn.close()


def run_mod_compare(ip, port, code, session, documents, report_dir):
    """Compare les mods de l'hote a ceux de l'invite, en lecture seule ; ecrit
    seulement le rapport dans report_dir. Renvoie (lignes, statut_court)."""
    host = fetch_mods_list(ip, port, code, session)
    guest = mods_cmp.scan_mods(core.find_mods_dir(documents), with_sha=host['avec_sha'],
                               cache_path=Path(report_dir) / mods_cmp.CACHE_NAME)
    result = mods_cmp.compare_mods(host['mods'], guest, use_sha=host['avec_sha'])
    lines = mods_cmp.report_lines(result, '{}:{}'.format(ip, port))
    path = mods_cmp.write_report(report_dir, lines)
    lines.append('Rapport : {}'.format(path))
    return lines, mods_cmp.summary_text(result)


def _safe_rel_path(rel):
    """Chemin relatif de l'hote utilisable dans Mods sur Windows comme sur Mac, sinon None."""
    parts = rel.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part != part.rstrip('. ') or WINDOWS_RESERVED.fullmatch(part)
                or any(c in part for c in '<>:"|?*') or any(ord(c) < 32 for c in part)):
            return None
    return parts


def plan_mods_sync(ip, port, code, session, documents, cache_dir, is_running=None):
    """Compare les mods et prepare la copie de ceux qui manquent ou different, sans rien
    ecrire dans Mods. Renvoie (lignes, plan) ; plan['copier'] vide : rien a faire."""
    is_running = is_running or core.game_is_running
    host = fetch_mods_list(ip, port, code, session)
    if not host['avec_sha']:
        raise mods_cmp.ModsError('L\'hôte n\'envoie pas les empreintes SHA-256 de ses mods : copie '
                                 'impossible (lanceur de l\'hôte trop ancien).')
    mods_dir = core.find_mods_dir(documents)
    guest = mods_cmp.scan_mods(mods_dir, with_sha=True, cache_path=Path(cache_dir) / mods_cmp.CACHE_NAME)
    result = mods_cmp.compare_mods(host['mods'], guest, use_sha=True)
    index = {id(entry): n for n, entry in enumerate(host['mods'])}
    # Un fichier de l'invite identique a un mod de l'hote (meme nom, meme SHA-256) reste en
    # place, meme s'il porte le nom d'un autre mod de l'hote (doublons dans deux dossiers).
    host_keys = {(e['nom'].casefold(), e['sha256']) for e in host['mods']}
    todo = [(e, []) for e in result['manquants']]
    for entry, candidates in result['differents']:
        todo.append((entry, [g for g in candidates if (g['nom'].casefold(), g['sha256']) not in host_keys]))
    copies, total, scripts = [], 0, 0
    for entry, replaced in todo:
        parts = _safe_rel_path(entry['chemin'])
        if parts is None:
            raise mods_cmp.ModsError('Chemin de mod inutilisable ici : {!r}'.format(entry['chemin'][:80]))
        if entry['taille'] > MAX_SYNC_FILE:
            raise mods_cmp.ModsError('Mod trop grand ({}, {:.1f} Go ; maximum {:.0f} Go par fichier).'.format(
                entry['nom'], entry['taille'] / 1024 ** 3, MAX_SYNC_FILE / 1024 ** 3))
        total += entry['taille']
        scripts += entry['nom'].lower().endswith('.ts4script')
        copies.append({'index': index[id(entry)], 'entree': entry, 'cible': mods_dir.joinpath(*parts),
                       'remplaces': [mods_dir / g['chemin'] for g in replaced]})
    if total > MAX_SYNC_TOTAL:
        raise mods_cmp.ModsError('Trop de mods à copier : {:.1f} Go (maximum {:.0f} Go).'.format(
            total / 1024 ** 3, MAX_SYNC_TOTAL / 1024 ** 3))
    if copies and shutil.disk_usage(mods_dir).free < total + DISK_MARGIN:
        raise mods_cmp.ModsError('Espace disque insuffisant pour copier {:.1f} Go de mods.'.format(total / 1e9))
    if copies and is_running():
        raise RoomError('Fermez Les Sims 4 avant de copier les mods.')
    lines = mods_cmp.report_lines(result, '{}:{}'.format(ip, port))[:-1]
    lines.append('À copier depuis l\'hôte : {} fichier(s), {:.1f} Mo, dont {} script(s) .ts4script.'.format(
        len(copies), total / 1e6, scripts))
    replaced = sum(len(c['remplaces']) for c in copies)
    if replaced:
        lines.append('{} de vos fichiers seront remplacés (rangés d\'abord dans sims4mp_backups).'.format(replaced))
    if result['en_plus']:
        lines.append('Vos {} mod(s) en plus ne sont pas touchés.'.format(len(result['en_plus'])))
    plan = {'mods_dir': mods_dir, 'copier': copies, 'total': total, 'scripts': scripts}
    return lines, plan


def progress_text(received, total, files_done, files_total):
    """'Copie des mods : 42 % (3/7 fichiers, 12.5 / 30.0 Mo)'"""
    percent = 100 if total <= 0 else min(100, int(received * 100 / total))
    return 'Copie des mods : {} % ({}/{} fichiers, {:.1f} / {:.1f} Mo)'.format(
        percent, files_done, files_total, received / 1e6, total / 1e6)


def apply_mods_sync(ip, port, code, session, plan, backup_root, temp_dir, is_running=None, progress=None):
    """Copie les mods prevus : chaque fichier est telecharge et verifie (taille, SHA-256)
    avant d'etre ecrit dans Mods ; les fichiers remplaces vont d'abord dans
    sims4mp_backups/mods_AAAAMMJJ_HHMMSS/. progress(texte) recoit l'avancement
    (pourcentage des octets recus). Renvoie (lignes, statut_court)."""
    code = validate_room_code(code)
    is_running = is_running or core.game_is_running
    mods_dir, copies = Path(plan['mods_dir']), plan['copier']
    if not copies:
        return ['Mods identiques à ceux de l\'hôte : rien à copier.'], 'Mods déjà identiques'
    if is_running():
        raise RoomError('Fermez Les Sims 4 avant de copier les mods.')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = Path(backup_root) / 'mods_{}'.format(stamp)
    n = 2
    while backup.exists():
        backup = Path(backup_root) / 'mods_{}_{}'.format(stamp, n)
        n += 1
    done, saved = 0, 0
    lines = []
    count = {'octets': 0}
    total = sum(c['entree']['taille'] for c in copies)

    def report():
        if progress is not None:
            progress(progress_text(count['octets'], total, done, len(copies)))

    def on_data(n):
        count['octets'] += n
        report()

    report()
    try:
        for copy in copies:
            entry, target = copy['entree'], Path(copy['cible'])
            before = count['octets']
            received = _fetch_file(ip, port, code, session, '/modfile/{}'.format(copy['index']),
                                   entry['taille'], entry['sha256'], temp_dir, entry['chemin'],
                                   on_data=on_data)
            count['octets'] = before + entry['taille']
            try:
                if is_running():
                    raise RoomError('Les Sims 4 a été lancé pendant la copie : arrêt.')
                for old in copy['remplaces']:
                    old = Path(old)
                    if old.is_file():
                        dest = backup / old.relative_to(mods_dir)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(old), str(dest))
                        saved += 1
                if not target.resolve().is_relative_to(mods_dir.resolve()):
                    raise RoomError('Chemin de mod hors du dossier Mods : refus.')
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # Meme chemin qu'un fichier different (deja range ci-dessus si c'etait un mod).
                    dest = backup / target.relative_to(mods_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(dest))
                    saved += 1
                part = target.with_name('.' + target.name + '.part')
                shutil.copyfile(received, part)
                if part.stat().st_size != entry['taille']:
                    part.unlink()
                    raise RoomError('Copie incomplète dans Mods : {}.'.format(entry['chemin']))
                os.replace(part, target)
                done += 1
                report()
            finally:
                try:
                    received.unlink()
                except OSError:
                    pass
    except BaseException as exc:
        if isinstance(exc, core.LauncherError):
            raise RoomError('{}\n{} mod(s) copié(s) avant l\'arrêt ; fichiers remplacés rangés dans {}.'.format(
                str(exc), done, backup)) from None
        raise
    lines.append('{} mod(s) copié(s) depuis l\'hôte et vérifiés (taille et SHA-256).'.format(done))
    if saved:
        lines.append('{} fichier(s) remplacé(s), rangé(s) dans {}'.format(saved, backup))
    lines.append('Relancez Les Sims 4 pour charger les nouveaux mods.')
    return lines, 'Mods copiés ({})'.format(done)


def plan_join(info, documents, is_running=None):
    """Ce qui serait fait, sans rien ecrire (« Verifier sans copier »).
    Renvoie (lignes, plan) ; refuse si le jeu tourne ou si les mods different."""
    is_running = is_running or core.game_is_running
    mods_dir = core.find_mods_dir(documents)
    folder = saves_dir(documents)
    if is_running():
        raise RoomError('Fermez Les Sims 4 avant de rejoindre la room.')
    mod = mods_dir / core.MOD_FILE
    own = core.read_mod_version(mod) if mod.is_file() else None
    if own is None:
        raise RoomError('Mod Sims4MP absent : installez-le d\'abord (page Mod).')
    if own == 'inconnue' or info['version_mod'] == 'inconnue':
        raise RoomError('Version du mod illisible (chez vous ou chez l\'hôte) : comparaison impossible.')
    if own != info['version_mod']:
        raise RoomError('Versions du mod différentes : vous avez {}, l\'hôte a {}. Mettez-vous à la '
                        'même version avant de rejoindre.'.format(own, info['version_mod']))
    target = folder / RESERVED_SLOT
    existing = sorted(p.name for p in folder.iterdir() if p.is_file())
    versions = [n for n in (RESERVED_SLOT + s for s in VERSION_SUFFIXES) if (folder / n).is_file()]
    plan = {'saves': folder, 'target': target, 'existing': existing, 'versions': versions}
    lines = [
        'Partie de l\'hôte : {} ({})'.format(info['partie'] or 'nom non lu', info['fichier']),
        'Foyer(s) : {}'.format(', '.join(info['foyers']) or 'non lu'),
        'Taille : {:.1f} Mo, SHA-256 {}...'.format(info['taille'] / 1e6, info['sha256'][:16]),
        'Version du mod : {} (identique)'.format(own),
        'Copie datée de vos {} fichier(s) de sauvegarde dans sims4mp_backups\\saves_...'.format(len(existing)),
        'Installation dans le slot réservé Sims4MP : {}{}'.format(
            RESERVED_SLOT, ' (remplace la précédente partie Sims4MP)' if target.exists() else ''),
    ]
    if versions:
        lines.append('Déplacés dans la copie datée : {}'.format(', '.join(versions)))
    lines.append('Vos autres sauvegardes ne sont pas modifiées.')
    if is_auto_save(info['fichier']):
        lines.append('ATTENTION : c\'est la sauvegarde automatique de l\'hôte (Slot_ffffffff), pas une '
                     'partie sauvegardée à la main.')
    return lines, plan


def _download(ip, port, code, session, info, temp_dir, timeout_per_mb=2.0):
    return _fetch_file(ip, port, code, session, '/save', info['taille'], info['sha256'], temp_dir,
                       'la sauvegarde reçue', timeout_per_mb)


def _fetch_file(ip, port, code, session, url_path, size, sha256, temp_dir, what, timeout_per_mb=2.0,
                on_data=None):
    """Telecharge dans un fichier temporaire de temp_dir, verifie taille et SHA-256 ; renvoie son chemin.
    on_data(n) est appele apres chaque bloc recu (progression)."""
    info = {'taille': size, 'sha256': sha256}
    deadline = time.monotonic() + 30 + timeout_per_mb * info['taille'] / 1e6
    headers = _session_headers(session)
    fd, tmp = tempfile.mkstemp(prefix='sims4mp_room_', suffix='.part', dir=str(temp_dir))
    tmp = Path(tmp)
    try:
        try:
            conn, response = _request(ip, port, code, url_path, CONNECT_TIMEOUT, headers)
        except (OSError, http.client.HTTPException) as exc:
            raise RoomError('Room injoignable pendant le téléchargement : {}'.format(exc)) from None
        try:
            _check_status(response)
            total = 0
            with os.fdopen(fd, 'wb') as out:
                fd = None
                while True:
                    if time.monotonic() > deadline:
                        raise RoomError('Téléchargement trop long : abandon.')
                    try:
                        block = response.read1(256 * 1024)
                    except (OSError, http.client.HTTPException) as exc:
                        raise RoomError('Téléchargement interrompu : {}'.format(exc)) from None
                    if not block:
                        break
                    total += len(block)
                    if total > info['taille']:
                        raise RoomError('L\'hôte envoie plus de données que prévu : refus.')
                    out.write(block)
                    if on_data is not None:
                        on_data(len(block))
        finally:
            conn.close()
        if total != info['taille']:
            raise RoomError('Téléchargement incomplet : {} octets reçus, {} attendus.'.format(
                total, info['taille']))
        if core.sha256_of(tmp) != info['sha256']:
            raise RoomError('SHA-256 incorrect, fichier refusé : {}.'.format(what))
    except BaseException:
        if fd is not None:
            os.close(fd)
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return tmp


def apply_join(ip, port, code, session, info, documents, backup_root, temp_dir, is_running=None):
    """Telecharge et verifie, puis copie datee des sauvegardes, deplacement des .ver
    du slot reserve, installation atomique. Rien n'est ecrit dans saves avant que
    le fichier recu soit verifie. Renvoie (lignes, statut_court)."""
    code = validate_room_code(code)
    is_running = is_running or core.game_is_running
    lines, plan = plan_join(info, documents, is_running)
    received = _download(ip, port, code, session, info, temp_dir)
    try:
        lines = ['Sauvegarde reçue et vérifiée (taille et SHA-256).']
        if is_running():
            raise RoomError('Les Sims 4 a été lancé pendant le téléchargement : rien n\'a été installé.')
        folder = plan['saves']
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = Path(backup_root) / 'saves_{}'.format(stamp)
        n = 2
        while backup.exists():
            backup = Path(backup_root) / 'saves_{}_{}'.format(stamp, n)
            n += 1
        backup.mkdir(parents=True)
        for name in plan['existing']:
            src = folder / name
            shutil.copy2(src, backup / name)                      # lecture seule de l'original
            if (backup / name).stat().st_size != src.stat().st_size:
                raise RoomError('Copie de sécurité incomplète : {}. Rien n\'a été installé.'.format(name))
        lines.append('Copie datée de {} fichier(s) : {}'.format(len(plan['existing']), backup))
        if plan['versions']:
            # La copie datee en contient deja un double : les originaux vont a part.
            moved = backup / 'ver_deplaces'
            moved.mkdir()
            for name in plan['versions']:
                os.replace(folder / name, moved / name)
        if plan['versions']:
            lines.append('Déplacés dans la copie datée : {}'.format(', '.join(plan['versions'])))
        part = folder / ('.' + RESERVED_SLOT + '.part')
        try:
            shutil.copyfile(received, part)
            if core.sha256_of(part) != info['sha256']:
                raise RoomError('Copie incorrecte dans le dossier saves : rien n\'a été remplacé.')
            os.replace(part, plan['target'])
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
    finally:
        try:
            received.unlink()
        except OSError:
            pass
    lines.append('Partie installée dans {} : {}'.format(RESERVED_SLOT, info['partie'] or info['fichier']))
    lines.append('En jeu, chargez cette partie (slot Sims4MP) puis tapez mp.join.')
    return lines, 'Sauvegarde de l\'hôte installée'
