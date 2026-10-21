# Tests du lanceur sur macOS, simules depuis Windows : fonctions Mac appelees
# avec de fausses commandes, dossiers temporaires imitant ~/Library et
# /Applications, et module recharge avec sys.platform = 'darwin'.
# Aucune commande Mac reelle n'est lancee, le jeu n'est jamais ouvert.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_mac.py -v

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402

GUI_FILE = Path(gui.__file__)


def load_as_mac():
    """Charge une copie du module comme sur un Mac (sans toucher a gui)."""
    spec = importlib.util.spec_from_file_location('sims4mp_launcher_gui_mac', GUI_FILE)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, 'platform', 'darwin'):
        spec.loader.exec_module(module)
    return module


class MacModuleTest(unittest.TestCase):
    def setUp(self):
        self.mac = load_as_mac()

    def test_mac_functions_selected(self):
        mac = self.mac
        self.assertTrue(mac.IS_MAC)
        self.assertFalse(mac.IS_WINDOWS)
        self.assertEqual(mac.GAME_PROCESS, 'The Sims 4')
        self.assertIs(mac.game_is_running, mac.game_is_running_mac)
        self.assertIs(mac.detect_game, mac.detect_game_mac)
        self.assertIs(mac.listening_pids, mac.listening_pids_mac)
        self.assertIs(mac.process_name, mac.process_name_mac)
        self.assertIs(mac.firewall_profiles, mac.firewall_profiles_mac)
        self.assertEqual((mac.FONT_FAMILY, mac.MONO_FAMILY), ('Helvetica Neue', 'Menlo'))
        # Valeurs par defaut figees a la definition : les versions Mac.
        self.assertIs(mac.launch_game.__defaults__[0], mac.game_is_running_mac)
        self.assertIs(mac.run_restore.__defaults__[0], mac.game_is_running_mac)
        defaults = mac.run_diagnostic.__defaults__
        self.assertIs(defaults[0], mac.game_is_running_mac)
        self.assertEqual(defaults[2:5], (mac.listening_pids_mac, mac.process_name_mac,
                                         mac.firewall_profiles_mac))

    def test_windows_untouched(self):
        self.assertEqual(gui.GAME_PROCESS, 'TS4_x64.exe')
        self.assertEqual(gui.FONT_FAMILY, 'Segoe UI')
        self.assertIsNot(gui.detect_game, gui.detect_game_mac)

    def test_documents_is_home(self):
        with mock.patch.object(self.mac.Path, 'home', return_value=Path('/Users/alex')):
            self.assertEqual(self.mac.documents_dir(), Path('/Users/alex/Documents'))

    def test_frozen_data_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix='sims4mp_mac_'))
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(self.mac.Path, 'home', return_value=tmp), \
                mock.patch.object(self.mac.sys, 'frozen', True, create=True):
            folder = self.mac.base_dir()
        self.assertEqual(folder, tmp / 'Library' / 'Application Support' / 'Sims4MP')
        self.assertTrue(folder.is_dir())

    def test_open_path_uses_open(self):
        with mock.patch.object(self.mac.subprocess, 'Popen') as popen:
            self.mac.open_path(Path('/Applications/The Sims 4.app'))
            self.mac.launch_game(is_running=lambda: False)
        self.assertEqual(popen.call_args_list, [mock.call(['open', str(Path('/Applications/The Sims 4.app'))]),
                                                mock.call(['open', gui.STEAM_GAME_URL])])

    def test_launch_refused_when_running(self):
        with mock.patch.object(self.mac.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(self.mac.LauncherError, r'deja lance \(The Sims 4 en cours'):
                self.mac.launch_game(is_running=lambda: True)
        popen.assert_not_called()

    def test_decode_console_without_oem(self):
        self.assertEqual(self.mac.decode_console('é'.encode('latin-1')), 'é')
        self.assertEqual(self.mac.decode_console('État'.encode('utf-8')), 'État')

    def test_diagnostic_recognises_game(self):
        tmp = Path(tempfile.mkdtemp(prefix='sims4mp_mac_diag_'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'Electronic Arts').mkdir()
        self.mac.write_settings(self.mac.settings_path(tmp), {'role': 'host', 'ip': '', 'port': 7777})
        lines, summary = self.mac.run_diagnostic(
            tmp, is_running=lambda: True, list_ips=lambda: ['192.168.1.20'],
            listeners=lambda port: [42], proc_name=lambda pid: 'The Sims 4',
            firewall=lambda: [('macOS', 'activé')], probe=None)
        self.assertIn('Port 7777 : ecoute par Les Sims 4 (mp.host actif)', lines)
        self.assertIn('Pare-feu, macOS : activé', lines)


class MacCommandsTest(unittest.TestCase):
    def test_game_is_running(self):
        calls = []

        def fake(code):
            def run(args, capture_output):
                calls.append(args)
                return subprocess.CompletedProcess(args, code, b'', b'')
            return run
        self.assertTrue(gui.game_is_running_mac(run=fake(0)))
        self.assertFalse(gui.game_is_running_mac(run=fake(1)))
        with self.assertRaisesRegex(gui.LauncherError, 'pgrep a echoue'):
            gui.game_is_running_mac(run=fake(3))
        self.assertEqual(calls[0], ['pgrep', '-f', 'The Sims 4.app/Contents/MacOS/'])

    def test_listening_pids(self):
        seen = []

        def run(args, ok_codes):
            seen.append((args, ok_codes))
            return 'p412\nfcwd\np99\np412\n'
        self.assertEqual(gui.listening_pids_mac(7777, run=run), [412, 99])
        self.assertEqual(seen, [(['lsof', '-nP', '-iTCP:7777', '-sTCP:LISTEN', '-Fp'], (0, 1))])
        self.assertEqual(gui.listening_pids_mac(7777, run=lambda args, ok_codes: ''), [])
        with self.assertRaises(ValueError):
            gui.listening_pids_mac('7777; rm', run=run)

    def test_process_name(self):
        out = '/Applications/The Sims 4.app/Contents/MacOS/The Sims 4\n'
        self.assertEqual(gui.process_name_mac(42, run=lambda args, ok_codes: out), 'The Sims 4')
        self.assertEqual(gui.process_name_mac(42, run=lambda args, ok_codes: '\n'), 'PID 42')

    def test_firewall(self):
        cases = [('Firewall is enabled. (State = 1)\n', [('macOS', 'activé')]),
                 ('Firewall is disabled. (State = 0)\n', [('macOS', 'désactivé')]),
                 ('Firewall is blocking all non-essential incoming connections. (State = 2)', [('macOS', 'activé')]),
                 ('Firewall is enabled.\n', [('macOS', 'activé')]),
                 ('???', [])]
        for output, expected in cases:
            self.assertEqual(gui.firewall_profiles_mac(run=lambda args: output), expected, output)


class MacDetectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_mac_detect_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / 'Users' / 'alex'
        self.applications = self.tmp / 'Applications'
        self.applications.mkdir(parents=True)
        self.steam = self.home / 'Library' / 'Application Support' / 'Steam'

    def detect(self):
        return gui.detect_game_mac(home=self.home, applications=self.applications)

    def steam_game(self, library, installdir='The Sims 4', app=gui.MAC_GAME_APP):
        (library / 'steamapps').mkdir(parents=True, exist_ok=True)
        (library / 'steamapps' / 'appmanifest_1222670.acf').write_text(
            '"AppState"\n{{\n\t"installdir"\t\t"{}"\n}}\n'.format(installdir), encoding='utf-8')
        path = library / 'steamapps' / 'common' / installdir / app
        path.mkdir(parents=True)
        return path

    def test_nothing(self):
        self.assertEqual(self.detect(), gui.GameInstall(None, None))

    def test_steam_default_library(self):
        app = self.steam_game(self.steam)
        self.assertEqual(self.detect(), gui.GameInstall('steam', app))
        self.assertEqual(gui.game_target(self.detect()), gui.STEAM_GAME_URL)

    def test_steam_other_library(self):
        other = self.tmp / 'Volumes' / 'Jeux' / 'SteamLibrary'
        (self.steam / 'steamapps').mkdir(parents=True)
        (self.steam / 'steamapps' / 'libraryfolders.vdf').write_text(
            '"libraryfolders"\n{{\n\t"1"\n\t{{\n\t\t"path"\t\t"{}"\n\t}}\n}}\n'.format(other.as_posix()),
            encoding='utf-8')
        app = self.steam_game(other, app='Les Sims 4.app')         # nom d'app different : accepte
        self.assertEqual(self.detect(), gui.GameInstall('steam', app))

    def test_steam_before_ea(self):
        (self.applications / gui.MAC_GAME_APP).mkdir()
        app = self.steam_game(self.steam)
        self.assertEqual(self.detect().kind, 'steam')
        self.assertEqual(self.detect().exe, app)

    def test_ea_applications(self):
        app = self.applications / gui.MAC_GAME_APP
        app.mkdir()
        self.assertEqual(self.detect(), gui.GameInstall('ea', app))
        self.assertEqual(gui.game_target(self.detect()), str(app))

    def test_ea_user_applications(self):
        app = self.home / 'Applications' / gui.MAC_GAME_APP
        app.mkdir(parents=True)
        self.assertEqual(self.detect(), gui.GameInstall('ea', app))

    def test_hostile_installdir_ignored(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        (self.steam / 'steamapps' / 'appmanifest_1222670.acf').write_text(
            '"installdir"\t"../../../../Applications"\n', encoding='utf-8')
        (self.applications / 'Autre.app').mkdir()
        self.assertEqual(self.detect(), gui.GameInstall(None, None))

    def test_app_file_not_folder_ignored(self):
        (self.applications / gui.MAC_GAME_APP).write_text('')
        self.assertEqual(self.detect(), gui.GameInstall(None, None))


if __name__ == '__main__':
    unittest.main()
