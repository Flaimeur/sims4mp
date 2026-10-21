# Tests de la page « Partie a deux » (etape 9a) : plus de carte Connexion, code de
# room bien visible, reglage enregistre automatiquement, carte Reseau dans Options.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_partie.py -v

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402
from test_sims4mp_room import NBSP_GAME, make_save, mod_bytes  # noqa: E402
from test_sims4mp_room_gui import free_game_port  # noqa: E402


def card_titles(page):
    """Titres des cartes d'une page, dans l'ordre."""
    titles = []
    for card in sorted(page.winfo_children(), key=lambda w: int(w.grid_info().get('row', 0))):
        for child in card.winfo_children():
            try:
                style = str(child.cget('style'))
            except Exception:                       # widget sans style ttk
                continue
            if style == 'CardTitle.TLabel':
                titles.append(child.cget('text'))
    return titles


class PartieTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_partie_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for target, value in [('base_dir', self.tmp), ('detect_game', gui.GameInstall(None, None)),
                              ('local_ipv4_addresses', ['127.0.0.1']), ('game_is_running', False)]:
            patcher = mock.patch.object(gui, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.docs = self.tmp / 'Documents'
        game = self.docs / 'Electronic Arts' / NBSP_GAME
        (game / 'Mods').mkdir(parents=True)
        (game / 'Mods' / 'Resource.cfg').write_text('')
        (game / 'Mods' / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        (game / 'saves').mkdir()
        make_save(game / 'saves' / 'Slot_00000002.save', 'Partie commune', ['Dupont'])
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = gui.LauncherApp(self.root, documents=self.docs)
        self.app._spawn = lambda worker: worker()

    def test_connexion_card_removed(self):
        self.assertEqual(card_titles(self.app.pages['connexion']), ['Mode de jeu', 'Room'])
        self.assertEqual(card_titles(self.app.pages['options']), ['GitHub', 'Outils', 'Réseau'])
        texts = []
        stack = [self.app.pages['connexion']]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            try:
                texts.append(widget.cget('text'))
            except Exception:
                pass
        self.assertNotIn('Enregistrer le réglage', texts)
        self.assertNotIn('IP locales', texts)

    def test_network_card_in_options(self):
        # IP locales et port vivent maintenant dans Options → Reseau.
        self.assertTrue(str(self.app.ip_list).startswith(str(self.app.pages['options'])))
        self.assertTrue(str(self.app.copy_button).startswith(str(self.app.pages['options'])))
        self.app.port.set('8000')
        self.assertEqual(self.app._room_port(), 8001)

    def test_code_shown_big_and_whole(self):
        self.app.port.set(str(free_game_port()))
        self.app._create_room()
        self.app._poll_install()
        self.addCleanup(self.app._close_room)
        code = self.app.room.code
        self.assertEqual(self.app.room_code_label.cget('text'), code)
        self.assertEqual(str(self.app.room_code_label.cget('style')), 'RoomCode.TLabel')
        self.assertIn(str(self.app.room_code_label.cget('wraplength')), ('', '0'))   # jamais coupe
        self.app._copy_room()
        self.assertIn('code {}'.format(code), self.root.clipboard_get())
        self.assertEqual(self.app.status.cget('text'), 'Invitation copiée')

    def test_settings_saved_automatically(self):
        path = gui.settings_path(self.docs)
        port = free_game_port()
        self.app.port.set(str(port))
        self.app._create_room()
        self.app._poll_install()
        self.app._close_room()
        self.assertEqual(gui.read_settings(path), {'role': 'host', 'ip': '', 'port': port})
        self.app.role.set(gui.ROLE_JOIN)
        self.app._on_role()
        self.app.ip.set('192.168.1.30')
        self.app.room_code.set('ABCD2345')
        with mock.patch('sims4mp_room.fetch_room_info', side_effect=gui.LauncherError('injoignable')):
            self.app._join_room()
            self.app._poll_install()
        self.assertEqual(gui.read_settings(path), {'role': 'join', 'ip': '192.168.1.30', 'port': port})

    def test_invalid_join_saves_nothing(self):
        path = gui.settings_path(self.docs)
        self.app.role.set(gui.ROLE_JOIN)
        self.app._on_role()
        self.app.ip.set('192.168.1')
        self.app.room_code.set('ABCD2345')
        self.app._join_room()
        self.assertFalse(path.exists())

    def test_join_view(self):
        self.app.role.set(gui.ROLE_JOIN)
        self.app._on_role()
        self.assertEqual(self.app.pseudo.get(), gui.default_pseudo())
        self.assertNotIn('disabled', self.app.ip_entry.state())
        self.app.role.set(gui.ROLE_HOST)
        self.app._on_role()
        self.assertIn('disabled', self.app.ip_entry.state())

    def test_default_pseudo(self):
        for raw, expected in [('Alex', 'Alex'), ('  Élise\x07 ', 'Élise'), ('x' * 40, 'x' * 24),
                              ('', 'Joueur'), ('\x00\x01', 'Joueur')]:
            with mock.patch('getpass.getuser', return_value=raw):
                self.assertEqual(gui.default_pseudo(), expected, repr(raw))
        with mock.patch('getpass.getuser', side_effect=OSError):
            self.assertEqual(gui.default_pseudo(), 'Joueur')


if __name__ == '__main__':
    unittest.main()
