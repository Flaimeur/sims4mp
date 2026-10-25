# Tests des packs (DLC) : lecture du dossier du jeu, comparaison hote / invite, /packs de la room.
# Dossiers temporaires (faux jeu, faux « Les Sims 4 » avec espaces insecables), room sur 127.0.0.1.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_packs.py -v

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as core  # noqa: E402
import sims4mp_room as room  # noqa: E402
from test_sims4mp_mods import CODE  # noqa: E402
from test_sims4mp_room import NBSP_GAME, SESSION, accept_guest, make_save  # noqa: E402


def make_game(root, installed=('EP01', 'GP04'), empty=('SP01',)):
    """Faux jeu Windows : <root>/Game/Bin/TS4_x64.exe et un dossier par pack."""
    exe = root / 'Game' / 'Bin' / 'TS4_x64.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'')
    for code in installed:
        (root / code).mkdir()
        (root / code / ('SimulationFullBuild0.package' if code != 'GP04' else 'ClientFullBuild0.package')
         ).write_bytes(b'DBPF')
    for code in empty:
        (root / code).mkdir()                          # dossier vide : pack desinstalle
    (root / 'Data').mkdir()
    (root / 'EP1').mkdir()                             # pas un code de pack
    return core.GameInstall('steam', exe)


class PacksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_packs_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_installed_packs_windows(self):
        game = make_game(self.tmp / 'The Sims 4')
        self.assertEqual(core.installed_packs(game), ['EP01', 'GP04'])
        self.assertIsNone(core.installed_packs(core.GameInstall(None, None)))
        self.assertIsNone(core.installed_packs(None))

    def test_installed_packs_mac_app(self):
        app = self.tmp / 'The Sims 4.app'
        (app / 'Contents' / 'EP02').mkdir(parents=True)
        (app / 'Contents' / 'EP02' / 'SimulationFullBuild0.package').write_bytes(b'DBPF')
        self.assertEqual(core.installed_packs(core.GameInstall('ea', app)), ['EP02'])

    def test_labels_and_summary(self):
        self.assertEqual(core.pack_label('EP05'), 'EP05 (Seasons)')
        self.assertEqual(core.pack_label('SP77'), 'SP77')
        self.assertEqual(core.packs_summary(['EP01', 'EP02', 'GP01', 'SP01', 'FP01']),
                         '2 packs d\'extension, 1 pack de jeu, 1 kit, 1 pack gratuit')
        self.assertEqual(core.packs_summary([]), 'aucun pack')

    def test_compare(self):
        self.assertEqual(core.compare_packs(['EP01', 'GP04'], ['EP01', 'GP04']),
                         ['Packs : identiques à l\'hôte (1 pack d\'extension, 1 pack de jeu).'])
        lines = core.compare_packs(['EP01', 'EP05', 'GP04'], ['EP01', 'GP04', 'SP02'])
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('ATTENTION : 1 pack(s) de l\'hôte absent(s) chez vous : EP05 (Seasons)'))
        self.assertTrue(lines[1].startswith('ATTENTION : 1 pack(s) que l\'hôte n\'a pas : SP02'))
        self.assertIn('trop ancien', core.compare_packs(None, ['EP01'])[0])
        self.assertIn('jeu introuvable', core.compare_packs(['EP01'], None)[0])


class RoomPacksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_room_packs_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(core, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        saves = self.tmp / 'hote' / 'Electronic Arts' / NBSP_GAME / 'saves'
        saves.mkdir(parents=True)
        self.save = make_save(saves / 'Slot_00000002.save')
        self.saves = saves

    def open_room(self, packs):
        server = room.RoomServer(self.save, self.saves, self.tmp / 'snap', '0.18.0', '127.0.0.1', 0, code=CODE,
                                 packs=packs)
        server.prepare(is_running=lambda: False)
        port = server.start()
        self.addCleanup(server.stop)
        accept_guest(server, port)
        return port

    def test_host_packs_served_after_agreement(self):
        port = self.open_room(['EP01', 'GP04', 'SP01'])
        self.assertEqual(room.fetch_packs('127.0.0.1', port, CODE, SESSION), ['EP01', 'GP04', 'SP01'])

    def test_older_host_without_packs(self):
        port = self.open_room(None)
        self.assertIsNone(room.fetch_packs('127.0.0.1', port, CODE, SESSION))

    def test_unknown_guest_refused(self):
        server = room.RoomServer(self.save, self.saves, self.tmp / 'snap', '0.18.0', '127.0.0.1', 0, code=CODE,
                                 packs=['EP01'])
        server.prepare(is_running=lambda: False)
        port = server.start()
        self.addCleanup(server.stop)
        with self.assertRaises(room.RoomError):                 # pas d'accord de l'hote : rien n'est lisible
            room.fetch_packs('127.0.0.1', port, CODE, SESSION)

    def test_window_pack_lines(self):
        import tkinter as tk
        port = self.open_room(['EP01', 'EP05'])
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        game = make_game(self.tmp / 'jeu' / 'The Sims 4', installed=('EP01',), empty=())
        with mock.patch.object(core, 'detect_game', return_value=game):
            app = core.LauncherApp(root, documents=self.tmp)
        presence = {'ip': '127.0.0.1', 'port': port, 'code': CODE, 'session': SESSION}
        lines = app._pack_lines(presence)
        self.assertEqual(len(lines), 1)
        self.assertIn('EP05 (Seasons)', lines[0])
        app.game = core.GameInstall(None, None)
        self.assertIn('jeu introuvable', app._pack_lines(presence)[0])
        import socket
        with socket.socket() as probe:                            # port libre puis ferme : personne n'ecoute
            probe.bind(('127.0.0.1', 0))
            free = probe.getsockname()[1]
        bad = dict(presence, port=free)                           # hote injoignable : message, pas d'erreur
        self.assertIn('comparaison impossible', app._pack_lines(bad)[0])


if __name__ == '__main__':
    unittest.main()
