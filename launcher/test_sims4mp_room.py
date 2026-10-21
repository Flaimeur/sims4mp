# Tests de la room (etape 7b) : lecture des sauvegardes, serveur de l'hote sur
# 127.0.0.1, client de l'invite. Uniquement des dossiers temporaires imitant
# « Les Sims 4 » (espaces insecables) et de fausses sauvegardes construites ici.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_room.py -v

import http.client
import io
import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as core  # noqa: E402
import sims4mp_room as room  # noqa: E402

NBSP_GAME = 'Les\u00a0Sims\u00a04'
CODE = 'ABCD2345'
SESSION = 'a1b2c3d4e5f60718'


def accept_guest(server, port, session=SESSION, code=CODE, pseudo='Alex'):
    """L'invite se signale, puis l'hote l'accepte (prealable a /info, /save, /mods)."""
    room.send_presence('127.0.0.1', port, code, session, pseudo, 'connecte', False)
    server.accept_guest(session)


# --- Fabrication de fausses sauvegardes -------------------------------------------

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, value):
    if isinstance(value, int):
        return _varint(num << 3) + _varint(value)
    return _varint(num << 3 | 2) + _varint(len(value)) + value


def save_blob(partie, foyers, others=('Voisins',)):
    blob = _field(1, 7) + _field(2, _field(1, 2) + _field(9, partie.encode('utf-8')))
    for name in foyers:
        blob += _field(5, _field(3, name.encode('utf-8')) + _field(31, 1))
    for name in others:                                    # foyers non joueurs : ignores
        blob += _field(5, _field(3, name.encode('utf-8')))
    return blob


def refpack_literal(data):
    """Encodage RefPack fait uniquement de litteraux (pour les tests)."""
    out = bytearray([0x10, 0xFB]) + len(data).to_bytes(3, 'big')
    pos = 0
    while len(data) - pos >= 4:
        n = min(112, (len(data) - pos) // 4 * 4)
        out.append(0xE0 | ((n - 4) >> 2))
        out += data[pos:pos + n]
        pos += n
    out.append(0xFC | (len(data) - pos))
    out += data[pos:]
    return bytes(out)


def make_save(path, partie='Ma partie', foyers=('Dupont',), compress=True, padding=0):
    blob = save_blob(partie, foyers)
    payload = refpack_literal(blob) if compress else blob
    comp = 0xFFFF if compress else 0
    data_offset = 96
    index_pos = data_offset + len(payload) + padding
    header = bytearray(96)
    header[0:4] = b'DBPF'
    struct.pack_into('<II', header, 4, 2, 1)
    struct.pack_into('<I', header, 0x24, 1)
    struct.pack_into('<Q', header, 0x40, index_pos)
    index = struct.pack('<I', 0) + struct.pack('<IIIIIIIHH', 0x0D, 0, 0, 1, data_offset,
                                               len(payload) | 0x80000000, len(blob), comp, 1)
    Path(path).write_bytes(bytes(header) + payload + b'\x00' * padding + index)
    return Path(path)


def mod_bytes(version):
    payload = b'\x00' * 16 + b'\xda' + bytes([len(version)]) + version.encode() + b'\x00' * 64
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('sims4mp_hello.pyc', payload)
    return buffer.getvalue()


def snapshot(folder):
    """Etat d'un dossier : nom -> (contenu, date)."""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(folder).iterdir() if p.is_file()}


# --- Lecture des sauvegardes ------------------------------------------------------

class SaveFormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_room_fmt_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_refpack(self):
        self.assertEqual(room.refpack_decompress(b'\x10\xfb\x00\x00\x09\x0f\x02abc\xfc'), b'abcabcabc')
        self.assertEqual(room.refpack_decompress(refpack_literal(b'x' * 300 + b'yz')), b'x' * 300 + b'yz')
        for bad in [b'\x10\xfa\x00\x00\x01a', b'\x10\xfb\x00\x00\x09\x0f\x09abc\xfc',
                    b'\x10\xfb\x00\x00\x02\xe0abcd\xfc', b'\x10\xfb\xff\xff\xff']:
            with self.assertRaises(ValueError, msg=bad):
                room.refpack_decompress(bad)

    def test_read_save_info(self):
        for compress in (True, False):
            path = make_save(self.tmp / 'Slot_00000002.save', 'Ma partie sauvegardée 1',
                             ['Петрова', 'Dupont'], compress=compress)
            self.assertEqual(room.read_save_info(path),
                             {'partie': 'Ma partie sauvegardée 1', 'foyers': ['Петрова', 'Dupont']})

    def test_unreadable_save_never_raises(self):
        junk = self.tmp / 'Slot_00000003.save'
        for content in [b'', b'pas un dbpf', b'DBPF' + b'\x00' * 200, b'DBPF' + b'\xff' * 200]:
            junk.write_bytes(content)
            self.assertEqual(room.read_save_info(junk), {'partie': None, 'foyers': []})
        self.assertEqual(room.read_save_info(self.tmp / 'absent.save'), {'partie': None, 'foyers': []})

    def test_list_saves(self):
        older = make_save(self.tmp / 'Slot_00000001.save')
        newer = make_save(self.tmp / 'Slot_ffffffff.save')
        os.utime(older, (1_000_000, 1_000_000))
        for other in ['Slot_1.save', 'Slot_00000001.save.ver0', 'notes.txt', 'Slot_zzzzzzzz.save']:
            (self.tmp / other).write_bytes(b'x')
        (self.tmp / 'Slot_00000004.save').mkdir()
        manual_recent = make_save(self.tmp / 'Slot_00000003.save')
        os.utime(manual_recent, (2_000_000, 2_000_000))
        # Parties manuelles d'abord (la plus recente en tete), la sauvegarde automatique toujours en dernier,
        # meme si c'est le fichier le plus recent.
        self.assertEqual([p.name for p in room.list_saves(self.tmp)],
                         [manual_recent.name, older.name, newer.name])
        self.assertTrue(room.is_auto_save(newer))
        self.assertFalse(room.is_auto_save(older))
        self.assertIn('sauvegarde automatique', room.save_label(newer))


