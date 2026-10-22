# Sims 4 Multiplayer - test hors jeu du menu Sims4MP (roue Maj + clic sur le sol)
# et des niveaux de notifications. Compatible Python 3.7.
# A lancer avec :  py -3.7 test_menu.py
#
# Faux modules du jeu : gestionnaire d'instances (types, TYPE, register_tuned_class),
# metaclasse de reglage, sol (terrain_service), fenetre UiDialog / UiDialogResponse.

import os
import shutil
import sys
import tempfile
import time
import types


def module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class _CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        _CheatOutput.lines.append(text)


commands = module('sims4.commands', Command=lambda *a, **k: (lambda f: f),
                  CommandType=types.SimpleNamespace(Live='Live'), CheatOutput=_CheatOutput)


class Key(object):
    def __init__(self, name, kind):
        self.instance, self.type = abs(hash(name)) % (2 ** 63), kind


resources = module('sims4.resources', Types=types.SimpleNamespace(INTERACTION='INTERACTION'),
                   get_resource_key=lambda name, kind: Key(name, kind))


class RawText(str):
    pass


localization = module('sims4.localization',
                      LocalizationHelperTuning=types.SimpleNamespace(get_raw_text=lambda text: RawText(text)))
module('sims4', commands=commands, resources=resources, localization=localization)


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)


class TestResult(object):
    def __init__(self, result, reason=None):
        self.result = result

    def __bool__(self):
        return self.result


TestResult.TRUE = TestResult(True)
module('event_testing')
module('event_testing.results', TestResult=TestResult)


class TunedMeta(type):
    """Comme HashedTunedInstanceMetaclass : les sous-classes heritent des reglages."""
    created = []

    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        TunedMeta.created.append(cls)
        return cls


class ImmediateSuperInteraction(object, metaclass=TunedMeta):
    cheat = False
    debug = False
    allow_user_directed = True
    allow_autonomous = True
    visible = True
    guid64 = 111

    @classmethod
    def _test(cls, *args, **kwargs):
        return TestResult(False)


module('interactions')
module('interactions.base')
module('interactions.base.immediate_interaction', ImmediateSuperInteraction=ImmediateSuperInteraction)


class TerrainTeleportCheat(ImmediateSuperInteraction):
    cheat = True


class GoHere(object):
    pass


class TerrainClass(object):
    _super_affordances = (GoHere, TerrainTeleportCheat)


TERRAIN = TerrainClass()


class Manager(object):
    TYPE = 'INTERACTION'

    def __init__(self):
        self.types = {1: TerrainTeleportCheat}
        self.registered = []

    def register_tuned_class(self, instance, key):
        self.registered.append((instance, key))


MANAGER = Manager()
DIALOGS = []


class UiDialogResponse(object):
    UiDialogUiRequest = types.SimpleNamespace(NO_REQUEST=0)

    def __init__(self, dialog_response_id=None, text=None, ui_request=None):
        self.dialog_response_id, self.text, self.ui_request = dialog_response_id, text, ui_request


class FakeDialog(object):
    def __init__(self, owner, text, title):
        self.owner, self.text, self.title = owner, text(), title()
        self.responses = ()
        self.response = None
        self.listener = None
        DIALOGS.append(self)

    def set_responses(self, responses):
        self.responses = tuple(responses)

    def show_dialog(self, on_response=None):
        self.listener = on_response

    def click(self, response_id):
        self.response = response_id
        self.listener(self)


class UiDialog(object):
    @staticmethod
    def TunableFactory():
        return types.SimpleNamespace(default=lambda owner, text, title: FakeDialog(owner, text, title))


module('ui')
module('ui.ui_dialog', UiDialog=UiDialog, UiDialogResponse=UiDialogResponse)

CLIENT = types.SimpleNamespace(active_sim='Elise')
module('services', get_instance_manager=lambda kind: MANAGER,
       terrain_service=types.SimpleNamespace(terrain_object=lambda: TERRAIN),
       client_manager=lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT))

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import sims4mp_hello as mod  # noqa: E402

results = []
notes = []
mod.show_notification = lambda title, text, *args: notes.append(text)
TMP = tempfile.mkdtemp(prefix='sims4mp_menu_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')
mod._mods_dir = TMP


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


