# Tests de la phase 1 : restauration de l'ancien mod, detection du jeu,
# diagnostic, ouverture du journal. Tout se passe dans des dossiers
# temporaires ; registre, netstat, netsh, reseau et lancement sont simules.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_phase1.py -v

import io
import os
import shutil
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402

NBSP_GAME = 'Les Sims 4'


def mod_bytes(version):
    payload = b'\x00' * 16 + b'\xda' + bytes([len(version)]) + version.encode() + b'\x00' * 64
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('sims4mp_hello.pyc', payload)
    return buffer.getvalue()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_phase1_'))
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.documents = self.tmp / 'Documents'
        self.mods = self.documents / 'Electronic Arts' / NBSP_GAME / 'Mods'
        self.mods.mkdir(parents=True)
        (self.mods / 'Resource.cfg').write_text('Priority 500\n')
        self.backups = self.tmp / gui.BACKUP_DIR_NAME
        self.backups.mkdir()


# --- 1a Restauration ---------------------------------------------------------------

class RestoreTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.current = mod_bytes('0.4.0')
        (self.mods / gui.MOD_FILE).write_bytes(self.current)
        self.old = mod_bytes('0.3.0')
        self.older = mod_bytes('0.2.0')
        (self.backups / 'sims4mp_hello_20261020_101500.ts4script').write_bytes(self.old)
        (self.backups / 'sims4mp_hello_20261019_090000.ts4script').write_bytes(self.older)

    def test_list_backups(self):
        (self.backups / 'notes.txt').write_text('x')
        (self.backups / 'sims4mp_hello_x.ts4script').write_bytes(self.old)
        (self.backups / 'sims4mp_hello_20261021_120000.ts4script').mkdir()       # dossier, ignore
        (self.backups / 'sims4mp_hello_20261020_101500_2.ts4script').write_bytes(self.old)
        names = [p.name for p in gui.list_backups(self.backups)]
        self.assertEqual(names, ['sims4mp_hello_20261020_101500_2.ts4script',
                                 'sims4mp_hello_20261020_101500.ts4script',
                                 'sims4mp_hello_20261019_090000.ts4script'])
        self.assertEqual(gui.list_backups(self.tmp / 'absent'), [])

    def test_label(self):
        label = gui.backup_label(self.backups / 'sims4mp_hello_20261020_101500.ts4script')
        self.assertEqual(label, '20/10/2026 10:15:00 · version 0.3.0 · {} octets'.format(len(self.old)))

    def test_restore_puts_old_back_and_saves_current(self):
        chosen = self.backups / 'sims4mp_hello_20261020_101500.ts4script'
        lines, summary = gui.run_restore(chosen, self.documents, self.backups, is_running=lambda: False)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.old)
        self.assertEqual(summary, 'Ancien mod restauré (0.3.0)')
        saved = [p for p in gui.list_backups(self.backups) if p.read_bytes() == self.current]
        self.assertEqual(len(saved), 1)                      # le mod remplace est sauvegarde
        self.assertEqual(chosen.read_bytes(), self.old)      # la sauvegarde choisie reste
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), ['Resource.cfg', gui.MOD_FILE])

    def test_refused_when_game_running(self):
        before = sorted(p.name for p in self.backups.iterdir())
        with self.assertRaisesRegex(gui.LauncherError, 'Fermez Les Sims 4'):
            gui.run_restore(self.backups / 'sims4mp_hello_20261020_101500.ts4script',
                            self.documents, self.backups, is_running=lambda: True)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.current)
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), before)

    def test_refuses_files_outside_backups(self):
        elsewhere = self.tmp / 'ailleurs'
        elsewhere.mkdir()
        outside = elsewhere / 'sims4mp_hello_20261020_101500.ts4script'
        outside.write_bytes(self.old)
        renamed = self.backups / 'mon_mod.ts4script'
        renamed.write_bytes(self.old)
        traversal = self.backups / '..' / 'ailleurs' / 'sims4mp_hello_20261020_101500.ts4script'
        for bad in [outside, renamed, traversal, self.backups / 'sims4mp_hello_20990101_000000.ts4script']:
            with self.assertRaisesRegex(gui.LauncherError, 'Sauvegarde invalide', msg=str(bad)):
                gui.run_restore(bad, self.documents, self.backups, is_running=lambda: False)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.current)

    def test_refuses_non_zip(self):
        junk = self.backups / 'sims4mp_hello_20261018_000000.ts4script'
        junk.write_bytes(b'pas un zip')
        with self.assertRaisesRegex(gui.LauncherError, 'illisible'):
            gui.run_restore(junk, self.documents, self.backups, is_running=lambda: False)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.current)

    def test_identical_backup_does_nothing(self):
        same = self.backups / 'sims4mp_hello_20261021_080000.ts4script'
        same.write_bytes(self.current)
        before = sorted(p.name for p in self.backups.iterdir())
        lines, summary = gui.run_restore(same, self.documents, self.backups, is_running=lambda: False)
        self.assertTrue(summary.startswith('Déjà en place'))
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), before)

    def test_copy_failure_keeps_current_mod(self):
        real_copy2 = shutil.copy2

        def failing_copy(src, dst):
            if str(dst).endswith('.part'):
                Path(dst).write_bytes(b'partiel')
                raise OSError('disque plein')
            return real_copy2(src, dst)
        with mock.patch.object(gui.shutil, 'copy2', failing_copy):
            with self.assertRaises(OSError):
                gui.run_restore(self.backups / 'sims4mp_hello_20261020_101500.ts4script',
                                self.documents, self.backups, is_running=lambda: False)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.current)
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), ['Resource.cfg', gui.MOD_FILE])


