# Tests du lanceur fenetre. Aucun acces au vrai dossier Mods ni aux vraies
# sauvegardes : tout se passe dans des dossiers temporaires.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_launcher_gui.py -v

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_test_'))
        # launcher.log va dans le dossier temporaire, pas dans launcher/.
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)


class PortTest(unittest.TestCase):
    def test_valid(self):
        for value, expected in [('1024', 1024), ('7777', 7777), (' 65535 ', 65535), (8080, 8080)]:
            self.assertEqual(gui.validate_port(value), expected)

    def test_invalid(self):
        for value in ['', 'abc', '1023', '65536', '0', '-1', '7777.0', '7 777', '１２３４', '1e4', True, 70000]:
            with self.assertRaises(ValueError, msg=repr(value)):
                gui.validate_port(value)


class IpTest(unittest.TestCase):
    def test_valid(self):
        for value in ['192.168.1.20', ' 10.0.0.5 ', '127.0.0.1', '25.10.200.3']:
            self.assertEqual(gui.validate_ipv4(value), value.strip())

    def test_invalid(self):
        for value in ['', '   ', '192.168.1', '192.168.1.256', '192.168.01.2', 'abc', '::1',
                      '192.168.1.20:7777', '0.0.0.0', '255.255.255.255', '224.0.0.1', 'localhost']:
            with self.assertRaises(ValueError, msg=repr(value)):
                gui.validate_ipv4(value)


class SettingsTest(TempDirTest):
    def setUp(self):
        super().setUp()
        (self.tmp / 'Electronic Arts').mkdir()
        self.path = gui.settings_path(self.tmp)

    def test_missing_file(self):
        self.assertIsNone(gui.read_settings(self.path))

    def test_write_and_read_join(self):
        written = gui.write_settings(self.path, {'role': 'join', 'ip': ' 192.168.1.20 ', 'port': 7777})
        self.assertEqual(written, {'role': 'join', 'ip': '192.168.1.20', 'port': 7777})
        self.assertEqual(gui.read_settings(self.path), written)
        # Uniquement role, ip, port ; aucun fichier temporaire restant.
        self.assertEqual(set(json.loads(self.path.read_text(encoding='utf-8'))), {'role', 'ip', 'port'})
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ['sims4mp_settings.json'])

    def test_write_host_without_ip(self):
        gui.write_settings(self.path, {'role': 'host', 'ip': '', 'port': 1024})
        self.assertEqual(gui.read_settings(self.path), {'role': 'host', 'ip': '', 'port': 1024})

    def test_overwrite(self):
        gui.write_settings(self.path, {'role': 'host', 'ip': '', 'port': 7777})
        gui.write_settings(self.path, {'role': 'join', 'ip': '10.0.0.2', 'port': 9000})
        self.assertEqual(gui.read_settings(self.path)['port'], 9000)

    def test_write_refuses_invalid_and_keeps_old(self):
        gui.write_settings(self.path, {'role': 'host', 'ip': '', 'port': 7777})
        for bad in [{'role': 'join', 'ip': '', 'port': 7777},
                    {'role': 'host', 'ip': '', 'port': 80},
                    {'role': 'admin', 'ip': '', 'port': 7777},
                    {'role': 'host', 'ip': '', 'port': 7777, 'save': 'x'}]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                gui.write_settings(self.path, bad)
        self.assertEqual(gui.read_settings(self.path)['port'], 7777)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_read_invalid_files(self):
        for content in ['pas du json', '[]', '{"role": "join", "ip": "1.2.3", "port": 7777}',
                        '{"role": "host", "ip": "", "port": "7777"}',
                        '{"role": "host", "ip": "", "port": 7777, "extra": 1}',
                        '{"role": "host", "port": 7777}']:
            self.path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError, msg=content):
                gui.read_settings(self.path)

    def test_write_requires_ea_folder(self):
        with self.assertRaises(gui.LauncherError):
            gui.write_settings(gui.settings_path(self.tmp / 'absent'), {'role': 'host', 'ip': '', 'port': 7777})


def make_mod(path, version='0.4.0'):
    # Faux .ts4script : un zip avec un "pyc" contenant la chaine marshal de la version.
    payload = b'\x00' * 16 + b'\xda' + bytes([len(version)]) + version.encode() + b'\x00' * 64
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('sims4mp_hello.pyc', payload)
    return path


class InstallTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.documents = self.tmp / 'Documents'
        self.mods = self.documents / 'Electronic Arts' / 'Les Sims 4' / 'Mods'
        self.mods.mkdir(parents=True)
        (self.mods / 'Resource.cfg').write_text('Priority 500\n')
        self.source = make_mod(self.tmp / gui.MOD_FILE)
        self.backups = self.tmp / gui.BACKUP_DIR_NAME

    def install(self, running=False):
        return gui.run_install(self.source, self.documents, self.backups, is_running=lambda: running)

    def test_fresh_install(self):
        lines = self.install()
        target = self.mods / gui.MOD_FILE
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(target.stat().st_mtime, self.source.stat().st_mtime)
        self.assertFalse(self.backups.exists())
        self.assertIn('Version du mod installe : 0.4.0', lines)

    def test_backup_of_previous_mod(self):
        old = make_mod(self.mods / gui.MOD_FILE, '0.3.0')
        old_bytes = old.read_bytes()
        self.install()
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.source.read_bytes())
        # Deux installations dans la meme seconde : pas d'ecrasement de sauvegarde.
        self.install()
        self.assertEqual(len(list(self.backups.iterdir())), 2)

    def test_refuses_when_game_running(self):
        old = make_mod(self.mods / gui.MOD_FILE, '0.3.0').read_bytes()
        with self.assertRaisesRegex(gui.LauncherError, 'Fermez Les Sims 4'):
            self.install(running=True)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), old)
        self.assertFalse(self.backups.exists())

    def test_no_mods_folder(self):
        (self.mods / 'Resource.cfg').unlink()
        with self.assertRaisesRegex(gui.LauncherError, '0 trouve'):
            self.install()
        self.assertFalse((self.mods / gui.MOD_FILE).exists())

    def test_two_mods_folders(self):
        other = self.documents / 'Electronic Arts' / 'The Sims 4' / 'Mods'
        other.mkdir(parents=True)
        (other / 'Resource.cfg').write_text('')
        with self.assertRaisesRegex(gui.LauncherError, '2 trouve'):
            self.install()
        self.assertFalse((self.mods / gui.MOD_FILE).exists())
        self.assertFalse((other / gui.MOD_FILE).exists())

    def test_corrupted_copy_detected(self):
        def bad_copy(src, dst):
            Path(dst).write_bytes(b'X' * Path(src).stat().st_size)   # meme taille, contenu faux
        with mock.patch.object(gui.shutil, 'copy2', bad_copy):
            with self.assertRaisesRegex(gui.LauncherError, 'SHA-256'):
                self.install()

    def test_warns_about_other_copy(self):
        sub = self.mods / 'ancien'
        sub.mkdir()
        make_mod(sub / 'sims4mp_hello_0.3.0.ts4script', '0.3.0')
        lines = self.install()
        self.assertTrue(any(l.startswith('ATTENTION') for l in lines))


class WindowTest(TempDirTest):
    def test_window_save_and_reload(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        app.role.set('join')
        app._on_role()
        app.ip.set('192.168.1.999')
        app._save()
        self.assertFalse(gui.settings_path(self.tmp).exists())
        self.assertIn('Adresse IP invalide', app.messages.get('1.0', 'end'))
        app.ip.set('192.168.1.42')
        app.port.set('99999')
        app._save()
        self.assertFalse(gui.settings_path(self.tmp).exists())
        app.port.set('8000')
        app._save()
        app2 = gui.LauncherApp(tk.Toplevel(root), documents=self.tmp)
        self.assertEqual((app2.role.get(), app2.ip.get(), app2.port.get()), ('join', '192.168.1.42', '8000'))
        self.assertIn('ERREUR', (self.tmp / gui.LOG_NAME).read_text(encoding='utf-8-sig'))

    def test_window_ignores_invalid_settings(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        gui.settings_path(self.tmp).write_text('{"role": "join", "ip": "x", "port": 1}', encoding='utf-8')
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        self.assertEqual((app.role.get(), app.port.get()), ('host', str(gui.DEFAULT_PORT)))
        self.assertIn('Reglage ignore', app.messages.get('1.0', 'end'))


class DisplayTest(TempDirTest):
    def make_app(self, ips):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir(exist_ok=True)
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with mock.patch.object(gui, 'local_ipv4_addresses', return_value=ips):
            return gui.LauncherApp(root, documents=self.tmp)

    def test_ip_labels_and_primary(self):
        self.assertEqual(gui.ip_label('192.168.1.20'), 'Wi-Fi/Ethernet')
        self.assertEqual(gui.ip_label('192.168.147.1'), 'Virtuel')
        self.assertEqual(gui.ip_label('192.168.49.1'), 'Virtuel')
        self.assertEqual(gui.ip_label('10.0.0.5'), 'inconnu')
        self.assertEqual(gui.primary_ip(['192.168.147.1', '10.0.0.5', '192.168.1.20']), '10.0.0.5')
        self.assertIsNone(gui.primary_ip(['192.168.49.1']))
        self.assertIsNone(gui.primary_ip([]))

    def test_window_builds(self):
        import tkinter.font as tkfont
        app = self.make_app(['192.168.147.1', '192.168.1.20'])
        style = app.ttk.Style(app.root)
        self.assertIn(style.theme_use(), ('vista', 'clam'))
        self.assertEqual(tkfont.nametofont('TkDefaultFont', root=app.root).actual('size'), 10)
        self.assertEqual(str(app.messages.cget('state')), 'disabled')
        self.assertEqual(app.status.cget('text'), 'Prêt')
        # Une ligne par IP, l'IP principale est celle sans etiquette Virtuel.
        lines = [[w.cget('text') for w in f.winfo_children()] for f in app.ip_list.winfo_children()]
        self.assertEqual(lines, [['192.168.147.1', 'Virtuel'],
                                 ['192.168.1.20', 'Wi-Fi/Ethernet  · principale']])
        # Champ IP desactive en mode Heberger, actif en mode Rejoindre.
        self.assertIn('disabled', app.ip_entry.state())
        app.role.set('join')
        app._on_role()
        self.assertNotIn('disabled', app.ip_entry.state())

    def test_copy_and_status(self):
        app = self.make_app(['192.168.147.1', '192.168.1.20'])
        app._copy_ips()
        self.assertEqual(app.root.clipboard_get(), '192.168.1.20')
        self.assertEqual(str(app.status.cget('style')), 'StatusOk.TLabel')
        app.port.set('80')
        app._save()
        self.assertEqual(str(app.status.cget('style')), 'StatusError.TLabel')
        self.assertTrue(app.status.cget('text').startswith('Port invalide'))

    def test_no_primary_ip_disables_copy(self):
        app = self.make_app(['192.168.49.1'])
        self.assertIn('disabled', app.copy_button.state())


if __name__ == '__main__':
    unittest.main()
