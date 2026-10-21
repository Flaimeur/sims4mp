# Tests de l'aide (bouton « ? ») et du guide launcher/README.md.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_help.py -v

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402

HERE = Path(os.path.dirname(os.path.abspath(__file__)))


class HelpTest(unittest.TestCase):
    def test_help_is_short(self):
        self.assertLessEqual(len(gui.HELP_TEXT.splitlines()), 10)
        for word in ('mp.host', 'mp.join', 'Diagnostic', 'Restaurer', 'non affilié à EA'):
            self.assertIn(word, gui.HELP_TEXT)

    def test_help_button_shows_text(self):
        import tkinter as tk
        tmp = Path(tempfile.mkdtemp(prefix='sims4mp_help_'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with mock.patch.object(gui, 'base_dir', return_value=tmp), \
                mock.patch.object(gui, 'detect_game', return_value=gui.GameInstall(None, None)):
            app = gui.LauncherApp(root, documents=tmp)
        self.assertEqual(app.help_button.cget('text'), '?')
        with mock.patch('tkinter.messagebox.showinfo') as showinfo:
            app.help_button.invoke()
        showinfo.assert_called_once()
        self.assertEqual(showinfo.call_args.args[1], gui.HELP_TEXT)


class ReadmeTest(unittest.TestCase):
    def test_guide_covers_topics(self):
        text = (HERE / 'README.md').read_text(encoding='utf-8')
        for topic in ('Program Files', 'SmartScreen', 'Héberger', 'Rejoindre', 'Réseaux privés',
                      'Lancer Les Sims 4', 'Diagnostic', 'Restaurer', 'non affilié à Electronic Arts'):
            self.assertIn(topic, text)


if __name__ == '__main__':
    unittest.main()