# --- Validations ----------------------------------------------------------------------

class ValidationTest(unittest.TestCase):
    INFO = {'protocole': 2, 'version_mod': '0.4.0', 'fichier': 'Slot_00000002.save', 'taille': 100,
            'sha256': 'a' * 64, 'partie': 'Ma partie', 'foyers': ['Dupont']}

    def test_clients(self):
        for ok in ['192.168.1.20', '10.0.0.5', '172.16.3.4', '127.0.0.1']:
            self.assertTrue(room.is_allowed_client(ok), ok)
        for bad in ['8.8.8.8', '0.0.0.0', '224.0.0.1', 'pas une ip', '']:
            self.assertFalse(room.is_allowed_client(bad), bad)

    def test_room_code(self):
        self.assertEqual(room.validate_room_code(' abcd2345 '), 'ABCD2345')
        self.assertEqual(len(room.new_room_code()), 8)
        for bad in ['', 'ABC', 'ABCD234O', 'ABCD-345', 'ABCD23451']:
            with self.assertRaises(room.RoomError, msg=bad):
                room.validate_room_code(bad)

    def test_room_info(self):
        self.assertEqual(room.validate_room_info(dict(self.INFO)), self.INFO)
        bad_names = ['..\\Slot_00000002.save', '../Slot_00000002.save', 'C:\\x\\Slot_00000002.save',
                     '/etc/Slot_00000002.save', 'Slot_1.save', 'Slot_zzzzzzzz.save', 'Slot_00000002.save ', 7]
        for name in bad_names:
            with self.assertRaisesRegex(room.RoomError, 'Nom de sauvegarde refusé', msg=repr(name)):
                room.validate_room_info(dict(self.INFO, fichier=name))
        for change in [{'taille': room.MAX_SAVE_SIZE + 1}, {'taille': 0}, {'taille': True},
                       {'sha256': 'A' * 64}, {'protocole': 1}, {'version_mod': '1'},   # 1 : ancien lanceur
                       {'foyers': 'Dupont'}, {'partie': 'x' * 300}]:
            with self.assertRaises(room.RoomError, msg=change):
                room.validate_room_info(dict(self.INFO, **change))
        with self.assertRaises(room.RoomError):
            room.validate_room_info(dict(self.INFO, chemin='C:\\'))


# --- Hote et invite de bout en bout -------------------------------------------------

class RoomFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_room_flow_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(core, 'base_dir', return_value=self.tmp)      # launcher.log
        patcher.start()
        self.addCleanup(patcher.stop)
        # Hote
        self.host_docs = self.tmp / 'hote' / 'Documents'
        host_game = self.host_docs / 'Electronic Arts' / NBSP_GAME
        (host_game / 'Mods').mkdir(parents=True)
        (host_game / 'Mods' / 'Resource.cfg').write_text('')
        self.host_saves = host_game / 'saves'
        self.host_saves.mkdir()
        self.host_save = make_save(self.host_saves / 'Slot_00000002.save', 'Partie commune', ['Петрова'],
                                   padding=50_000)
        # Invite
        self.guest_docs = self.tmp / 'invite' / 'Documents'
        guest_game = self.guest_docs / 'Electronic Arts' / NBSP_GAME
        (guest_game / 'Mods').mkdir(parents=True)
        (guest_game / 'Mods' / 'Resource.cfg').write_text('')
        (guest_game / 'Mods' / core.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.guest_saves = guest_game / 'saves'
        self.guest_saves.mkdir()
        make_save(self.guest_saves / 'Slot_00000001.save', 'Partie de l\'invité', ['Martin'])
        make_save(self.guest_saves / 'Slot_00000002.save', 'Autre partie invité', ['Bernard'])
        (self.guest_saves / 'Slot_00000001.save.ver0').write_bytes(b'ancienne version invite')
        os.utime(self.guest_saves / 'Slot_00000001.save', (1_500_000_000, 1_500_000_000))
        self.backups = self.tmp / 'invite' / 'sims4mp_backups'
        self.downloads = self.tmp / 'invite' / 'launcher'
        self.downloads.mkdir()
        self.server = None

    def open_room(self, code=CODE, accept=True):
        self.server = room.RoomServer(self.host_save, self.host_saves, self.tmp / 'hote' / 'launcher',
                                      '0.4.0', '127.0.0.1', 0, code=code)
        self.server.prepare(is_running=lambda: False)
        port = self.server.start()
        self.addCleanup(self.server.stop)
        if accept:
            accept_guest(self.server, port, code=code)
        return port

    def join(self, port, code=CODE, running=lambda: False):
        info = room.fetch_room_info('127.0.0.1', port, code, SESSION)
        return info, room.apply_join('127.0.0.1', port, code, SESSION, info, self.guest_docs, self.backups,
                                     self.downloads, is_running=running)

    def assert_guest_untouched(self, before):
        self.assertEqual(snapshot(self.guest_saves), before)
        self.assertFalse(self.backups.exists())
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_full_flow(self):
        before = snapshot(self.guest_saves)
        port = self.open_room()
        info, (lines, summary) = self.join(port)
        self.assertEqual((info['partie'], info['foyers']), ('Partie commune', ['Петрова']))
        self.assertEqual(summary, 'Sauvegarde de l\'hôte installée')
        target = self.guest_saves / room.RESERVED_SLOT
        self.assertEqual(target.read_bytes(), self.host_save.read_bytes())
        # Parties de l'invite : contenu et dates inchanges (meme Slot_00000002 que l'hote).
        after = snapshot(self.guest_saves)
        for name, value in before.items():
            self.assertEqual(after[name], value, name)
        # Copie datee de toutes les sauvegardes existantes.
        [backup] = list(self.backups.iterdir())
        self.assertTrue(backup.name.startswith('saves_'))
        self.assertEqual(sorted(p.name for p in backup.iterdir() if p.is_file()), sorted(before))
        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assertFalse(any(p.name.endswith('.part') for p in self.guest_saves.iterdir()))
        self.assertIn('Sauvegarde envoyée à 127.0.0.1', self.server.take_events())

    def test_second_join_replaces_previous_and_moves_ver(self):
        port = self.open_room()
        old = make_save(self.guest_saves / room.RESERVED_SLOT, 'Ancienne partie commune', ['Vieux'])
        old_bytes = old.read_bytes()
        (self.guest_saves / (room.RESERVED_SLOT + '.ver0')).write_bytes(b'ver0 de l\'ancienne')
        (self.guest_saves / (room.RESERVED_SLOT + '.ver3')).write_bytes(b'ver3 de l\'ancienne')
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        lines, plan = room.plan_join(info, self.guest_docs, is_running=lambda: False)
        self.assertIn('Déplacés dans la copie datée : Slot_534d5000.save.ver0, Slot_534d5000.save.ver3', lines)
        room.apply_join('127.0.0.1', port, CODE, SESSION, info, self.guest_docs, self.backups, self.downloads,
                        is_running=lambda: False)
        [backup] = list(self.backups.iterdir())
        self.assertEqual((backup / room.RESERVED_SLOT).read_bytes(), old_bytes)
        self.assertEqual(sorted(p.name for p in (backup / 'ver_deplaces').iterdir()),
                         [room.RESERVED_SLOT + '.ver0', room.RESERVED_SLOT + '.ver3'])
        self.assertFalse((self.guest_saves / (room.RESERVED_SLOT + '.ver0')).exists())
        self.assertTrue((self.guest_saves / 'Slot_00000001.save.ver0').exists())     # autres .ver gardes
        self.assertEqual((self.guest_saves / room.RESERVED_SLOT).read_bytes(), self.host_save.read_bytes())

    def test_simulation_writes_nothing(self):
        before = snapshot(self.guest_saves)
        port = self.open_room()
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        lines, plan = room.plan_join(info, self.guest_docs, is_running=lambda: False)
        self.assertIn('Vos autres sauvegardes ne sont pas modifiées.', lines)
        self.assert_guest_untouched(before)
        self.assertNotIn('Sauvegarde envoyée à 127.0.0.1', self.server.take_events())

    def test_wrong_code_and_lock(self):
        port = self.open_room()
        with self.assertRaisesRegex(room.RoomError, 'Code de room refusé'):
            room.fetch_room_info('127.0.0.1', port, 'ZZZZ2345', SESSION)
        for _ in range(room.MAX_BAD_CODES - 1):
            with self.assertRaises(room.RoomError):
                room.fetch_room_info('127.0.0.1', port, 'ZZZZ2345', SESSION)
        with self.assertRaisesRegex(room.RoomError, 'verrouillée'):
            room.fetch_room_info('127.0.0.1', port, CODE, SESSION)                    # meme le bon code

    def test_no_code_and_unknown_path(self):
        port = self.open_room()
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('GET', '/save')
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()
        for path in ['/../saves/Slot_00000002.save', '/saves', '/info/../save', '/']:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            conn.request('GET', path, headers={room.CODE_HEADER: CODE})
            response = conn.getresponse()
            self.assertEqual(response.status, 404, path)
            self.assertEqual(response.read(), b'')
            conn.close()

    def test_wrong_sha_rejected(self):
        before = snapshot(self.guest_saves)
        port = self.open_room()
        data = bytearray(self.server.snapshot.read_bytes())
        data[-1] ^= 0xFF                                                     # meme taille, contenu altere
        self.server.snapshot.write_bytes(bytes(data))
        with self.assertRaisesRegex(room.RoomError, 'SHA-256 incorrect'):
            self.join(port)
        self.assert_guest_untouched(before)

    def test_truncated_transfer_rejected(self):
        before = snapshot(self.guest_saves)
        port = self.open_room()
        self.server.info['taille'] += 1000                                   # annonce plus que le fichier
        with self.assertRaises(room.RoomError):
            self.join(port)
        self.assert_guest_untouched(before)

    def test_game_running(self):
        before = snapshot(self.guest_saves)
        port = self.open_room()
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        with self.assertRaisesRegex(room.RoomError, 'Fermez Les Sims 4'):
            room.plan_join(info, self.guest_docs, is_running=lambda: True)
        calls = []

        def started_during_download():
            calls.append(1)
            return len(calls) > 1
        with self.assertRaisesRegex(room.RoomError, 'lancé pendant le téléchargement'):
            room.apply_join('127.0.0.1', port, CODE, SESSION, info, self.guest_docs, self.backups,
                            self.downloads, is_running=started_during_download)
        self.assert_guest_untouched(before)

    def test_mod_version_mismatch(self):
        (self.guest_docs / 'Electronic Arts' / NBSP_GAME / 'Mods' / core.MOD_FILE).write_bytes(mod_bytes('0.3.0'))
        port = self.open_room()
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        with self.assertRaisesRegex(room.RoomError, 'Versions du mod différentes : vous avez 0.3.0, l\'hôte a 0.4.0'):
            room.plan_join(info, self.guest_docs, is_running=lambda: False)

    def test_unreachable_room(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]                                        # port ferme ensuite
        with self.assertRaisesRegex(room.RoomError, 'Room injoignable'):
            room.fetch_room_info('127.0.0.1', port, CODE, SESSION, timeout=2)

    def test_host_prepare_checks(self):
        server = room.RoomServer(self.host_save, self.host_saves, self.tmp / 'snap', '0.4.0', '127.0.0.1', 0)
        with self.assertRaisesRegex(room.RoomError, 'Fermez Les Sims 4'):
            server.prepare(is_running=lambda: True)
        outside = make_save(self.tmp / 'Slot_00000009.save')
        renamed = self.host_saves / 'ma_partie.save'
        renamed.write_bytes(self.host_save.read_bytes())
        for bad in [outside, renamed, self.host_saves / 'Slot_0000000a.save']:
            with self.assertRaisesRegex(room.RoomError, 'Sauvegarde invalide', msg=str(bad)):
                room.RoomServer(bad, self.host_saves, self.tmp / 'snap', '0.4.0', '127.0.0.1', 0).prepare(
                    is_running=lambda: False)

    def test_snapshot_is_frozen(self):
        port = self.open_room()
        expected = self.server.info['sha256']
        make_save(self.host_save, 'Partie modifiée apres creation', ['Autre'])   # le jeu resauvegarde
        info, _ = self.join(port)
        self.assertEqual(info['sha256'], expected)
        self.assertEqual(core.sha256_of(self.guest_saves / room.RESERVED_SLOT), expected)
        self.server.stop()
        self.assertFalse(any((self.tmp / 'hote' / 'launcher').iterdir()))    # copie figee supprimee

    def test_host_original_never_written(self):
        original = (self.host_save.read_bytes(), self.host_save.stat().st_mtime_ns)
        port = self.open_room()
        self.join(port)
        self.server.stop()
        self.assertEqual((self.host_save.read_bytes(), self.host_save.stat().st_mtime_ns), original)


if __name__ == '__main__':
    unittest.main()