# --- 1. Creation et ajout a la roue du sol --------------------------------------------
mod._safe_on_zone_loaded()                            # fin de chargement d'une partie
menu = mod._menu['affordance']
report('action « Sims4MP… » creee a partir d\'une action immediate du sol',
       menu is not None and issubclass(menu, TerrainTeleportCheat) and type(menu) is TunedMeta, str(mod._menu))
report('reglages : roue Maj + clic, choisie par le joueur, jamais par l\'autonomie, nom affiche',
       menu.cheat is True and menu.debug is False and menu.allow_user_directed and not menu.allow_autonomous
       and menu.visible and menu.display_name() == 'Sims4MP…' and isinstance(menu.display_name(), RawText))
report('tests du jeu contournes (toujours disponible)', bool(menu._test(None, None)))
report('enregistree aupres du gestionnaire avec sa propre cle',
       MANAGER.registered and MANAGER.registered[0][0] is menu and menu.guid64 == MANAGER.registered[0][1].instance
       and menu.guid64 != TerrainTeleportCheat.guid64)
report('ajoutee a la roue du sol', TerrainClass._super_affordances[-1] is menu
       and TerrainClass._super_affordances[:2] == (GoHere, TerrainTeleportCheat))
mod._safe_on_zone_loaded()                            # deuxieme chargement
report('deuxieme chargement : ni recreee ni ajoutee deux fois',
       len(MANAGER.registered) == 1 and TerrainClass._super_affordances.count(menu) == 1)

# --- 2. La fenetre ----------------------------------------------------------------------
result = menu()._run_interaction_gen(None)
try:
    next(result)
    finished = False
except StopIteration as stop:
    finished = stop.value is True
dialog = DIALOGS[-1] if DIALOGS else None
labels = [r.text() for r in dialog.responses] if dialog else []
report('cliquer « Sims4MP… » ouvre une fenetre du jeu avec un bouton par choix',
       finished and dialog is not None and dialog.title == 'Sims4MP' and dialog.owner == 'Elise'
       and labels == [label for _, label in mod.MENU_CHOICES]
       and all(r.ui_request == 0 for r in dialog.responses), str(labels))

# --- 3. Niveaux de notifications ----------------------------------------------------------
del notes[:]
dialog.click(2)
report('« importantes seulement » : choisi et confirme', mod._notify['level'] == 'important'
       and notes == ['Notifications : importantes seulement.'])
del notes[:]
mod.bridge_notify('L\'autre joueur contrôle Alex.', important=False)
mod.bridge_notify('Connexion à l\'hôte perdue.')
report('niveau « important » : notifications secondaires masquees, importantes affichees',
       notes == ['Connexion à l\'hôte perdue.'] and mod._notify['hidden'] == 1)
mod.open_menu()
DIALOGS[-1].click(3)
mod.bridge_notify('Connexion à l\'hôte perdue.')
report('niveau « aucune » : plus rien', mod._notify['level'] == 'rien' and notes == ['Connexion à l\'hôte perdue.'])
mod.open_menu()
DIALOGS[-1].click(1)
mod.bridge_notify('L\'autre joueur contrôle Alex.', important=False)
report('niveau « toutes » : tout revient', notes[-1] == 'L\'autre joueur contrôle Alex.')

# --- 4. Etat de la partie et jouer seul -------------------------------------------------
mod._auto['target'] = ('join', '192.168.1.200', 7777)
mod.open_menu()
DIALOGS[-1].click(4)
state = DIALOGS[-1]
report('« État de la partie » : fenetre de resume', state.title == 'État de la partie'
       and 'Connexion automatique prévue : invité vers 192.168.1.200.' in state.text, state.text)
mod.open_menu()
DIALOGS[-1].click(5)
report('« Jouer seul » : connexion automatique arretee', mod._auto['target'] is None and mod._session is None)
count = len(DIALOGS)
mod.open_menu()
DIALOGS[-1].click(6)
report('« Fermer » : rien d\'autre', len(DIALOGS) == count + 1)

# --- 5. Erreur pendant la creation : le jeu continue ---------------------------------------
mod._menu['affordance'] = None
TerrainClass._super_affordances = (GoHere,)
MANAGER.types = {}
mod._safe_on_zone_loaded()
report('aucune action immediate disponible : erreur journalisee, aucune exception',
       mod._menu['affordance'] is None and 'aucune action immediate' in (mod._menu['error'] or ''))

shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
