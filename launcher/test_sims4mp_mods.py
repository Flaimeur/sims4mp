# Tests de la comparaison des mods (etape 8a). Dossiers Mods temporaires imitant
# « Les Sims 4 », room reelle sur 127.0.0.1. Rien n'est jamais copie dans Mods.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_mods.py -v

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as core  # noqa: E402
import sims4mp_mods as mods  # noqa: E402
import sims4mp_room as room  # noqa: E402
from test_sims4mp_room import NBSP_GAME, SESSION, accept_guest, make_save, mod_bytes  # noqa: E402

CODE = 'ABCD2345'


def put(folder, rel, content):
    path = Path(folder) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def tree_snapshot(folder):
    """Etat recursif : chemin -> (contenu, date)."""
    return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in Path(folder).rglob('*') if p.is_file()}


def fill_host(mods_dir):
    put(mods_dir, 'CC/Cheveux/hair.package', b'h' * 100)
    put(mods_dir, 'CC/shoes.package', b's' * 200)
    put(mods_dir, 'script.ts4script', b'host script')
    put(mods_dir, 'A/dup.package', b'd' * 10)
    put(mods_dir, 'B/dup.package', b'd' * 20)
    put(mods_dir, 'only_host.package', b'o' * 50)
    put(mods_dir, core.MOD_FILE, mod_bytes('0.4.0'))           # exclu : compare par la room
    put(mods_dir, 'Resource.cfg', b'Priority 500')
    put(mods_dir, 'notes.log', b'x')
    put(mods_dir, 'thumbs.ini', b'x')


def fill_guest(mods_dir):
    put(mods_dir, 'hair.package', b'h' * 100)                   # autre dossier, meme fichier
    put(mods_dir, 'CC/shoes.package', b's' * 201)               # taille differente
    put(mods_dir, 'script.ts4script', b'GUEST scrip')           # meme taille, contenu different
    put(mods_dir, 'dup.package', b'd' * 20)                     # un seul des deux doublons
    put(mods_dir, 'extra.package', b'e' * 30)
    put(mods_dir, core.MOD_FILE, mod_bytes('0.4.0'))


class ScanCompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_mods_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.host = self.tmp / 'host'
        self.guest = self.tmp / 'guest'
        fill_host(self.host)
        fill_guest(self.guest)

    def test_scan(self):
        entries = mods.scan_mods(self.host)
        self.assertEqual([e['chemin'] for e in entries],
                         ['A/dup.package', 'B/dup.package', 'CC/Cheveux/hair.package', 'CC/shoes.package',
                          'only_host.package', 'script.ts4script'])
        self.assertTrue(all(e['sha256'] is None for e in entries))
        self.assertEqual(entries[2], {'nom': 'hair.package', 'chemin': 'CC/Cheveux/hair.package',
                                      'taille': 100, 'sha256': None})

    def test_sha_and_cache(self):
        cache = self.tmp / mods.CACHE_NAME
        real = core.sha256_of
        calls = []

        def counting(path):
            calls.append(Path(path).name)
            return real(path)
        with mock.patch.object(core, 'sha256_of', counting):
            first = mods.scan_mods(self.host, with_sha=True, cache_path=cache)
            self.assertEqual(len(calls), 6)
            calls.clear()
            second = mods.scan_mods(self.host, with_sha=True, cache_path=cache)
            self.assertEqual(calls, [])                          # tout vient du cache
            put(self.host, 'CC/shoes.package', b's' * 201)       # un fichier change
            mods.scan_mods(self.host, with_sha=True, cache_path=cache)
            self.assertEqual(calls, ['shoes.package'])
            calls.clear()
            cache.write_text('{pas du json', encoding='utf-8')   # cache abime : ignore
            mods.scan_mods(self.host, with_sha=True, cache_path=cache)
            self.assertEqual(len(calls), 6)
        self.assertEqual(first, second)
        self.assertTrue(all(len(e['sha256']) == 64 for e in first))

    def test_compare_name_and_size(self):
        result = mods.compare_mods(mods.scan_mods(self.host), mods.scan_mods(self.guest))
        self.assertEqual([e['nom'] for e in result['manquants']], ['only_host.package'])
        self.assertEqual(sorted(e['chemin'] for e, yours in result['differents']),
                         ['A/dup.package', 'CC/shoes.package'])
        self.assertEqual([e['nom'] for e in result['en_plus']], ['extra.package'])
        self.assertEqual(result['identiques'], 3)                # hair, dup (20), script (meme taille)
        self.assertFalse(result['exacte'])
        self.assertEqual(mods.summary_text(result), 'Mods : 1 manquant(s), 2 différent(s), 1 en plus')

    def test_compare_exact(self):
        host = mods.scan_mods(self.host, with_sha=True)
        guest = mods.scan_mods(self.guest, with_sha=True)
        result = mods.compare_mods(host, guest, use_sha=True)
        self.assertTrue(result['exacte'])
        self.assertIn('script.ts4script', [e['nom'] for e, yours in result['differents']])
        self.assertEqual(result['identiques'], 2)

    def test_case_insensitive_names(self):
        put(self.guest, 'ONLY_HOST.PACKAGE', b'o' * 50)
        result = mods.compare_mods(mods.scan_mods(self.host), mods.scan_mods(self.guest))
        self.assertEqual(result['manquants'], [])

    def test_validate_hostile_lists(self):
        good = mods.mods_list(self.host)
        self.assertEqual(mods.validate_mods_list(json.loads(json.dumps(good))), good)
        entry = {'nom': 'a.package', 'chemin': 'CC/a.package', 'taille': 1, 'sha256': None}
        bad_entries = [
            dict(entry, chemin='../a.package'), dict(entry, chemin='/a.package'),
            dict(entry, chemin='C:/x/a.package'), dict(entry, chemin='CC\\a.package'),
            dict(entry, chemin='CC/b.package'), dict(entry, nom='a.exe', chemin='a.exe'),
            dict(entry, nom='../a.package'), dict(entry, nom=''), dict(entry, taille=True),
            dict(entry, taille=-1), dict(entry, taille='1'), dict(entry, sha256='Z' * 64),
            dict(entry, extra=1), 'a.package',
        ]
        for bad in bad_entries:
            with self.assertRaises(mods.ModsError, msg=repr(bad)):
                mods.validate_mods_list({'protocole': 1, 'avec_sha': False, 'mods': [bad]})
        for bad_list in [[], {'protocole': 1, 'avec_sha': False}, {'protocole': 2, 'avec_sha': False, 'mods': []},
                         {'protocole': 1, 'avec_sha': 'oui', 'mods': []},
                         {'protocole': 1, 'avec_sha': True, 'mods': [entry]},
                         {'protocole': 1, 'avec_sha': False, 'mods': [entry] * (mods.MAX_ENTRIES + 1)}]:
            with self.assertRaises(mods.ModsError, msg=str(bad_list)[:60]):
                mods.validate_mods_list(bad_list)

    def test_report_file(self):
        result = mods.compare_mods(mods.scan_mods(self.host), mods.scan_mods(self.guest))
        lines = mods.report_lines(result, '192.168.1.20:7778')
        path = mods.write_report(self.tmp, lines)
        self.assertEqual(path.parent, self.tmp)
        self.assertTrue(path.name.startswith('sims4mp_mods_') and path.name.endswith('.txt'))
        text = path.read_text(encoding='utf-8-sig')
        self.assertIn('Manquants chez vous : 1', text)
        self.assertIn('only_host.package (only_host.package, 0.0 Mo)', text)
        self.assertIn('Rien n\'a été copié ni modifié.', text)
        self.assertNotEqual(mods.write_report(self.tmp, lines), path)            # pas d'ecrasement


class RoomModsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_room_mods_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(core, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        game = self.tmp / 'hote' / 'Electronic Arts' / NBSP_GAME
        self.host_mods = game / 'Mods'
        fill_host(self.host_mods)
        (game / 'saves').mkdir()
        self.host_save = make_save(game / 'saves' / 'Slot_00000002.save')
        self.saves = game / 'saves'
        self.guest_docs = self.tmp / 'invite' / 'Documents'
        self.guest_mods = self.guest_docs / 'Electronic Arts' / NBSP_GAME / 'Mods'
        fill_guest(self.guest_mods)
        put(self.guest_mods, 'Resource.cfg', b'Priority 500')
        self.reports = self.tmp / 'lanceur_invite'
        self.reports.mkdir()

    def open_room(self, **kwargs):
        server = room.RoomServer(self.host_save, self.saves, self.tmp / 'snap', '0.4.0', '127.0.0.1', 0,
                                 code=CODE, **kwargs)
        server.prepare(is_running=lambda: False)
        port = server.start()
        self.addCleanup(server.stop)
        accept_guest(server, port)                      # /mods exige l'accord de l'hote
        return server, port

    def test_compare_through_room(self):
        before = tree_snapshot(self.guest_mods)
        server, port = self.open_room(mods_dir=self.host_mods)
        lines, summary = room.run_mod_compare('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.reports)
        self.assertEqual(summary, 'Mods : 1 manquant(s), 2 différent(s), 1 en plus')
        self.assertEqual(tree_snapshot(self.guest_mods), before)                  # rien de modifie
        [report] = [p for p in self.reports.iterdir() if p.suffix == '.txt']
        self.assertIn(str(report), lines[-1])
        self.assertIn('a comparé ses mods (6 mods de l\'hôte)', ' '.join(server.take_events()))

    def test_exact_mode_through_room(self):
        server, port = self.open_room(mods_dir=self.host_mods, mods_sha=True,
                                      mods_cache=self.tmp / mods.CACHE_NAME)
        lines, summary = room.run_mod_compare('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.reports)
        self.assertIn('exacte, SHA-256', lines[0])
        self.assertIn('script.ts4script', '\n'.join(lines))
        self.assertTrue((self.reports / mods.CACHE_NAME).is_file())            # cache de l'invite

    def test_host_without_mods_list(self):
        server, port = self.open_room()
        with self.assertRaisesRegex(mods.ModsError, 'ne propose pas la comparaison'):
            room.run_mod_compare('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.reports)
        self.assertEqual([p for p in self.reports.iterdir()], [])

    def test_wrong_code(self):
        server, port = self.open_room(mods_dir=self.host_mods)
        with self.assertRaisesRegex(room.RoomError, 'Code de room refusé'):
            room.run_mod_compare('127.0.0.1', port, 'ZZZZ2345', SESSION, self.guest_docs, self.reports)

    def test_hostile_host_list_rejected(self):
        server, port = self.open_room(mods_dir=self.host_mods)
        server.mods['mods'].append({'nom': 'evil.package', 'chemin': '../../evil.package',
                                    'taille': 1, 'sha256': None})
        before = tree_snapshot(self.guest_mods)
        with self.assertRaisesRegex(mods.ModsError, 'Chemin de mod refusé'):
            room.run_mod_compare('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.reports)
        self.assertEqual(tree_snapshot(self.guest_mods), before)
        self.assertEqual([p for p in self.reports.iterdir()], [])


if __name__ == '__main__':
    unittest.main()
