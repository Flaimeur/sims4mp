# Tests de la presence et de « Lancer pour tous » (etape 9b). Room reelle sur
# 127.0.0.1, dossiers temporaires imitant « Les Sims 4 ». Le jeu n'est jamais
# lance : launch_game est remplace par un faux qui note les appels.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_presence.py -v

import http.client
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402
import sims4mp_room as room  # noqa: E402
from test_sims4mp_room import NBSP_GAME, make_save, mod_bytes  # noqa: E402
from test_sims4mp_room_gui import free_game_port  # noqa: E402

CODE = 'ABCD2345'


class RoomPresenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_presence_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        saves = self.tmp / 'saves'
        saves.mkdir()
        save = make_save(saves / 'Slot_00000002.save')
        self.server = room.RoomServer(save, saves, self.tmp / 'snap', '0.4.0', '127.0.0.1', 0, code=CODE)
        self.server.prepare(is_running=lambda: False)
        self.port = self.server.start()
        self.addCleanup(self.server.stop)
        self.now = [1000.0]
        self.server._clock = lambda: self.now[0]

    def presence(self, session='a' * 16, pseudo='Alex', state='connecte', allowed=False, code=CODE):
        return room.send_presence('127.0.0.1', self.port, code, session, pseudo, state, allowed)

    def test_guest_listed_and_signal(self):
        self.assertEqual(self.presence(pseudo='Петрова', allowed=True), {'lancer': None, 'accord': 'attente'})
        [guest] = self.server.guests_snapshot()
        self.assertEqual((guest['pseudo'], guest['ip'], guest['etat'], guest['autorise'], guest['accord']),
                         ('Петрова', '127.0.0.1', 'connecte', True, 'attente'))
        token = self.server.request_launch()
        # Pas de signal tant que l'hote n'a pas accepte l'invite.
        self.assertEqual(self.presence(), {'lancer': None, 'accord': 'attente'})
        self.server.accept_guest('a' * 16)
        self.assertEqual(self.presence(state='partie_recue'), {'lancer': token, 'accord': 'accepte'})
        self.assertEqual(self.server.guests_snapshot()[0]['etat'], 'partie_recue')
        events = ' '.join(self.server.take_events())
        self.assertIn('Петрова demande à rejoindre la room (127.0.0.1)', events)
        self.assertIn('Signal « Lancer pour tous » envoyé', events)

    def test_silent_guest_removed(self):
        self.presence()
        self.now[0] += room.PRESENCE_TIMEOUT - 1
        self.assertEqual(len(self.server.guests_snapshot()), 1)
        self.now[0] += 2
        self.assertEqual(self.server.guests_snapshot(), [])
        self.assertIn('Alex a quitté la room (plus de nouvelles)', self.server.take_events())

    def test_hostile_pseudo_cleaned(self):
        self.presence(pseudo='\x1b[31mMé\x07lodie' + 'x' * 50)
        pseudo = self.server.guests_snapshot()[0]['pseudo']
        self.assertTrue(pseudo.isprintable())
        self.assertLessEqual(len(pseudo), room.PSEUDO_MAX)
        self.presence(session='b' * 16, pseudo='\x00\x01')
        self.assertIn('Joueur', [g['pseudo'] for g in self.server.guests_snapshot()])

    def test_malformed_presence_refused(self):
        for headers in [{room.SESSION_HEADER: 'zz', room.STATE_HEADER: 'connecte', room.ALLOW_HEADER: '0'},
                        {room.SESSION_HEADER: 'a' * 16, room.STATE_HEADER: 'admin', room.ALLOW_HEADER: '0'},
                        {room.SESSION_HEADER: 'a' * 16, room.STATE_HEADER: 'connecte', room.ALLOW_HEADER: 'oui'}]:
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
            conn.request('GET', '/presence', headers=dict(headers, **{room.CODE_HEADER: CODE}))
            self.assertEqual(conn.getresponse().status, 400, headers)
            conn.close()
        self.assertEqual(self.server.guests_snapshot(), [])
        with self.assertRaises(room.RoomError):
            room.send_presence('127.0.0.1', self.port, CODE, 'pas-hex', 'x', 'connecte', False)

    def test_wrong_code_and_full_room(self):
        with self.assertRaisesRegex(room.RoomError, 'Code de room refusé'):
            self.presence(code='ZZZZ2345')
        for i in range(room.MAX_GUESTS):
            self.presence(session='{:016x}'.format(i + 1))
        with self.assertRaisesRegex(room.RoomError, 'Room pleine'):
            self.presence(session='f' * 16)
        self.presence(session='{:016x}'.format(1))              # un invite deja connu continue


class LaunchAllWindowTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_launch_all_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for target, value in [('base_dir', self.tmp), ('detect_game', gui.GameInstall(None, None)),
                              ('local_ipv4_addresses', ['127.0.0.1']), ('game_is_running', False)]:
            patcher = mock.patch.object(gui, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.launched = []

        def fake_launch(target=gui.STEAM_GAME_URL):
            self.launched.append(target)
            return ['Lancement simulé']
        patcher = mock.patch.object(gui, 'launch_game', fake_launch)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.port = free_game_port()
        self.host = self.make_app('hote', gui.ROLE_HOST)
        make_save(self.saves('hote') / 'Slot_00000002.save', 'Partie commune', ['Dupont'])
        self.host._refresh_saves()
        self.host._create_room()
        self.host._poll_install()
        self.addCleanup(self.host._close_room)
        self.guest = self.make_app('invite', gui.ROLE_JOIN)
        self.guest.game = gui.GameInstall('steam', self.tmp / 'TS4_x64.exe')
        self.guest.ip.set('127.0.0.1')
        self.guest.room_code.set(self.host.room.code)
        self.guest.pseudo.set('Alex')

    def saves(self, who):
        return self.tmp / who / 'Documents' / 'Electronic Arts' / NBSP_GAME / 'saves'

    def make_app(self, who, role):
        import tkinter as tk
        docs = self.tmp / who / 'Documents'
        game = docs / 'Electronic Arts' / NBSP_GAME
        (game / 'Mods').mkdir(parents=True)
        (game / 'Mods' / 'Resource.cfg').write_text('')
        (game / 'Mods' / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        (game / 'saves').mkdir()
        app = gui.LauncherApp(tk.Toplevel(self.root), documents=docs)
        app._spawn = lambda worker: worker()                 # sans thread
        app.role.set(role)
        app._on_role()
        app.port.set(str(self.port))
        return app

    def join(self, accept=True):
        """Rejoindre : demande (presence), accord de l'hote, puis lecture, confirmation, installation."""
        with mock.patch.object(self.guest, '_confirm', return_value=accept):
            self.guest._join_room()
            self.tick()                                        # la demande arrive chez l'hote
            self.host._answer_guest(self.guest.presence['session'], True)
            self.tick(2)                                       # l'invite apprend l'accord -> lecture
            self.guest._poll_install()                         # infos lues -> confirmation
            self.guest._poll_install()                         # telechargement et installation

    def tick(self, n=1):
        for _ in range(n):
            self.guest._presence_tick()

    def players(self):
        self.host._refresh_players()
        return self.host.players_label.cget('text')

    def test_host_sees_guest(self):
        self.assertEqual(self.players(), 'En attente d\'un joueur…')
        self.join()
        self.tick(2)
        self.assertEqual(self.players(), 'Alex · 127.0.0.1 · partie reçue · lancement non autorisé')
        self.guest.allow_host_launch.set(True)
        self.tick(2)
        self.assertIn('lancement autorisé', self.players())
        self.assertIn('Connecté à 127.0.0.1 · partie reçue', self.guest.presence_label.cget('text'))

    def test_unchecked_box_never_launches(self):
        self.join()
        self.tick(2)
        self.host._launch_all()
        self.tick(2)
        self.assertEqual(self.launched, [])
        self.assertEqual(self.guest.presence['etat'], 'lancement_refuse')
        self.assertIn('vous n\'avez pas coché', self.guest.messages.get('1.0', 'end'))
        self.tick()
        self.assertIn('lancement refusé', self.players())

    def test_checked_and_received_launches_once(self):
        self.guest.allow_host_launch.set(True)
        self.join()
        self.tick(2)
        self.host._launch_all()
        self.tick(2)
        self.assertEqual(self.launched, [gui.STEAM_GAME_URL])
        self.assertEqual(self.guest.presence['etat'], 'jeu_lance')
        self.tick(3)
        self.assertEqual(len(self.launched), 1)                  # un seul lancement par signal
        self.host._launch_all()                                  # nouveau signal
        self.tick(2)
        self.assertEqual(len(self.launched), 2)

    def test_not_received_refused(self):
        self.guest.allow_host_launch.set(True)
        self.join(accept=False)                                   # room trouvee, partie refusee
        self.tick(2)
        self.host._launch_all()
        self.tick(2)
        self.assertEqual(self.launched, [])
        self.assertIn('pas été reçue', self.guest.messages.get('1.0', 'end'))

    def test_game_already_running_refused(self):
        self.guest.allow_host_launch.set(True)
        self.join()
        self.tick(2)

        def running(target=gui.STEAM_GAME_URL):
            raise gui.LauncherError('Les Sims 4 est deja lance (TS4_x64.exe en cours d\'execution).')
        with mock.patch.object(gui, 'launch_game', running):
            self.host._launch_all()
            self.tick(2)
        self.assertEqual(self.guest.presence['etat'], 'lancement_refuse')
        self.assertIn('deja lance', self.guest.messages.get('1.0', 'end'))

    def test_signal_before_joining_is_ignored(self):
        self.host._launch_all()                                   # avant l'arrivee de l'invite
        self.guest.allow_host_launch.set(True)
        self.join()
        self.tick(3)
        self.assertEqual(self.launched, [])

    def test_room_lost_after_three_failures(self):
        self.join()
        self.tick(2)
        self.host._close_room()
        self.tick(4)
        self.assertIsNone(self.guest.presence)
        self.assertEqual(self.guest.status.cget('text'), 'Room perdue : hôte injoignable')
        self.assertEqual(self.guest.presence_label.cget('text'), 'Non connecté à une room.')

    def test_leave_room(self):
        self.join()
        self.tick(2)
        self.guest._leave_room()
        self.assertIsNone(self.guest.presence)
        self.assertEqual(str(self.guest.leave_room_button.cget('state')), 'disabled')
        self.host.room._clock = lambda: 10 ** 9                   # 10 s plus tard chez l'hote
        self.assertEqual(self.players(), 'En attente d\'un joueur…')


if __name__ == '__main__':
    unittest.main()
