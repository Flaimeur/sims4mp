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
        # Comme get_resource_key : un entier est pris tel quel, un nom est hache.
        self.instance = name if isinstance(name, int) else abs(hash(name)) % (2 ** 63)
        self.type = kind


PACKAGE_KEYS = set()                                  # (type, instance) des .package installes


resources = module('sims4.resources', Types=types.SimpleNamespace(INTERACTION='INTERACTION', PNG=0x2F7D0004,
                                                                  DDS=0x00B2D882),
                   get_resource_key=lambda name, kind: Key(name, kind),
                   does_key_exist=lambda key: (key.type, key.instance) in PACKAGE_KEYS)


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


class TestList(tuple):
    """Comme event_testing.tests.TestList : run_tests renvoie TRUE si tous les tests passent."""

    def run_tests(self, resolver, skip_safe_tests=False, search_for_tooltip=False):
        for test in self:
            result = test(resolver)
            if not result:
                return result
        return TestResult.TRUE


module('event_testing.tests', TestList=TestList)
BASE_TESTS_FAIL = TestList((lambda resolver: TestResult(False),))


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

    tests = BASE_TESTS_FAIL                           # tests regles de la base : echouent ici
    test_globals = BASE_TESTS_FAIL
    allow_while_save_locked = False
    _tunable_tests_enabled = staticmethod(lambda: True)

    @classmethod
    def _test(cls, *args, **kwargs):
        return TestResult(False)

    @classmethod
    def test(cls, target=None, context=None):
        # Resume d'Interaction.test (bytecode) : _test, puis si _tunable_tests_enabled()
        # test_globals et tests ; sinon target_result n'existe pas (UnboundLocalError).
        result = cls._test(target, context)
        if cls._tunable_tests_enabled():
            target_result = cls.test_globals.run_tests(None, False, search_for_tooltip=True)
            target_result = target_result and cls.tests.run_tests(None, False, search_for_tooltip=True)
        if not result:
            return result
        return target_result


module('interactions')
module('interactions.base')
module('interactions.base.immediate_interaction', ImmediateSuperInteraction=ImmediateSuperInteraction)


class PickerSuperInteractionMixin(object):
    pass


module('interactions.base.picker_interaction', PickerSuperInteractionMixin=PickerSuperInteractionMixin)


class ChoiceMenu(object):
    """Comme interactions.choices.ChoiceMenu : add_potential_aops appelle add_aop."""

    def __init__(self):
        self.items = []

    def __iter__(self):
        return iter([(n, types.SimpleNamespace(aop=aop)) for n, aop in enumerate(self.items)])

    def add_potential_aops(self, target, context, potential_aops, scoring_gsi_handler=None):
        for aop in potential_aops:
            self.add_aop(aop, context, user_pick_target=target)

    def add_aop(self, aop, context, user_pick_target=None, result_override=None, do_test=True):
        result = aop.affordance.test(aop.target, context)
        if result:
            self.items.append(aop)
        return result


module('interactions.choices', ChoiceMenu=ChoiceMenu)


class ProtocolBufferRollback(object):
    """Comme distributor.rollback.ProtocolBufferRollback : retire l'element et avale l'erreur."""

    def __init__(self, items):
        self.items = items

    def __enter__(self):
        self.items.append('bouton')
        return self.items[-1]

    def __exit__(self, exc_type, value, tb):
        if exc_type is not None:
            del self.items[-1]
        return True


module('distributor')
module('distributor.rollback', ProtocolBufferRollback=ProtocolBufferRollback)
module('distributor.shared_messages',
       IconInfoData=lambda icon_resource=None, **kwargs: types.SimpleNamespace(icon_resource=icon_resource))


def create_pie_menu_message(items, fail):
    with ProtocolBufferRollback(items):
        if fail:
            raise TypeError('nom du bouton impossible')


def game_pie_message(sim, choice_menu, reference_id=0, drop_guid=None):
    """Comme interaction_commands.create_pie_menu_message : un item par aop du menu."""
    items = [types.SimpleNamespace(affordance_id=item.aop.affordance.guid64, loc_string='nom',
                                   pie_menu_priority=0)
             for _, item in choice_menu if item.aop.affordance.guid64 != drop_guid]
    return types.SimpleNamespace(items=items)


module('server_commands')
module('server_commands.interaction_commands', create_pie_menu_message=game_pie_message)


class TravelWithPicker(PickerSuperInteractionMixin, ImmediateSuperInteraction):
    # Comme « Voyager avec » : selecteur, sa roue liste des Sims (vide = cachee).
    pass


class DebugCategory(object):
    guid64 = 999                                      # sous-menu « … » de la roue


class TerrainTeleportCheat(ImmediateSuperInteraction):
    cheat = True
    category = DebugCategory
    category_on_forwarded = DebugCategory


class GoHere(object):
    pass


class TerrainClass(object):
    _super_affordances = (GoHere, TravelWithPicker, TerrainTeleportCheat)


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
report('sans categorie : premier niveau de la roue (la base est dans un sous-menu)',
       TerrainTeleportCheat.category is DebugCategory and menu.category is None
       and menu.category_on_forwarded is None)