# --- 1b Detection du jeu ---------------------------------------------------------

class DetectGameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_detect_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_reg(self, values):
        return lambda hive, key, name: values.get((hive, key, name))

    def make_exe(self, folder):
        exe = folder / 'Game' / 'Bin' / gui.GAME_PROCESS
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'MZ')
        return exe

    def make_steam(self, game_in_second_library=True, installdir='The Sims 4'):
        root = self.tmp / 'Steam'
        second = self.tmp / 'Jeux Steam'
        (root / 'steamapps').mkdir(parents=True)
        (second / 'steamapps').mkdir(parents=True)
        (root / 'steamapps' / 'libraryfolders.vdf').write_text(
            '"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{}"\n\t}}\n\t"1"\n\t{{\n\t\t"path"\t\t"{}"\n\t}}\n}}\n'
            .format(str(root).replace('\\', '\\\\'), str(second).replace('\\', '\\\\')), encoding='utf-8')
        library = second if game_in_second_library else root
        (library / 'steamapps' / 'appmanifest_1222670.acf').write_text(
            '"AppState"\n{{\n\t"appid"\t\t"1222670"\n\t"installdir"\t\t"{}"\n}}\n'.format(
                installdir.replace('\\', '\\\\')), encoding='utf-8')
        exe = self.make_exe(library / 'steamapps' / 'common' / 'The Sims 4')
        reg = self.fake_reg({('HKCU', r'Software\Valve\Steam', 'SteamPath'): str(root).replace('\\', '/')})
        return reg, exe, second

    def test_steam_second_library(self):
        reg, exe, second = self.make_steam()
        self.assertIn(second, gui.steam_libraries(reg))
        self.assertEqual(gui.detect_game(reg), gui.GameInstall('steam', exe))

    def test_steam_bad_installdir_ignored(self):
        reg, exe, second = self.make_steam(installdir='..\\..\\Windows')
        self.assertEqual(gui.detect_game(reg).kind, None)

    def test_ea_app(self):
        exe = self.make_exe(self.tmp / 'EA Games' / 'The Sims 4')
        reg = self.fake_reg({('HKLM', r'SOFTWARE\Maxis\The Sims 4', 'Install Dir'): str(self.tmp / 'EA Games' / 'The Sims 4') + '\\'})
        self.assertEqual(gui.detect_game(reg), gui.GameInstall('ea', exe))

    def test_maxis_key_inside_steam_library_is_steam(self):
        reg, exe, second = self.make_steam()
        (second / 'steamapps' / 'appmanifest_1222670.acf').unlink()          # sans manifeste Steam
        values = {('HKCU', r'Software\Valve\Steam', 'SteamPath'): str(self.tmp / 'Steam'),
                  ('HKLM', r'SOFTWARE\WOW6432Node\Maxis\The Sims 4', 'Install Dir'): str(exe.parent.parent.parent)}
        self.assertEqual(gui.detect_game(self.fake_reg(values)), gui.GameInstall('steam', exe))

    def test_not_found(self):
        self.assertEqual(gui.detect_game(self.fake_reg({})), gui.GameInstall(None, None))
        values = {('HKLM', r'SOFTWARE\Maxis\The Sims 4', 'Install Dir'): str(self.tmp / 'supprime')}
        self.assertEqual(gui.detect_game(self.fake_reg(values)).kind, None)

    def test_targets(self):
        self.assertEqual(gui.game_target(gui.GameInstall('steam', Path('x'))), gui.STEAM_GAME_URL)
        ea = gui.GameInstall('ea', self.tmp / 'TS4_x64.exe')
        self.assertEqual(gui.game_target(ea), str(self.tmp / 'TS4_x64.exe'))
        started = []
        gui.launch_game(is_running=lambda: False, start=started.append, target=gui.game_target(ea))
        self.assertEqual(started, [str(self.tmp / 'TS4_x64.exe')])


