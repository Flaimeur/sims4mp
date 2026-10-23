# Tests de la copie des mods de l'hote vers l'invite. Dossiers Mods temporaires
# imitant « Les Sims 4 », room reelle sur 127.0.0.1. Aucun vrai dossier Mods.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_modsync.py -v

import hashlib
import http.client
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
from test_sims4mp_mods import CODE, fill_guest, fill_host, put, tree_snapshot  # noqa: E402
from test_sims4mp_room import NBSP_GAME, SESSION, accept_guest, make_save  # noqa: E402


class ModSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_modsync_'))
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
        self.launcher = self.tmp / 'lanceur_invite'
        self.launcher.mkdir()
        self.backups = self.launcher / 'sims4mp_backups'

    def open_room(self, accept=True):
        server = room.RoomServer(self.host_save, self.saves, self.tmp / 'snap', '0.4.0', '127.0.0.1', 0,
                                 code=CODE, mods_dir=self.host_mods, mods_sha=True,
                                 mods_cache=self.tmp / 'cache_hote.json')
        server.prepare(is_running=lambda: False)
        port = server.start()
        self.addCleanup(server.stop)
        if accept:
            accept_guest(server, port)
        return server, port

    def plan(self, port):
        return room.plan_mods_sync('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.launcher,
                                   is_running=lambda: False)

    def apply(self, port, plan, is_running=lambda: False):
        return room.apply_mods_sync('127.0.0.1', port, CODE, SESSION, plan, self.backups, self.launcher,
                                    is_running=is_running)

    def by_name(self, folder):
        found = {}
        for path in Path(folder).rglob('*'):
            if path.is_file():
                found.setdefault(path.name, []).append(path.relative_to(folder).as_posix())
        return found

    def test_host_mod_updated_while_room_open(self):
        from test_sims4mp_update import mod_bytes
        put(self.host_mods, core.MOD_FILE, mod_bytes('0.4.0'))
        server, port = self.open_room()
        now = [1000.0]
        server._clock = lambda: now[0]
        server._refreshed_at = now[0]
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        self.assertEqual(info['version_mod'], '0.4.0')
        # L'hote installe une nouvelle version et un nouveau mod sans fermer la room.
        put(self.host_mods, core.MOD_FILE, mod_bytes('0.5.0'))
        put(self.host_mods, 'nouveau.package', b'nouveau mod')
        now[0] += 1.0                                   # moins de 5 s : pas encore relu
        self.assertEqual(room.fetch_room_info('127.0.0.1', port, CODE, SESSION)['version_mod'], '0.4.0')
        now[0] += room.HOST_REFRESH_GAP
        info = room.fetch_room_info('127.0.0.1', port, CODE, SESSION)
        self.assertEqual(info['version_mod'], '0.5.0')
        self.assertTrue(any('Mod de l\'hôte mis à jour : version 0.5.0 (avant : 0.4.0)' in e
                            for e in server.take_events()))
        now[0] += room.HOST_REFRESH_GAP
        listed = room.fetch_mods_list('127.0.0.1', port, CODE, SESSION)
        self.assertIn('nouveau.package', [m['chemin'] for m in listed['mods']])
        # L'invite compare avec la version actuelle de l'hote, pas celle de la creation de la room.
        (self.guest_mods.parent / 'saves').mkdir(exist_ok=True)
        (self.guest_mods / core.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        with self.assertRaisesRegex(room.RoomError, '0.5.0'):
            room.plan_join(info, self.guest_docs, is_running=lambda: False)

    def test_plan_writes_nothing(self):
        server, port = self.open_room()
        before = tree_snapshot(self.guest_mods)
        lines, plan = self.plan(port)
        self.assertEqual(sorted(c['entree']['chemin'] for c in plan['copier']),
                         ['A/dup.package', 'CC/shoes.package', 'only_host.package', 'script.ts4script'])
        # dup.package de l'invite est identique a B/dup.package de l'hote : il n'est pas remplace.
        [dup] = [c for c in plan['copier'] if c['entree']['chemin'] == 'A/dup.package']
        self.assertEqual(dup['remplaces'], [])
        self.assertEqual(plan['scripts'], 1)
        text = '\n'.join(lines)
        self.assertIn('À copier depuis l\'hôte : 4 fichier(s)', text)
        self.assertIn('dont 1 script(s) .ts4script', text)
        self.assertIn('Vos 1 mod(s) en plus ne sont pas touchés', text)
        self.assertEqual(tree_snapshot(self.guest_mods), before)

    def test_copy_then_identical(self):
        server, port = self.open_room()
        lines, plan = self.plan(port)
        lines, summary = self.apply(port, plan)
        self.assertEqual(summary, 'Mods copiés (4)')
        self.assertEqual((self.guest_mods / 'dup.package').read_bytes(), b'd' * 20)     # garde
        for rel in ('A/dup.package', 'CC/shoes.package', 'only_host.package', 'script.ts4script'):
            self.assertEqual((self.guest_mods / rel).read_bytes(), (self.host_mods / rel).read_bytes(), rel)
        # Anciennes versions rangees dans la copie datee, avec leur chemin.
        [backup] = self.backups.iterdir()
        self.assertTrue(backup.name.startswith('mods_'))
        self.assertEqual((backup / 'CC' / 'shoes.package').read_bytes(), b's' * 201)
        self.assertEqual((backup / 'script.ts4script').read_bytes(), b'GUEST scrip')
        # Fichiers en plus et Resource.cfg intacts, aucun reste temporaire.
        self.assertEqual((self.guest_mods / 'extra.package').read_bytes(), b'e' * 30)
        self.assertTrue((self.guest_mods / 'Resource.cfg').is_file())
        self.assertEqual([p for p in self.guest_mods.rglob('*.part')], [])
        self.assertEqual([p for p in self.launcher.glob('*.part')], [])
        lines, plan = self.plan(port)
        self.assertEqual(plan['copier'], [])
        self.assertEqual(self.apply(port, plan)[1], 'Mods déjà identiques')

    def test_progress_percentages(self):
        put(self.host_mods, 'gros.package', b'G' * (700 * 1024))           # plusieurs blocs de 256 Ko
        server, port = self.open_room()
        lines, plan = self.plan(port)
        seen = []
        room.apply_mods_sync('127.0.0.1', port, CODE, SESSION, plan, self.backups, self.launcher,
                             is_running=lambda: False, progress=seen.append)
        percents = [int(text.split(': ')[1].split(' %')[0]) for text in seen]
        self.assertEqual(percents[0], 0)
        self.assertEqual(percents, sorted(percents))                         # jamais en arriere
        self.assertTrue(any(0 < p < 100 for p in percents))                  # avancement visible
        self.assertTrue(seen[-1].startswith('Copie des mods : 100 % (5/5 fichiers'), seen[-1])

    def test_progress_text(self):
        self.assertEqual(room.progress_text(12_500_000, 30_000_000, 3, 7),
                         'Copie des mods : 41 % (3/7 fichiers, 12.5 / 30.0 Mo)')
        self.assertEqual(room.progress_text(0, 0, 0, 1), 'Copie des mods : 100 % (0/1 fichiers, 0.0 / 0.0 Mo)')

    def test_different_in_other_folder_is_moved(self):
        put(self.host_mods, 'CC/new/hat.package', b'H' * 40)
        put(self.guest_mods, 'old/hat.package', b'h' * 41)
        server, port = self.open_room()
        lines, plan = self.plan(port)
        self.apply(port, plan)
        self.assertEqual(self.by_name(self.guest_mods)['hat.package'], ['CC/new/hat.package'])
        [backup] = self.backups.iterdir()
        self.assertEqual((backup / 'old' / 'hat.package').read_bytes(), b'h' * 41)

    def test_nothing_without_agreement(self):
        server, port = self.open_room(accept=False)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('GET', '/modfile/0', headers={room.CODE_HEADER: CODE, room.SESSION_HEADER: SESSION})
        self.assertEqual(conn.getresponse().status, 409)
        conn.close()

    def test_unknown_index_and_paths(self):
        server, port = self.open_room()
        for path, status in (('/modfile/999', 404), ('/modfile/-1', 404), ('/modfile/1/../../x', 404),
                             ('/modfile/abc', 404)):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            conn.request('GET', path, headers={room.CODE_HEADER: CODE, room.SESSION_HEADER: SESSION})
            self.assertEqual(conn.getresponse().status, status, path)
            conn.close()

    def test_host_file_changed_after_room(self):
        server, port = self.open_room()
        lines, plan = self.plan(port)
        (self.host_mods / 'only_host.package').write_bytes(b'o' * 51)      # change apres la liste
        before = (self.guest_mods / 'CC' / 'shoes.package').read_bytes()
        with self.assertRaisesRegex(room.RoomError, 'mod\\(s\\) copié\\(s\\) avant l\'arrêt'):
            self.apply(port, plan)
        self.assertFalse((self.guest_mods / 'only_host.package').exists())
        self.assertEqual([p for p in self.launcher.glob('*.part')], [])
        # Les fichiers deja traites sont coherents (copie complete ou ancienne version intacte).
        shoes = (self.guest_mods / 'CC' / 'shoes.package').read_bytes()
        self.assertIn(shoes, (before, b's' * 200))

    def test_wrong_content_refused(self):
        server, port = self.open_room()
        lines, plan = self.plan(port)
        same_size = b'X' * (self.host_mods / 'only_host.package').stat().st_size
        (self.host_mods / 'only_host.package').write_bytes(same_size)        # meme taille, autre contenu
        with self.assertRaisesRegex(room.RoomError, 'SHA-256 incorrect'):
            self.apply(port, plan)
        self.assertFalse((self.guest_mods / 'only_host.package').exists())

    def test_game_running(self):
        server, port = self.open_room()
        lines, plan = self.plan(port)
        before = tree_snapshot(self.guest_mods)
        with self.assertRaisesRegex(room.RoomError, 'Fermez Les Sims 4'):
            self.apply(port, plan, is_running=lambda: True)
        self.assertEqual(tree_snapshot(self.guest_mods), before)
        with self.assertRaisesRegex(room.RoomError, 'Fermez Les Sims 4'):
            room.plan_mods_sync('127.0.0.1', port, CODE, SESSION, self.guest_docs, self.launcher,
                                is_running=lambda: True)

    def test_host_without_sha_refused(self):
        server, port = self.open_room()
        server.mods = mods.mods_list(self.host_mods, with_sha=False)
        with self.assertRaisesRegex(mods.ModsError, 'empreintes SHA-256'):
            self.plan(port)

    def test_unsafe_names_refused(self):
        for rel in ('CON.package', 'a./b.package', 'x /b.package', 'a/nul.ts4script', 'a\x01/b.package'):
            self.assertIsNone(room._safe_rel_path(rel), rel)
        self.assertEqual(room._safe_rel_path('CC/Cheveux/hair.package'), ['CC', 'Cheveux', 'hair.package'])

    def test_limits(self):
        server, port = self.open_room()
        with mock.patch.object(room, 'MAX_SYNC_TOTAL', 100):
            with self.assertRaisesRegex(mods.ModsError, 'Trop de mods à copier'):
                self.plan(port)
        with mock.patch.object(room, 'MAX_SYNC_FILE', 10):
            with self.assertRaisesRegex(mods.ModsError, 'Mod trop grand'):
                self.plan(port)


class ModSyncWindowTest(unittest.TestCase):
    def test_button_confirms_before_copy(self):
        import tkinter as tk
        from test_sims4mp_room_gui import free_game_port
        tmp = Path(tempfile.mkdtemp(prefix='sims4mp_modsync_gui_'))
        self.addCleanup(shutil.rmtree, tmp, True)
        for target, value in [('base_dir', tmp), ('detect_game', core.GameInstall(None, None)),
                              ('local_ipv4_addresses', ['127.0.0.1']), ('game_is_running', False)]:
            patcher = mock.patch.object(core, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        port = free_game_port()
        apps = {}
        for who, role in (('hote', core.ROLE_HOST), ('invite', core.ROLE_JOIN)):
            docs = tmp / who / 'Documents'
            game = docs / 'Electronic Arts' / NBSP_GAME
            (game / 'saves').mkdir(parents=True)
            put(game / 'Mods', 'Resource.cfg', b'')
            from test_sims4mp_room import mod_bytes
            put(game / 'Mods', core.MOD_FILE, mod_bytes('0.4.0'))
            app = core.LauncherApp(tk.Toplevel(root), documents=docs)
            app._spawn = lambda worker: worker()
            app.role.set(role)
            app._on_role()
            app.port.set(str(port))
            apps[who] = (app, game)
        host, host_game = apps['hote']
        guest, guest_game = apps['invite']
        put(host_game / 'Mods', 'CC/hair.package', b'h' * 64)
        make_save(host_game / 'saves' / 'Slot_00000002.save')
        host._refresh_saves()
        host._create_room()
        host._poll_install()
        self.addCleanup(host._close_room)
        guest.ip.set('127.0.0.1')
        guest.room_code.set(host.room.code)
        for answer in (False, True):
            with mock.patch.object(guest, '_confirm', return_value=answer) as confirm:
                guest._sync_mods()
                guest._presence_tick()
                if host.room.guests and list(host.room.guests.values())[0]['accord'] == 'attente':
                    host._answer_guest(guest.presence['session'], True)
                    guest._presence_tick()
                    guest._presence_tick()
                guest._poll_install()                       # comparaison -> confirmation
                guest._poll_install()                       # copie (si « Oui »)
            confirm.assert_called_once()
            copied = (guest_game / 'Mods' / 'CC' / 'hair.package').exists()
            self.assertEqual(copied, answer)
        self.assertEqual((guest_game / 'Mods' / 'CC' / 'hair.package').read_bytes(), b'h' * 64)
        self.assertIsNone(guest.task_progress)                       # effacee a la fin de la tache
        # Pendant une tache, la barre d'etat affiche le pourcentage recu du thread.
        guest.installing = False
        guest._start_task('Copie des mods...', lambda: guest._set_progress(
            room.progress_text(5_000_000, 10_000_000, 1, 2)))
        guest._poll_install()
        self.assertEqual(guest.status.cget('text'), 'Copie des mods : 50 % (1/2 fichiers, 5.0 / 10.0 Mo)')
        guest.results.put(('ok', ['fin'], 'Mods copiés (2)'))
        guest._poll_install()
        self.assertEqual(guest.status.cget('text'), 'Mods copiés (2)')


if __name__ == '__main__':
    unittest.main()