report('selecteur ignore comme base ; visible meme sauvegarde verrouillee',
       not issubclass(menu, TravelWithPicker) and menu.allow_while_save_locked is True)
try:
    menu_test = menu.test()
    menu_test_error = ''
except Exception as exc:                              # 0.14.1 : UnboundLocalError ici
    menu_test, menu_test_error = None, repr(exc)
report('test du jeu reussi malgre les tests regles de la base, sans erreur',
       bool(menu_test) and menu._tunable_tests_enabled() is True and not TerrainTeleportCheat.test(),
       menu_test_error)
report('enregistree aupres du gestionnaire avec sa propre cle',
       MANAGER.registered and MANAGER.registered[0][0] is menu and menu.guid64 == MANAGER.registered[0][1].instance
       and menu.guid64 != TerrainTeleportCheat.guid64)
report('ajoutee a la roue du sol', TerrainClass._super_affordances[-1] is menu
       and TerrainClass._super_affordances[:3] == (GoHere, TravelWithPicker, TerrainTeleportCheat))
mod._safe_on_zone_loaded()                            # deuxieme chargement
report('deuxieme chargement : ni recreee ni ajoutee deux fois',
       len(MANAGER.registered) == 1 and TerrainClass._super_affordances.count(menu) == 1)

# --- 1b. Diagnostic de la roue (Maj + clic) -------------------------------------------
pie = ChoiceMenu()
shift = types.SimpleNamespace(shift_held=True)
aops = [types.SimpleNamespace(affordance=a, target=TERRAIN) for a in (TerrainTeleportCheat, menu)]
pie.add_potential_aops(TERRAIN, shift, aops)
pie.add_potential_aops(TERRAIN, shift, aops)          # meme situation : notee une seule fois
with open(mod.LOG_PATH, encoding='utf-8') as handle:
    diag = [line for line in handle if 'menu (roue)' in line]
report('roue : entree proposee et acceptee, raison notee une seule fois dans le journal',
       pie.items.count(aops[1]) == 2 and len(diag) == 2 and 'presente parmi les 2' in diag[0]
       and 'test du jeu : OK' in diag[1], str(diag))
ChoiceMenu().add_potential_aops(TERRAIN, types.SimpleNamespace(shift_held=False), aops[:1])
with open(mod.LOG_PATH, encoding='utf-8') as handle:
    report('roue sans Maj : rien de note', sum('menu (roue)' in line for line in handle) == 2)
buttons = []
create_pie_menu_message(buttons, fail=False)
create_pie_menu_message(buttons, fail=True)
with ProtocolBufferRollback([]):
    raise ValueError('hors de la roue')
with open(mod.LOG_PATH, encoding='utf-8') as handle:
    text = handle.read()
report('bouton retire par le jeu : erreur avalee notee avec sa trace (roue seulement)',
       buttons == ['bouton'] and 'bouton retire par le jeu' in text and 'nom du bouton impossible' in text
       and 'hors de la roue' not in text)
commands_module = sys.modules['server_commands.interaction_commands']
commands_module.create_pie_menu_message(None, pie)
commands_module.create_pie_menu_message(None, pie, 0, drop_guid=menu.guid64)
with open(mod.LOG_PATH, encoding='utf-8') as handle:
    text = handle.read()
report('message final : presence du bouton Sims4MP notee (present puis absent)',
       getattr(commands_module.create_pie_menu_message, '_sims4mp_hook', False)
       and 'Sims4MP present (nom' in text and 'Sims4MP ABSENT' in text)

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
shown = len(DIALOGS)
mod.mp_menu()
report('commande mp.menu : ouvre la meme fenetre',
       len(DIALOGS) == shown + 1 and DIALOGS[-1].title == 'Sims4MP'
       and [r.text() for r in DIALOGS[-1].responses] == labels)

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

# --- 4b. Icone de la roue (sims4mp_icons.package) -----------------------------------------
import icon_package  # noqa: E402

with open(mod.LOG_PATH, encoding='utf-8') as handle:
    text = handle.read()
report('sans sims4mp_icons.package : bouton sans icone, journal explicite',
       menu.pie_menu_icon is None and 'icone absente' in text and mod.bridge_menu_icon() is None)
PACKAGE_KEYS.add((0x2F7D0004, icon_package.ICON_INSTANCE))     # ancien .package (0.16.0, PNG)
report('ancien .package a image PNG : ignore (elle s\'affichait en lama)', mod.bridge_menu_icon() is None)
PACKAGE_KEYS.add((icon_package.DDS_TYPE, icon_package.ICON_INSTANCE))
with_icon = mod.bridge_create_menu_affordance()
icon = with_icon.pie_menu_icon('resolver')
report('avec sims4mp_icons.package : le bouton montre l\'image DDS du fichier',
       mod.MENU_ICON_INSTANCE == icon_package.ICON_INSTANCE and icon.icon_resource.type == 0x00B2D882
       and icon.icon_resource.instance == icon_package.ICON_INSTANCE)
PACKAGE_KEYS.clear()

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