# --- 1c Diagnostic -------------------------------------------------------------------

NETSTAT = '''
Connexions actives

  Proto  Adresse locale         Adresse distante       Etat
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1768
  TCP    0.0.0.0:7777           0.0.0.0:0              LISTENING       4242
  TCP    0.0.0.0:17777          0.0.0.0:0              LISTENING       5000
  TCP    192.168.1.20:7777      192.168.1.30:51000     ESTABLISHED     4242
  TCP    [::]:7777              [::]:0                 LISTENING       4242
'''

NETSH_FR = '''
Paramètres Profil de domaine :
----------------------------------------------------------------------
État                                  Actif

Paramètres Profil privé :
----------------------------------------------------------------------
État                                  Actif

Paramètres Profil public :
----------------------------------------------------------------------
État                                  Inactif
Ok.
'''

NETSH_EN = '''
Domain Profile Settings:
----------------------------------------------------------------------
State                                 ON

Private Profile Settings:
----------------------------------------------------------------------
State                                 OFF
Ok.
'''


class ParsersTest(unittest.TestCase):
    def test_listening_pids(self):
        self.assertEqual(gui.listening_pids(7777, run=lambda args: NETSTAT), [4242])
        self.assertEqual(gui.listening_pids(8888, run=lambda args: NETSTAT), [])
        calls = []
        gui.listening_pids(7777, run=lambda args: calls.append(args) or '')
        self.assertEqual(calls, [['netstat', '-ano', '-p', 'TCP']])      # arguments fixes
        with self.assertRaises(ValueError):
            gui.listening_pids('7777; calc', run=lambda args: '')

    def test_process_name(self):
        out = '"TS4_x64.exe","4242","Console","1","2 000 000 Ko"\r\n'
        self.assertEqual(gui.process_name(4242, run=lambda args: out), 'TS4_x64.exe')
        self.assertEqual(gui.process_name(1, run=lambda args: 'INFO: aucune tache'), 'PID 1')

    def test_decode_console(self):
        text = 'Paramètres Profil privé :'
        self.assertEqual(gui.decode_console(text.encode('utf-8')), text)       # netsh recent
        self.assertEqual(gui.decode_console(text.encode('cp850')), text)       # page OEM
        self.assertEqual(gui.firewall_profiles(run=lambda a: gui.decode_console(NETSH_FR.encode('utf-8')))[1],
                         ('Paramètres Profil privé', 'Actif'))

    def test_firewall_french_and_english(self):
        self.assertEqual(gui.firewall_profiles(run=lambda a: NETSH_FR),
                         [('Paramètres Profil de domaine', 'Actif'), ('Paramètres Profil privé', 'Actif'),
                          ('Paramètres Profil public', 'Inactif')])
        self.assertEqual(gui.firewall_profiles(run=lambda a: NETSH_EN),
                         [('Domain Profile Settings', 'ON'), ('Private Profile Settings', 'OFF')])

    def test_tcp_probe(self):
        class Sock:
            closed = False

            def close(self):
                Sock.closed = True
        seen = []

        def ok(address, timeout):
            seen.append((address, timeout))
            return Sock()
        self.assertEqual(gui.tcp_probe('192.168.1.20', 7777, connect=ok), (True, 'Joignable'))
        self.assertEqual(seen, [(('192.168.1.20', 7777), 3)])
        self.assertTrue(Sock.closed)
        for error in (ConnectionRefusedError(), socket.timeout(), OSError('injoignable')):
            def fail(address, timeout, error=error):
                raise error
            self.assertEqual(gui.tcp_probe('192.168.1.20', 7777, connect=fail), (False, gui.JOIN_HELP))
        self.assertEqual(gui.tcp_probe('pas une ip', 7777, connect=ok), (False, gui.JOIN_HELP))


