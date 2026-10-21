# Tests du bouton « Lancer Les Sims 4 ». Le jeu n'est jamais vraiment lance :
# os.startfile est remplace par un faux.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_launch.py -v

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402


class LaunchGameTest(unittest.TestCase):
    def test_launches_steam_url(self):
        started = []
        lines = gui.launch_game(is_running=lambda: False, start=started.append)
        self.assertEqual(started, ['steam://rungameid/1222670'])
        self.assertIn('Steam', lines[0])

    def test_refused_when_running(self):
        started = []
        with self.assertRaisesRegex(gui.LauncherError, 'deja lance'):
            gui.launch_game(is_running=lambda: True, start=started.append)
        self.assertEqual(started, [])


class LaunchWindowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_launch_test_'))
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = gui.LauncherApp(self.root, documents=self.tmp)

    def click_play(self, running):
        startfile = mock.Mock()
        # launch_game fige game_is_running et os.startfile comme valeurs par
        # defaut : on la remplace par un appel explicite avec les faux.
        real = gui.launch_game
        with mock.patch.object(gui.threading, 'Thread') as thread, \
                mock.patch.object(gui, 'launch_game',
                                  lambda: real(is_running=lambda: running, start=startfile)):
            self.app._launch_game()
            self.assertEqual(str(self.app.play_button.cget('state')), 'disabled')
            thread.call_args.kwargs['target']()          # execute le travail sans thread
        self.app._poll_install()
        return startfile

    def test_button_launches(self):
        startfile = self.click_play(running=False)
        startfile.assert_called_once_with('steam://rungameid/1222670')
        self.assertEqual(self.app.status.cget('text'), 'Jeu lancé via Steam')
        self.assertEqual(str(self.app.play_button.cget('state')), 'normal')

    def test_button_refused_when_running(self):
        startfile = self.click_play(running=True)
        startfile.assert_not_called()
        self.assertEqual(str(self.app.status.cget('style')), 'StatusError.TLabel')
        self.assertIn('deja lance', self.app.status.cget('text'))


class LogoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_logo_test_'))
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'Electronic Arts').mkdir()
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    # sims4mp_assets.py (image d'EA) n'est pas dans le depot : test ignore sur une copie fraiche.
    @unittest.skipUnless((Path(__file__).resolve().parent / 'sims4mp_assets.py').is_file(),
                         'sims4mp_assets.py absent (non publie)')
    def test_embedded_plumbob_loads(self):
        app = gui.LauncherApp(self.root, documents=self.tmp)
        self.assertIsNotNone(app.logo_image)
        self.assertEqual((app.logo_image.width(), app.logo_image.height()), (26, 50))

    def test_fallback_to_drawn_logo(self):
        with mock.patch.dict(sys.modules, {'sims4mp_assets': None}):     # import impossible
            app = gui.LauncherApp(self.root, documents=self.tmp)
        self.assertIsNone(app.logo_image)
        self.assertIn('losange dessine', (self.tmp / gui.LOG_NAME).read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
