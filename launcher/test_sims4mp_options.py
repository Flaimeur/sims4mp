# Tests de la page OPTIONS (depot GitHub). Aucun acces reseau : le test du
# manifeste passe par un faux opener. Fichiers dans des dossiers temporaires.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_options.py -v

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402
from test_sims4mp_update import FakeOpener, json_bytes, manifest_for, mod_bytes  # noqa: E402


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_options_test_'))
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)


class RepoTagTest(unittest.TestCase):
    def test_repo(self):
        for ok in ['Flaimeur/sims4mp', 'a/b', ' user-1/my.repo_2 ']:
            self.assertEqual(gui.validate_repo(ok), ok.strip())
        for bad in ['', 'sims4mp', 'a/b/c', '../x', 'a/..', 'a/.', '-a/b', 'a b/c',
                    'https://github.com/a/b', 'a/b?token=1', 'a\\b', 'a/b#x', 'é/b']:
            with self.assertRaises(ValueError, msg=bad):
                gui.validate_repo(bad)

    def test_tag(self):
        for ok in ['', 'v0.4.0', '0.4.1-test', 'release_1']:
            self.assertEqual(gui.validate_tag(ok), ok)
        for bad in ['..', '.', 'v1/2', '../v1', 'v 1', 'v1?x', 'a' * 65]:
            with self.assertRaises(ValueError, msg=bad):
                gui.validate_tag(bad)

    def test_manifest_url(self):
        self.assertEqual(gui.manifest_url_for('Flaimeur/sims4mp'),
                         'https://github.com/Flaimeur/sims4mp/releases/latest/download/sims4mp_manifest.json')
        self.assertEqual(gui.manifest_url_for('Flaimeur/sims4mp', 'v0.4.0'),
                         'https://github.com/Flaimeur/sims4mp/releases/download/v0.4.0/sims4mp_manifest.json')
        gui.require_https(gui.manifest_url_for('a/b', 'v1'))

    def test_effective_url_fallback(self):
        self.assertEqual(gui.effective_manifest_url(None), gui.MANIFEST_URL)
        self.assertIn('/releases/download/v1/', gui.effective_manifest_url({'depot': 'a/b', 'tag': 'v1'}))


class ConfigFileTest(TempDirTest):
    def test_write_and_read(self):
        path = gui.config_path()
        self.assertIsNone(gui.read_config(path))
        gui.write_config(path, {'depot': ' Flaimeur/sims4mp ', 'tag': 'v0.4.0'})
        self.assertEqual(gui.read_config(path), {'depot': 'Flaimeur/sims4mp', 'tag': 'v0.4.0'})
        self.assertEqual(set(json.loads(path.read_text(encoding='utf-8'))), {'depot', 'tag'})
        self.assertEqual([p.name for p in self.tmp.iterdir()], [gui.CONFIG_NAME])

    def test_invalid_refused_and_old_kept(self):
        path = gui.config_path()
        gui.write_config(path, {'depot': 'a/b', 'tag': ''})
        for bad in [{'depot': 'a', 'tag': ''}, {'depot': 'a/b', 'tag': '../x'},
                    {'depot': 'a/b', 'tag': '', 'token': 'secret'}, {'depot': 'a/b'}]:
            with self.assertRaises(ValueError, msg=bad):
                gui.write_config(path, bad)
        self.assertEqual(gui.read_config(path), {'depot': 'a/b', 'tag': ''})

    def test_invalid_files(self):
        path = gui.config_path()
        for content in ['pas du json', '[]', '{"depot": "a/b", "tag": "", "token": "x"}',
                        '{"depot": "a/b/c", "tag": ""}', '{"depot": 1, "tag": ""}']:
            path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError, msg=content):
                gui.read_config(path)


class OptionsWindowTest(TempDirTest):
    def make_app(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir(exist_ok=True)
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        return gui.LauncherApp(root, documents=self.tmp)

    def test_save_and_reload(self):
        app = self.make_app()
        self.assertEqual(app.tag_mode.get(), 'latest')
        self.assertIn('disabled', app.tag_entry.state())
        self.assertEqual(app._manifest_url(), gui.MANIFEST_URL)
        app.repo.set('Flaimeur/sims4mp')
        app.tag_mode.set('tag')
        app._on_tag_mode()
        self.assertNotIn('disabled', app.tag_entry.state())
        app.tag.set('v0.4.0')
        self.assertIn('/releases/download/v0.4.0/', app.manifest_preview.cget('text'))
        app._save_config()
        self.assertEqual(str(app.status.cget('style')), 'StatusOk.TLabel')
        app2 = self.make_app()
        self.assertEqual((app2.repo.get(), app2.tag_mode.get(), app2.tag.get()),
                         ('Flaimeur/sims4mp', 'tag', 'v0.4.0'))
        self.assertEqual(app2._manifest_url(), gui.manifest_url_for('Flaimeur/sims4mp', 'v0.4.0'))

    def test_invalid_input_not_saved(self):
        app = self.make_app()
        app.repo.set('https://github.com/a/b')
        app._save_config()
        self.assertFalse(gui.config_path().exists())
        self.assertEqual(str(app.status.cget('style')), 'StatusError.TLabel')
        app.repo.set('a/b')
        app.tag_mode.set('tag')
        app.tag.set('')
        app._save_config()
        self.assertFalse(gui.config_path().exists())
        self.assertIn('Tag manquant', app.status.cget('text'))

    def test_latest_mode_ignores_tag_field(self):
        app = self.make_app()
        app.repo.set('a/b')
        app.tag.set('v9')
        app._save_config()
        self.assertEqual(gui.read_config(gui.config_path()), {'depot': 'a/b', 'tag': ''})

    def test_check_manifest(self):
        app = self.make_app()
        app.repo.set('a/b')
        data = mod_bytes('0.4.0')
        url = gui.manifest_url_for('a/b')
        opener = FakeOpener({url: json_bytes(manifest_for(data, version='0.4.0', statut='test'))})
        with mock.patch.object(gui, 'make_https_opener', return_value=opener), \
                mock.patch.object(gui.threading, 'Thread') as thread:
            app._check_manifest()
            thread.call_args.kwargs['target']()          # execute le travail sans thread
        app._poll_install()
        self.assertEqual(opener.requested, [url])
        self.assertEqual(app.status.cget('text'), 'Manifeste valide (0.4.0, test)')
        self.assertEqual(str(app.check_button.cget('state')), 'normal')

    def test_check_manifest_error(self):
        app = self.make_app()
        app.repo.set('a/b')
        with mock.patch.object(gui, 'make_https_opener', return_value=FakeOpener({})), \
                mock.patch.object(gui.threading, 'Thread') as thread:
            app._check_manifest()
            thread.call_args.kwargs['target']()
        app._poll_install()
        self.assertEqual(str(app.status.cget('style')), 'StatusError.TLabel')

    def test_update_uses_saved_repo(self):
        gui.write_config(gui.config_path(), {'depot': 'a/b', 'tag': 'v1'})
        app = self.make_app()
        with mock.patch.object(gui, 'run_update', return_value=(['ok'], 'ok')) as run:
            app._update_worker()
        self.assertEqual(run.call_args.args[0], gui.manifest_url_for('a/b', 'v1'))


if __name__ == '__main__':
    unittest.main()
