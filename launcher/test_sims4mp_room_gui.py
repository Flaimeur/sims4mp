# Tests de la carte Room dans la fenetre (etape 7c) : un lanceur hote et un
# lanceur invite dans le meme processus, room reelle sur 127.0.0.1, dossiers
# temporaires imitant « Les Sims 4 ». Les taches de fond sont executees sans thread.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_room_gui.py -v

import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402
import sims4mp_room as room  # noqa: E402
from test_sims4mp_room import NBSP_GAME, make_save, mod_bytes, snapshot  # noqa: E402


def free_game_port():
    """Un port du jeu dont le port + 1 (la room) est libre."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        if port - 1 >= gui.PORT_MIN:
            return port - 1
    raise RuntimeError('aucun port libre')


class RoomWindowTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_room_gui_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # game_is_running simule : les tests ne dependent pas du jeu ouvert sur ce PC.
        for target, value in [('base_dir', self.tmp), ('detect_game', gui.GameInstall(None, None)),
                              ('local_ipv4_addresses', ['127.0.0.1']), ('game_is_running', False)]:
            patcher = mock.patch.object(gui, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.host_docs, self.host_saves = self.make_docs('hote', mod='0.4.0')
        self.host_save = make_save(self.host_saves / 'Slot_00000002.save', 'Partie commune', ['Петрова'])
        self.guest_docs, self.guest_saves = self.make_docs('invite', mod='0.4.0')
        make_save(self.guest_saves / 'Slot_00000001.save', 'Partie invité', ['Martin'])
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.port = free_game_port()

    def destroy_root(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def make_docs(self, who, mod=None):
        docs = self.tmp / who / 'Documents'
        game = docs / 'Electronic Arts' / NBSP_GAME
        (game / 'Mods').mkdir(parents=True)
        (game / 'Mods' / 'Resource.cfg').write_text('')
        if mod:
            (game / 'Mods' / gui.MOD_FILE).write_bytes(mod_bytes(mod))
        (game / 'saves').mkdir()
        return docs, game / 'saves'

    def make_app(self, docs, role):
        import tkinter as tk
        app = gui.LauncherApp(tk.Toplevel(self.root), documents=docs)
        app._spawn = lambda worker: worker()                 # taches de fond sans thread
        app.role.set(role)
        app._on_role()
        app.port.set(str(self.port))
        return app

    def open_host_room(self):
        host = self.make_app(self.host_docs, gui.ROLE_HOST)
        [label] = host.save_box.cget('values')
        self.assertTrue(label.startswith('Slot_00000002.save · '), label)
        host._create_room()
        host._poll_install()
        self.addCleanup(host._close_room)
        return host

    def test_host_then_guest(self):
        host = self.open_host_room()
        self.assertIsNotNone(host.room)
        code = host.room.code
        self.assertEqual(host.status.cget('text'), 'Room ouverte (code {})'.format(code))
        self.assertEqual(host.room_code_label.cget('text'), code)
        self.assertEqual(host.room_label.cget('text'), 'IP 127.0.0.1 · port {}'.format(self.port + 1))
        self.assertEqual(str(host.create_room_button.cget('state')), 'disabled')
        self.assertEqual(str(host.close_room_button.cget('state')), 'normal')
        host._copy_room()
        self.assertEqual(host.root.clipboard_get(),
                         'Sims4MP · IP 127.0.0.1 · port {} · code {}'.format(self.port + 1, code))

        before = snapshot(self.guest_saves)
        guest = self.make_app(self.guest_docs, gui.ROLE_JOIN)
        guest.ip.set('127.0.0.1')
        guest.room_code.set(code.lower())
        # Verifier sans copier : d'abord la demande, puis l'accord de l'hote ; rien n'est ecrit.
        guest._check_room()
        self.assertEqual(guest.status.cget('text'), 'En attente de l\'accord de l\'hôte')
        guest._presence_tick()
        host._answer_guest(guest.presence['session'], True)
        guest._presence_tick()
        guest._presence_tick()                                  # accord recu -> verification
        guest._poll_install()
        self.assertEqual(guest.status.cget('text'), 'Vérification OK : rien n\'a été écrit')
        self.assertIn('Partie commune', guest.messages.get('1.0', 'end'))
        self.assertEqual(snapshot(self.guest_saves), before)
        # Rejoindre (deja accepte) puis refuser la confirmation : rien n'est ecrit.
        with mock.patch.object(guest, '_confirm', return_value=False):
            guest._join_room()
            guest._poll_install()
        self.assertEqual(guest.status.cget('text'), 'Annulé : rien n\'a été écrit')
        self.assertEqual(snapshot(self.guest_saves), before)
        self.assertFalse((self.tmp / gui.BACKUP_DIR_NAME).exists())
        # Rejoindre et accepter.
        with mock.patch.object(guest, '_confirm', return_value=True) as confirm:
            guest._join_room()
            guest._poll_install()                              # infos lues -> confirmation
            guest._poll_install()                              # telechargement et installation
        self.assertIn('Петрова', confirm.call_args.args[1])
        self.assertIn('pas encore synchronisées', confirm.call_args.args[1])
        self.assertEqual(guest.status.cget('text'), 'Sauvegarde de l\'hôte installée')
        self.assertEqual((self.guest_saves / room.RESERVED_SLOT).read_bytes(), self.host_save.read_bytes())
        self.assertEqual(snapshot(self.guest_saves)['Slot_00000001.save'], before['Slot_00000001.save'])
        # L'hote voit l'envoi dans son journal.
        host._poll_room()
        self.assertIn('Sauvegarde envoyée à 127.0.0.1', host.messages.get('1.0', 'end'))
        host._close_room()
        self.assertIsNone(host.room)
        self.assertEqual(host.status.cget('text'), 'Room fermée')
        self.assertEqual(list((self.tmp / 'sims4mp_room').iterdir()), [])     # copie figee supprimee

    def test_guest_input_errors_without_network(self):
        guest = self.make_app(self.guest_docs, gui.ROLE_JOIN)
        with mock.patch.object(gui.socket, 'create_connection', side_effect=AssertionError('reseau')):
            guest.ip.set('127.0.0.1')
            guest.room_code.set('ABC')
            guest._check_room()
            self.assertIn('Code de room invalide', guest.status.cget('text'))
            guest.room_code.set('ABCD2345')
            guest.ip.set('192.168.1')
            guest._join_room()
            self.assertIn('Adresse IP invalide', guest.status.cget('text'))
            guest.ip.set('127.0.0.1')
            guest.port.set('65535')
            guest._check_room()
            self.assertIn('la room utilise le port du jeu + 1', guest.status.cget('text'))
        self.assertFalse(guest.installing)

    def test_host_needs_mod(self):
        (self.host_docs / 'Electronic Arts' / NBSP_GAME / 'Mods' / gui.MOD_FILE).unlink()
        host = self.make_app(self.host_docs, gui.ROLE_HOST)
        host._create_room()
        host._poll_install()
        self.assertIsNone(host.room)
        self.assertIn('Installez le mod', host.status.cget('text'))

    def test_no_saves_disables_create(self):
        self.host_save.unlink()
        host = self.make_app(self.host_docs, gui.ROLE_HOST)
        self.assertEqual(host.save_box.cget('values'), '')
        self.assertEqual(str(host.create_room_button.cget('state')), 'disabled')
        self.assertEqual(host.room_code_label.cget('text'), '')

    def test_quit_closes_room(self):
        host = self.open_host_room()
        port = host.room.port
        host._quit()
        self.assertIsNone(host.room)
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1).close()


if __name__ == '__main__':
    unittest.main()
