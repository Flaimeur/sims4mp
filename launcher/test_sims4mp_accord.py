# Tests de l'accord de l'hote, d'un envoi par invite accepte, de la fermeture du
# partage et du choix de la partie (sauvegarde automatique jamais par defaut).
# Uniquement des parties jetables fabriquees ici, dans des dossiers temporaires.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_accord.py -v

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
from test_sims4mp_room import NBSP_GAME, make_save, mod_bytes, snapshot  # noqa: E402
from test_sims4mp_room_gui import free_game_port  # noqa: E402

CODE = 'ABCD2345'
A, B = 'a' * 16, 'b' * 16


class AgreementRoomTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_accord_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        host_saves = self.tmp / 'hote_saves'
        host_saves.mkdir()
        self.host_save = make_save(host_saves / 'Slot_00000002.save', 'Partie jetable', ['Jetable'])
        self.server = room.RoomServer(self.host_save, host_saves, self.tmp / 'snap', '0.4.0',
                                      '127.0.0.1', 0, code=CODE)
        self.server.prepare(is_running=lambda: False)
        self.port = self.server.start()
        self.addCleanup(self.server.stop)
        self.docs = self.tmp / 'invite' / 'Documents'
        game = self.docs / 'Electronic Arts' / NBSP_GAME
        (game / 'Mods').mkdir(parents=True)
        (game / 'Mods' / 'Resource.cfg').write_text('')
        (game / 'Mods' / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.saves = game / 'saves'
        self.saves.mkdir()
        make_save(self.saves / 'Slot_00000001.save', 'Partie de l\'invité', ['Martin'])
        self.backups = self.tmp / 'invite' / 'sims4mp_backups'
        self.downloads = self.tmp / 'invite' / 'lanceur'
        self.downloads.mkdir()

    def presence(self, session=A, state='connecte'):
        return room.send_presence('127.0.0.1', self.port, CODE, session, 'Alex', state, False)

    def join(self, session=A):
        info = room.fetch_room_info('127.0.0.1', self.port, CODE, session)
        return room.apply_join('127.0.0.1', self.port, CODE, session, info, self.docs, self.backups,
                               self.downloads, is_running=lambda: False)

    def raw_status(self, path, session=A):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', path, headers={room.CODE_HEADER: CODE, room.SESSION_HEADER: session})
        status = conn.getresponse().status
        conn.close()
        return status

    def test_nothing_readable_before_agreement(self):
        for path in ('/info', '/save', '/mods'):
            self.assertEqual(self.raw_status(path), 409, path)            # inconnu : pas de presence
        self.assertEqual(self.presence()['accord'], 'attente')
        for path in ('/info', '/save', '/mods'):
            self.assertEqual(self.raw_status(path), 409, path)            # connu mais pas accepte
        with self.assertRaisesRegex(room.RoomError, 'En attente de l\'accord'):
            room.fetch_room_info('127.0.0.1', self.port, CODE, A)
        self.assertNotIn('a lu les informations', ' '.join(self.server.take_events()))

    def test_agreement_bound_to_session_and_ip(self):
        self.presence(A)
        self.presence(B)
        self.server.accept_guest(A)
        self.assertEqual(self.raw_status('/info', A), 200)
        self.assertEqual(self.raw_status('/info', B), 409)                # autre session non acceptee
        self.assertEqual(self.raw_status('/info', 'c' * 16), 409)         # session inconnue
        # La meme session vue depuis une autre adresse : refusee.
        self.assertEqual(self.server.update_guest(A, '192.168.1.99', 'Intrus', 'connecte', False), 'autre_ip')
        self.assertEqual(self.server.authorize(A, '192.168.1.99', '/info'), (409, 'invité inconnu : présence et accord requis'))

    def test_refused_guest(self):
        self.presence(A)
        self.server.refuse_guest(A)
        self.assertEqual(self.presence(A)['accord'], 'refuse')            # reste refuse
        self.assertEqual(self.server.guests_snapshot(), [])
        self.assertEqual(self.server.accept_guest(A), False)
        with self.assertRaisesRegex(room.RoomError, 'refuse cette connexion'):
            room.fetch_room_info('127.0.0.1', self.port, CODE, A)

    def test_one_send_per_accepted_guest(self):
        self.presence(A)
        self.server.accept_guest(A)
        self.join(A)
        self.assertEqual(self.presence(A, 'partie_recue')['accord'], 'accepte')   # reception confirmee
        before = snapshot(self.saves)
        backups = sorted(self.backups.iterdir())
        with self.assertRaisesRegex(room.RoomError, 'déjà reçue'):
            self.join(A)
        self.assertEqual(snapshot(self.saves), before)                   # rien de reecrit
        self.assertEqual(sorted(self.backups.iterdir()), backups)        # aucune nouvelle copie datee
        self.assertEqual(self.raw_status('/save', A), 410)

    def test_sharing_closes_when_every_accepted_guest_received(self):
        for session in (A, B):
            self.presence(session)
            self.server.accept_guest(session)
        self.join(A)
        self.presence(A, 'partie_recue')
        self.assertTrue(self.server.sharing_open)                        # B n'a pas encore recu
        self.join(B)
        self.presence(B, 'partie_recue')
        self.assertFalse(self.server.sharing_open)
        self.assertIsNone(self.server.snapshot)                          # copie figee supprimee
        self.assertIn('Partage fermé : chaque invité accepté a reçu la partie (la room reste ouverte)',
                      self.server.take_events())
        # La room reste ouverte : presence et « Lancer pour tous » fonctionnent encore.
        token = self.server.request_launch()
        self.assertEqual(self.presence(A, 'partie_recue'), {'lancer': token, 'accord': 'accepte'})
        self.assertEqual(self.raw_status('/info', A), 200)

    def test_failed_transfer_can_be_retried(self):
        self.presence(A)
        self.server.accept_guest(A)
        good = self.server.info['taille']
        self.server.info['taille'] = good + 100                          # transfert tronque
        with self.assertRaises(room.RoomError):
            self.join(A)
        self.assertFalse(self.backups.exists())                          # rien ecrit
        self.server.info['taille'] = good
        self.join(A)                                                     # nouvel essai accepte
        self.assertEqual((self.saves / room.RESERVED_SLOT).read_bytes(), self.host_save.read_bytes())

    def test_auto_save_warning_in_plan(self):
        info = {'protocole': 2, 'version_mod': '0.4.0', 'fichier': 'Slot_ffffffff.save', 'taille': 10,
                'sha256': 'a' * 64, 'partie': 'Sauvegarde automatique', 'foyers': []}
        lines, plan = room.plan_join(info, self.docs, is_running=lambda: False)
        self.assertIn('sauvegarde automatique de l\'hôte (Slot_ffffffff)', '\n'.join(lines))
        lines, plan = room.plan_join(dict(info, fichier='Slot_00000002.save'), self.docs, is_running=lambda: False)
        self.assertNotIn('Slot_ffffffff', '\n'.join(lines))


class AgreementWindowTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_accord_gui_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for target, value in [('base_dir', self.tmp), ('detect_game', gui.GameInstall(None, None)),
                              ('local_ipv4_addresses', ['127.0.0.1']), ('game_is_running', False)]:
            patcher = mock.patch.object(gui, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.port = free_game_port()

    def make_app(self, who, role):
        import tkinter as tk
        docs = self.tmp / who / 'Documents'
        game = docs / 'Electronic Arts' / NBSP_GAME
        (game / 'Mods').mkdir(parents=True, exist_ok=True)
        (game / 'Mods' / 'Resource.cfg').write_text('')
        (game / 'Mods' / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        (game / 'saves').mkdir(exist_ok=True)
        app = gui.LauncherApp(tk.Toplevel(self.root), documents=docs)
        app._spawn = lambda worker: worker()
        app.role.set(role)
        app._on_role()
        app.port.set(str(self.port))
        return app, game / 'saves'

    def test_default_save_is_manual_and_auto_warns(self):
        host, saves = self.make_app('hote', gui.ROLE_HOST)
        make_save(saves / 'Slot_ffffffff.save', 'Sauvegarde automatique')          # la plus recente
        manual = make_save(saves / 'Slot_00000002.save', 'Partie jetable')
        os.utime(manual, (1_000_000, 1_000_000))
        host._refresh_saves()
        self.assertTrue(host.save_choice.get().startswith('Slot_00000002.save'))
        self.assertEqual(host.save_warning.cget('text'), '')
        host.save_box.current(1)
        host._update_save_warning()
        self.assertIn('Sauvegarde automatique (Slot_ffffffff)', host.save_warning.cget('text'))
        manual.unlink()                                                             # seule l'automatique
        host._refresh_saves()
        self.assertTrue(host.save_choice.get().startswith('Slot_ffffffff.save'))
        self.assertIn('préférez une partie sauvegardée à la main', host.save_warning.cget('text'))

    def test_host_refuses_guest(self):
        host, host_saves = self.make_app('hote', gui.ROLE_HOST)
        make_save(host_saves / 'Slot_00000002.save', 'Partie jetable', ['Jetable'])
        host._refresh_saves()
        host._create_room()
        host._poll_install()
        self.addCleanup(host._close_room)
        guest, guest_saves = self.make_app('invite', gui.ROLE_JOIN)
        before = snapshot(guest_saves)
        guest.ip.set('127.0.0.1')
        guest.room_code.set(host.room.code)
        guest.pseudo.set('Alex')
        with mock.patch.object(guest, '_confirm', return_value=True) as confirm:
            guest._join_room()
            guest._presence_tick()                                     # la demande arrive
            host._refresh_players()
            self.assertEqual(host.players_label.cget('text'), 'Aucun joueur accepté.')
            labels = [w.cget('text') for w in host.pending_frame.winfo_children()]
            self.assertIn('Alex · 127.0.0.1 · demande', labels)
            self.assertIn('Accepter', labels)
            self.assertIn('Refuser', labels)
            refuse = [w for w in host.pending_frame.winfo_children() if w.cget('text') == 'Refuser'][0]
            refuse.invoke()
            guest._presence_tick()
            guest._presence_tick()
        confirm.assert_not_called()
        self.assertIsNone(guest.presence)
        self.assertEqual(guest.status.cget('text'), 'Refusé par l\'hôte')
        self.assertEqual(snapshot(guest_saves), before)
        self.assertFalse((self.tmp / gui.BACKUP_DIR_NAME).exists())
        self.assertEqual(host.pending_frame.winfo_children(), [])


if __name__ == '__main__':
    unittest.main()