class DiagnosticTest(TempDirTest):
    def settings(self, role, ip='', port=7777):
        (self.documents / 'Electronic Arts' / gui.SETTINGS_NAME).write_text(
            '{{"role": "{}", "ip": "{}", "port": {}}}'.format(role, ip, port), encoding='utf-8')

    def run_diag(self, listeners=lambda port: [], names=None, probe=None):
        self.probed = []

        def fake_probe(ip, port):
            self.probed.append((ip, port))
            return probe if probe else (True, 'Joignable')
        return gui.run_diagnostic(
            self.documents, is_running=lambda: False, list_ips=lambda: ['192.168.1.20'],
            listeners=listeners, proc_name=lambda pid: (names or {}).get(pid, 'autre.exe'),
            firewall=lambda: [('Profil privé', 'Actif')], probe=fake_probe)

    def test_host_port_free(self):
        (self.mods / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.settings('host')
        lines, summary = self.run_diag()
        text = '\n'.join(lines)
        self.assertIn('Mod : present, version 0.4.0', text)
        self.assertIn('Jeu : ferme', text)
        self.assertIn('Reglage : Heberger, IP -, port 7777', text)
        self.assertIn('IP locales : 192.168.1.20', text)
        self.assertIn('Port 7777 : libre', text)
        self.assertIn('Pare-feu, Profil privé : Actif', text)
        self.assertEqual(self.probed, [])                       # pas de test TCP en mode Heberger
        self.assertEqual(summary, 'Diagnostic : tout est en ordre')

    def test_host_port_taken(self):
        (self.mods / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.settings('host')
        lines, summary = self.run_diag(listeners=lambda port: [99], names={99: 'serveur.exe'})
        self.assertIn('ATTENTION : port 7777 deja utilise par serveur.exe (PID 99)', lines)
        self.assertEqual(summary, 'Diagnostic : 1 point(s) à vérifier')
        lines, summary = self.run_diag(listeners=lambda port: [42], names={42: 'TS4_x64.exe'})
        self.assertIn('Port 7777 : ecoute par Les Sims 4 (mp.host actif)', lines)

    def test_join_reachable(self):
        (self.mods / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.settings('join', '192.168.1.30', 8000)
        lines, summary = self.run_diag()
        self.assertEqual(self.probed, [('192.168.1.30', 8000)])
        self.assertIn('Hote 192.168.1.30:8000 : Joignable', lines)

    def test_join_unreachable_help(self):
        (self.mods / gui.MOD_FILE).write_bytes(mod_bytes('0.4.0'))
        self.settings('join', '192.168.1.30', 8000)
        lines, summary = self.run_diag(probe=(False, gui.JOIN_HELP))
        self.assertIn('ATTENTION : hote 192.168.1.30:8000 : le port ne répond pas : vérifiez que le host '
                      'a lancé mp.host et que le pare-feu autorise le réseau privé', lines)
        self.assertIn('à vérifier', summary)

    def test_missing_mod_and_settings(self):
        lines, summary = self.run_diag()
        text = '\n'.join(lines)
        self.assertIn('ATTENTION : mod absent du dossier Mods', text)
        self.assertIn('ATTENTION : aucun reglage enregistre', text)
        self.assertEqual(self.probed, [])
        self.assertEqual(summary, 'Diagnostic : 2 point(s) à vérifier')


# --- Fenetre -----------------------------------------------------------------------

class WindowTest(TempDirTest):
    def make_app(self, game):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)

        def no_network(*args, **kwargs):
            raise AssertionError('aucun acces reseau au demarrage')
        with mock.patch.object(gui, 'detect_game', return_value=game), \
                mock.patch.object(gui.socket, 'create_connection', no_network):
            return gui.LauncherApp(root, documents=self.documents)

    def run_task(self, app, action):
        with mock.patch.object(gui.threading, 'Thread') as thread:
            action()
            if thread.call_args:
                thread.call_args.kwargs['target']()
        app._poll_install()

    def test_game_status_and_play_button(self):
        app = self.make_app(gui.GameInstall(None, None))
        self.assertEqual(app.game_status.cget('text'), 'Jeu : introuvable')
        self.assertEqual(str(app.play_button.cget('state')), 'disabled')
        self.assertIn('Jeu introuvable', app.play_hint.cget('text'))
        self.assertEqual(app.status.cget('text'), 'Prêt')
        app = self.make_app(gui.GameInstall('steam', self.tmp / 'TS4_x64.exe'))
        self.assertEqual(app.game_status.cget('text'), 'Jeu : Steam')
        self.assertEqual(str(app.play_button.cget('state')), 'normal')
        self.assertEqual(app.play_hint.cget('text'), '')

    def test_ea_launch_uses_detected_exe(self):
        exe = self.tmp / 'EA' / 'TS4_x64.exe'
        app = self.make_app(gui.GameInstall('ea', exe))
        self.assertEqual(app.game_status.cget('text'), 'Jeu : EA app')
        calls = []

        def fake_launch(target=gui.STEAM_GAME_URL):
            calls.append(target)
            return ['ok']
        with mock.patch.object(gui, 'launch_game', fake_launch):
            self.run_task(app, app._launch_game)
        self.assertEqual(calls, [str(exe)])
        self.assertEqual(app.status.cget('text'), 'Jeu lancé via EA app')

    def test_restore_from_window(self):
        current, old = mod_bytes('0.4.0'), mod_bytes('0.3.0')
        (self.mods / gui.MOD_FILE).write_bytes(current)
        (self.backups / 'sims4mp_hello_20261020_101500.ts4script').write_bytes(old)
        app = self.make_app(gui.GameInstall(None, None))
        self.assertEqual(len(app.backup_box.cget('values')), 1)
        self.assertEqual(str(app.restore_button.cget('state')), 'normal')
        with mock.patch.object(app, '_confirm', return_value=False):
            self.run_task(app, app._restore)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), current)     # annule
        # run_restore fige game_is_running comme valeur par defaut : on passe un faux.
        real = gui.run_restore
        with mock.patch.object(app, '_confirm', return_value=True), \
                mock.patch.object(gui, 'run_restore',
                                  lambda b, d, bd: real(b, d, bd, is_running=lambda: False)):
            self.run_task(app, app._restore)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), old)
        self.assertEqual(app.status.cget('text'), 'Ancien mod restauré (0.3.0)')
        self.assertEqual(len(app.backup_box.cget('values')), 2)               # liste rafraichie

    def test_no_backup_disables_restore(self):
        app = self.make_app(gui.GameInstall(None, None))
        self.assertEqual(app.backup_box.cget('values'), '')
        self.assertEqual(str(app.restore_button.cget('state')), 'disabled')

    def test_diagnostic_button(self):
        app = self.make_app(gui.GameInstall('steam', self.tmp / 'x.exe'))
        with mock.patch.object(gui, 'run_diagnostic', return_value=(['Jeu : ferme'], 'Diagnostic : tout est en ordre')):
            self.run_task(app, app._diagnostic)
        self.assertEqual(app.status.cget('text'), 'Diagnostic : tout est en ordre')
        self.assertIn('Jeu : ferme', app.messages.get('1.0', 'end'))

    def test_open_log(self):
        app = self.make_app(gui.GameInstall(None, None))
        with mock.patch.object(gui.os, 'startfile') as startfile:
            app._open_log()
        startfile.assert_called_once_with(str(self.tmp / gui.LOG_NAME))
        self.assertTrue((self.tmp / gui.LOG_NAME).exists())


if __name__ == '__main__':
    unittest.main()
