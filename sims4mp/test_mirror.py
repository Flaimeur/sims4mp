# Sims 4 Multiplayer - test hors jeu de la simulation unique (0.20.0).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_mirror.py
#
# Faux modules du jeu : omega (send), services (client, zone, ligne du temps, Sims),
# scheduling.Timeline, clock.GameClock, SimSpawnerService, interaction_commands.cancel_common,
# InteractionQueue, TestResult, Consts_pb2. Les sessions sont simulees (pas de reseau).

import base64
import os
import shutil
import sys
import tempfile
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
module('sims4', commands=commands)


class _Zone(object):
    is_zone_running = True

    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)

SENT = []                                            # appels de l'omega.send d'origine


def _omega_send(session_id, msg_id, data):
    SENT.append((session_id, msg_id, data))


module('omega', send=_omega_send)


class Timeline(object):
    def __init__(self, name):
        self.name = name
        self.runs = 0

    def simulate(self, until, max_elements=None, max_time_ms=None):
        self.runs += 1
        return 'simule'


module('scheduling', Timeline=Timeline)


class GameClock(object):
    broadcasts = 0

    def _sync_clock_and_broadcast_gameclock(self, immediate=False):
        GameClock.broadcasts += 1
        return 'heure envoyee'


module('clock', GameClock=GameClock)


class SimSpawnerService(object):
    updates = 0

    def update(self):
        SimSpawnerService.updates += 1
        return 'pnj'


module('sims')
module('sims.sim_spawner_service', SimSpawnerService=SimSpawnerService)
LOCAL_CANCELS = []


def cancel_common(interaction_id, context_handle=None, _connection=None, user_canceled=False):
    LOCAL_CANCELS.append(interaction_id)
    return 'annulee ici'


module('server_commands')
GENERATED = []                                       # menus calcules par la fausse commande du jeu


class ChoiceMenu(object):
    revision_counter = 40

    def __init__(self, sim, reference_id):
        ChoiceMenu.revision_counter += 1
        self.revision = ChoiceMenu.revision_counter
        self.sim, self.reference_id, self.selected = sim, reference_id, None

    def select(self, choice_id):
        self.selected = choice_id
        return 'action lancee'


def generate_choices(target_id, pick_type, x, y, z, lot_id, level, control, alt, shift, reference_id,
                     referred_object_id=0, preferred_object_id=0, is_routable=True, _connection=None):
    commands_module = sys.modules['server_commands.interaction_commands']
    client = sys.modules['services'].client_manager().get_first_client()
    sim = commands_module._active_sim(client)          # comme le jeu : Sim acteur par _active_sim(client)
    GENERATED.append(('pie', sim, target_id, reference_id, x, shift, _connection))
    client.set_choices(ChoiceMenu(sim, reference_id))


def generate_phone_choices(control, alt, shift, reference_id, selected_affordance_id=None, _connection=None):
    commands_module = sys.modules['server_commands.interaction_commands']
    client = sys.modules['services'].client_manager().get_first_client()
    sim = commands_module._active_sim(client)
    GENERATED.append(('phone', sim, reference_id, _connection))
    client.set_choices(ChoiceMenu(sim, reference_id))


LOCAL_SELECTS = []


def select_choice(choice_id, reference_id=None, _connection=None):
    LOCAL_SELECTS.append((choice_id, reference_id))


module('server_commands.interaction_commands', cancel_common=cancel_common, generate_choices=generate_choices,
       generate_phone_choices=generate_phone_choices, select_choice=select_choice,
       _active_sim=lambda client: 'Sim actif de l\'hote')


class TestResult(object):
    def __init__(self, ok, reason=None):
        self.ok = ok
        self.reason = reason

    def __bool__(self):
        return self.ok


module('event_testing')
module('event_testing.results', TestResult=TestResult)


class InteractionQueue(object):
    def __init__(self, sim):
        self.sim = sim
        self.items = []

    def append(self, interaction):
        self.items.append(interaction)
        return TestResult(True)


module('interactions')
module('interactions.interaction_queue', InteractionQueue=InteractionQueue)
module('protocolbuffers')
module('protocolbuffers.Consts_pb2', MSG_OBJECTS_VIEW_UPDATE=11, MSG_UI_DIALOG_SHOW=40,
       MSG_UI_NOTIFICATION_SHOW=41, MSG_CONNECTION_STATUS_CONNECTED=210, MSG_SIM_MOOD_UPDATE=159,
       MSG_PIE_MENU_CREATE=6, MSG_PHONE_MENU_CREATE=171)


class _PieMessage(object):
    """Faux PieMenuCreate : octets « sim:reference »."""

    def ParseFromString(self, data):
        sim, reference = data.decode('ascii').split(':')
        self.sim, self.client_reference_id = int(sim), int(reference)


module('protocolbuffers.InteractionOps_pb2', PieMenuCreate=_PieMessage)


class _DialogMessage(object):
    """Faux UiDialogMessage : octets « dialog_id:owner_id »."""

    def ParseFromString(self, data):
        dialog_id, owner_id = data.decode('ascii').split(':')
        self.dialog_id, self.owner_id = int(dialog_id), int(owner_id)


module('protocolbuffers.Dialog_pb2', UiDialogMessage=_DialogMessage)


class UiDialogService(object):
    def __init__(self):
        self.known = {}
        self.calls = []

    def get_dialog(self, dialog_id):
        return self.known.get(dialog_id)

    def dialog_respond(self, dialog_id, response, client=None):
        self.calls.append(('respond', dialog_id, response, client))
        return True

    def dialog_pick_result(self, dialog_id, picked_results=(), ingredient_check=False,
                           prepped_ingredient_check=False, recipe_id=None):
        self.calls.append(('pick', dialog_id, tuple(picked_results), ingredient_check, prepped_ingredient_check,
                           recipe_id))
        return True

    def dialog_text_input(self, dialog_id, text_input_name, text_input_value):
        self.calls.append(('text', dialog_id, text_input_name, text_input_value))


DIALOGS = UiDialogService()
module('ui')
module('ui.ui_dialog_service', UiDialogService=UiDialogService)
resources = module('sims4.resources', Types=types.SimpleNamespace(INTERACTION='INTERACTION'))
sys.modules['sims4'].resources = resources


class InteractionContext(object):
    SOURCE_PIE_MENU, SOURCE_AUTONOMY, SOURCE_SCRIPT, SOURCE_SCRIPT_WITH_USER_INTENT = 'pie', 'auto', 's', 'su'

    def __init__(self, sim, source, priority):
        self.sim, self.source, self.priority = sim, source, priority


module('interactions.context', InteractionContext=InteractionContext)
module('interactions.priority', Priority=types.SimpleNamespace(High='haute', Low='basse'))
module('objects', ALL_HIDDEN_REASONS='tous')


class _Played(object):
    interaction = 'mixer rejoue'

    def __bool__(self):
        return True


class AffordanceObjectPair(object):
    made = []

    def __init__(self, affordance, target, sa, si):
        AffordanceObjectPair.made.append((affordance, target, sa, si))

    def test_and_execute(self, context):
        AffordanceObjectPair.made.append(('contexte', context.source, context.priority))
        return _Played()


module('interactions.aop', AffordanceObjectPair=AffordanceObjectPair)


class Distributor(object):
    shown = []

    def add_object(self, obj):
        Distributor.shown.append(('ajout', obj.id))

    def remove_object(self, obj):
        Distributor.shown.append(('retrait', obj.id))


module('distributor')
module('distributor.system', Distributor=Distributor)
OBJECTS = {}


class ObjectManager(object):
    def add(self, obj):
        OBJECTS[obj.id] = obj
        Distributor().add_object(obj)

    def remove(self, obj):
        OBJECTS.pop(obj.id, None)
        Distributor().remove_object(obj)

    def get(self, obj_id):
        return OBJECTS.get(obj_id)


MANAGER = ObjectManager()


class GameObject(object):
    is_sim = False

    def __init__(self, obj_id, def_id, position=(1.0, 0.0, 2.0)):
        self.id = obj_id
        self.definition = types.SimpleNamespace(id=def_id)
        vector = types.SimpleNamespace(x=position[0], y=position[1], z=position[2])
        self.transform = types.SimpleNamespace(translation=vector,
                                               orientation=types.SimpleNamespace(x=0.0, y=0.7071, z=0.0, w=0.7071))
        self.level = 0
        self.moved = None

    def move_to(self, **kwargs):
        self.moved = kwargs


CREATED = []


def create_object(definition, obj_id=0, **kwargs):
    CREATED.append((definition, obj_id))
    if definition == 666:
        return None
    obj = GameObject(obj_id, definition)
    MANAGER.add(obj)
    return obj


BB_CALLS = []                                        # appels des fonctions du jeu (construction)


def c_api_create_object(zone_id, def_id, obj_id, obj_state=None, loc_type=1, content_source=0):
    BB_CALLS.append(('create', zone_id, def_id, obj_id, obj_state, loc_type, content_source))
    return 'cree'


def c_api_destroy_object(zone_id, obj_or_id):
    BB_CALLS.append(('destroy', zone_id, getattr(obj_or_id, 'id', obj_or_id)))
    return True


def c_api_set_parent_object(obj_id, parent_id, transform=None, joint_name=None, slot_hash=0, zone_id=None):
    BB_CALLS.append(('parent', obj_id, parent_id, transform, joint_name, slot_hash, zone_id))


def c_api_clear_parent_object(obj_id, transform, zone_id, surface):
    BB_CALLS.append(('unparent', obj_id, transform, zone_id, surface))


def c_api_set_object_location_ex(zone_id, obj_id, routing_surface, transform, parent_id, parent_type_info, slot_hash):
    BB_CALLS.append(('place', zone_id, obj_id, routing_surface, transform, parent_id, parent_type_info, slot_hash))
    return True


def c_api_set_object_location(zone_id, obj_id, routing_surface, transform):
    BB_CALLS.append(('place_simple', zone_id, obj_id, routing_surface, transform))
    return True


def c_api_buildbuy_session_begin(zone_id, account_id):
    return 'debut'


def c_api_buildbuy_session_end(zone_id, account_id, zone_data_change=None):
    return 'fin'


class ClientObjectMixin(object):
    def set_definition(self, definition_id, ignore_rig_footprint=False):
        BB_CALLS.append(('design', self.id, definition_id))
        return True


module('build_buy', c_api_set_object_location_ex=c_api_set_object_location_ex,
       c_api_set_object_location=c_api_set_object_location,
       c_api_buildbuy_session_begin=c_api_buildbuy_session_begin,
       c_api_buildbuy_session_end=c_api_buildbuy_session_end)
module('objects.object_manager', ObjectManager=ObjectManager)
module('objects.system', create_object=create_object, c_api_create_object=c_api_create_object,
       c_api_destroy_object=c_api_destroy_object, c_api_set_parent_object=c_api_set_parent_object,
       c_api_clear_parent_object=c_api_clear_parent_object)
module('objects.client_object_mixin', ClientObjectMixin=ClientObjectMixin)
sys.modules['objects'].system = sys.modules['objects.system']


class SurfaceType(int):
    SURFACETYPE_WORLD = 'monde'


module('routing', SurfaceIdentifier=lambda zone, level, kind: ('surface', zone, level, kind), SurfaceType=SurfaceType)
math = module('sims4.math', Vector3=lambda x, y, z: ('v', x, y, z), Quaternion=lambda x, y, z, w: ('q', x, y, z, w),
              Transform=lambda v, q: ('t', v, q))
sys.modules['sims4'].math = math
MIXER = types.SimpleNamespace(guid64=77, __name__='mixer_social_Chat', is_super=False)
SOCIAL = types.SimpleNamespace(guid64=88, __name__='socials_SocialSuper', is_super=True)
INTERACTIONS = {77: MIXER, 88: SOCIAL}

SIM_TIMELINE = Timeline('sims')
WALL_TIMELINE = Timeline('horloge murale')
ZONE = _Zone()


class Interaction(object):
    def __init__(self, interaction_id, user=True):
        self.id = interaction_id
        self.is_user_directed = user
        self.canceled = None

    def cancel_user(self, cancel_reason_msg=None):
        self.canceled = cancel_reason_msg
        return True


class Sim(object):
    is_sim = True

    def __init__(self, sim_id, interactions=()):
        self.sim_info = types.SimpleNamespace(sim_id=sim_id, get_sim_instance=lambda **kwargs: self)
        self._interactions = {i.id: i for i in interactions}
        self.si_state = []
        self.autonomy = None
        self.autonomy_settings = types.SimpleNamespace(
            set_setting=lambda state, group: setattr(self, 'autonomy', (state, group)))

    def get_autonomy_settings_group(self):
        return 'groupe'

    def find_interaction_by_id(self, interaction_id):
        return self._interactions.get(interaction_id)

    def find_continuation_by_id(self, interaction_id):
        return None


SLEEP = Interaction(555)
SIMS = [Sim(1), Sim(2, [SLEEP])]
CLIENT = types.SimpleNamespace(id=0xABC, choice_menu='menu de l\'hote')
CLIENT.set_choices = lambda menu: setattr(CLIENT, 'choice_menu', menu)
module('services',
       client_manager=lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT),
       current_zone=lambda: ZONE,
       time_service=lambda: types.SimpleNamespace(sim_timeline=SIM_TIMELINE),
       sim_info_manager=lambda: types.SimpleNamespace(
           instanced_sims_gen=lambda: iter(SIMS),
           get=lambda sim_id: next((s.sim_info for s in SIMS if s.sim_info.sim_id == sim_id), None)),
       get_instance_manager=lambda kind: types.SimpleNamespace(get=INTERACTIONS.get),
       ui_dialog_service=lambda: DIALOGS,
       object_manager=lambda: MANAGER,
       current_zone_id=lambda: 99,
       autonomy_service=lambda: AUTONOMY_SERVICE)
AUTONOMY_SERVICE = types.SimpleNamespace(_selected_sim_autonomy_enabled=False)
module('autonomy')
module('autonomy.settings', AutonomyState=types.SimpleNamespace(LIMITED_ONLY='limitee', UNDEFINED='normale'))

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import omega  # noqa: E402
import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
from server_commands import interaction_commands  # noqa: E402

results = []
notes = []
real_kind = mod.bridge_interaction_kind
real_order = mod.bridge_order_from_interaction
mod.show_notification = lambda title, text, *args, **kwargs: notes.append(text)
TMP = tempfile.mkdtemp(prefix='sims4mp_mirror_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


class Endpoint(object):
    def __init__(self):
        self.sent = []
        self.is_connected = True

    def send(self, message):
        protocol.encode_message(message)             # meme limite de taille que le vrai transport
        self.sent.append(message)
        return True


def events(endpoint, kind):
    return [m['data'] for m in endpoint.sent if m['type'] == protocol.EVENT and m['data'].get('kind') == kind]


report('accroches installees : ligne du temps, horloge, PNJ, croix, fenetres, objets, construction, menus',
       mod._mirror['hooks'] == ['ligne du temps', 'horloge', 'PNJ', 'croix', 'fenetres', 'objets', 'construction',
                                'menus'], str(mod._mirror['hooks']))

# --- 1. Hote : choix, annonce, confirmation ---------------------------------------------------
host = mod.NetSession('host', Endpoint())
host.handshake_done = True
mod._session = host
mod._gate['waiting'] = False
report('seul mode (0.21.0) : voulue des le chargement, l\'ancienne synchro ne tourne pas chez l\'hote',
       mod._mirror['wanted'] and mod.mirror_on(host))
mod._mirror_announce(host)
report('annoncee a l\'invite des sa connexion',
       events(host.endpoint, 'mirror') == [{'kind': 'mirror', 'on': True}])
mod._mirror_tick(host, 99.0)
report('pas de recopie tant que l\'invite n\'a pas gele sa simulation', not mod._mirror['capturing'])
mod._handle_mirror_ready(host, {'kind': 'mirror_ready', 'on': True})
report('confirmation de l\'invite : active chez l\'hote', mod.mirror_on(host) and host.mirror_ready)
mod._mirror_tick(host, 100.0)
report('recopie demarree au passage de la pompe', mod._mirror['capturing'])

# --- 2. Hote : recopie de l'affichage -----------------------------------------------------------
del SENT[:]
omega.send(0x1, 11, b'\x01\x02vue')
omega.send(0x1, 40, b'fenetre de l\'hote')
omega.send(0x1, 210, b'connexion')
omega.send(0x1, 159, b'humeur')
report('l\'affichage de l\'hote n\'est pas change (omega.send d\'origine appele 4 fois)', len(SENT) == 4)
report('fenetres et etat de connexion de l\'hote gardes sur son ecran',
       [m for m, _ in mod._mirror['out']] == [11, 159] and mod._mirror['skipped'] == 2,
       str(mod._mirror['out']))
mod._mirror_tick(host, 101.0)
views = events(host.endpoint, 'view')
report('envoye a l\'invite en un lot, octets en base64',
       len(views) == 1 and views[0]['m'] == [[11, base64.b64encode(b'\x01\x02vue').decode('ascii')],
                                             [159, base64.b64encode(b'humeur').decode('ascii')]]
       and not mod._mirror['out'], str(views))
omega.send(0x1, 11, b'x' * (mod.MIRROR_MAX_RAW + 1))
report('message trop gros : jamais recopie', mod._mirror['too_big'] == 1 and not mod._mirror['out'])
items = [(11, b'a' * 100000), (11, b'b' * 100000), (11, b'c' * 100000), (11, b'd' * 700000)]
batches = list(mod.mirror_batches(items))
report('lots d\'au plus {} octets, un gros message part seul'.format(mod.MIRROR_BATCH_BYTES),
       [len(b) for b in batches] == [2, 1, 1], str([len(b) for b in batches]))
for _ in range(mod.MIRROR_QUEUE_MAX + 1):
    mod.mirror_capture(11, b'z')
report('file pleine : videe et comptee', not mod._mirror['out'] and mod._mirror['dropped'] == mod.MIRROR_QUEUE_MAX + 1)

# --- 3. Hote : l'ancienne synchro se retire ------------------------------------------------------
report('ordres de l\'hote plus envoyes (l\'invite voit deja le resultat)',
       mod.send_player_order({'sim_id': 1, 'affordance': 5, 'name': 'sit', 'target': {'t': 'none'},
                              'auto': False}) is None)
queue = InteractionQueue(types.SimpleNamespace(sim_info=types.SimpleNamespace(sim_id=2)))
mod.bridge_interaction_kind = lambda interaction: 'auto'
report('autonomie jamais refusee chez l\'hote (il decide pour tous les Sims)',
       mod.autonomy_refused(queue, Interaction(9, user=False)) is False)

# --- 4. Hote : croix de l'invite ----------------------------------------------------------------
mod._handle_cancel_si(host, {'kind': 'cancel_si', 'id': 555})
report('croix de l\'invite : l\'action de l\'hote est annulee comme par sa croix',
       SLEEP.canceled is not None and mod._mirror['cancels_applied'] == 1)
mod._handle_cancel_si(host, {'kind': 'cancel_si', 'id': 'x'})
mod._handle_cancel_si(host, {'kind': 'cancel_si', 'id': 999})
report('identifiant invalide ou action finie : rien de plus', mod._mirror['cancels_applied'] == 1)

text = mod.mirror_set_wanted(False)
report('coupee par l\'hote : annonce envoyee, plus active',
       events(host.endpoint, 'mirror')[-1] == {'kind': 'mirror', 'on': False} and not mod.mirror_on(host))
mod._mirror_tick(host, 102.0)
report('recopie arretee', not mod._mirror['capturing'])

# --- 5. Invite : gel de sa simulation ------------------------------------------------------------
guest = mod.NetSession('client', Endpoint())
guest.handshake_done = True
mod._session = guest
SIM_TIMELINE.runs = WALL_TIMELINE.runs = 0
SIM_TIMELINE.simulate(1)
report('avant la simulation unique : la ligne du temps des Sims avance', SIM_TIMELINE.runs == 1)
del notes[:]
mod._handle_mirror(guest, {'kind': 'mirror', 'on': True})
report('annonce de l\'hote : simulation gelee, confirmation et notification',
       mod._mirror['active'] and events(guest.endpoint, 'mirror_ready') == [{'kind': 'mirror_ready', 'on': True}]
       and any('l\'hôte calcule la partie' in n for n in notes))
result = SIM_TIMELINE.simulate(2)
report('ligne du temps des Sims gelee (« tout est fait », rien n\'est execute)',
       result is True and SIM_TIMELINE.runs == 1 and mod._mirror['frozen'] == 1)
WALL_TIMELINE.simulate(2)
report('les autres lignes du temps continuent', WALL_TIMELINE.runs == 1)
ZONE.is_zone_running = False
SIM_TIMELINE.simulate(3)
ZONE.is_zone_running = True
report('chargement ou voyage (zone arretee) : jamais gele', SIM_TIMELINE.runs == 2)
GameClock.broadcasts = 0
GameClock()._sync_clock_and_broadcast_gameclock()
SimSpawnerService.updates = 0
SimSpawnerService().update()
report('heure et venue des PNJ de l\'invite coupees (elles viennent de l\'hote)',
       GameClock.broadcasts == 0 and SimSpawnerService.updates == 0
       and mod._mirror['clock_skipped'] == 1 and mod._mirror['spawns_skipped'] == 1)

# --- 6. Invite : affichage recu de l'hote ---------------------------------------------------------
del SENT[:]
mod._handle_view(guest, {'kind': 'view', 'm': [[11, base64.b64encode(b'vue1').decode('ascii')],
                                               [159, base64.b64encode(b'humeur').decode('ascii')]]})
report('messages de l\'hote remis a l\'affichage de l\'invite, dans l\'ordre (son client)',
       SENT == [(0xABC, 11, b'vue1'), (0xABC, 159, b'humeur')] and mod._mirror['delivered'] == 2, str(SENT))
del SENT[:]
mod._handle_view(guest, {'kind': 'view', 'm': [[11, 'pas du base64 !'], ['11', 'AA=='], [-1, 'AA=='], 'x']})
mod._handle_view(guest, {'kind': 'view', 'm': 'pas une liste'})
report('entrees invalides ignorees', not SENT and mod._mirror['ignored'] == 4)

# --- 7. Invite : clics et croix partent a l'hote --------------------------------------------------
mod.bridge_order_from_interaction = lambda q, i, kind='pie', mixers=False: {
    'sim_id': 2, 'affordance': 77, 'name': 'bed_sleep', 'target': {'t': 'obj', 'id': 9}, 'auto': False}
click = Interaction(42)
refused = queue.append(click)
orders = events(guest.endpoint, 'order')
report('clic de l\'invite : envoye a l\'hote et refuse dans sa file gelee',
       not refused and refused.reason == mod.MIRROR_REFUSE_REASON and click not in queue.items
       and len(orders) == 1 and orders[0]['affordance'] == 77, str(orders))
auto = Interaction(43, user=False)
mod.bridge_interaction_kind = lambda interaction: None
report('action non choisie par le joueur : laissee au jeu', bool(queue.append(auto)) and auto in queue.items)
del LOCAL_CANCELS[:]
answer = interaction_commands.cancel_common(555, None, None)
report('croix de l\'invite : envoyee a l\'hote (cancel_si), pas annulee localement',
       answer is True and not LOCAL_CANCELS and events(guest.endpoint, 'cancel_si') == [{'kind': 'cancel_si', 'id': 555}])
mod._handle_order(guest, {'kind': 'order', 'id': 'host-9', 'sim_id': 2, 'affordance': 77,
                          'target': {'t': 'none'}, 'name': 'x'})
report('ordre recu de l\'hote : jamais rejoue chez l\'invite', guest.orders_replayed == 0 and guest.orders_failed == 0)

# --- 8. Actions sociales (0.20.1) -----------------------------------------------------------------
mod.bridge_interaction_kind = real_kind
mod.bridge_order_from_interaction = real_order
chat = Interaction(44)
chat.source, chat.affordance, chat.super_affordance, chat.target = 'pie', MIXER, SOCIAL, SIMS[0]
queue.append(chat)
orders = events(guest.endpoint, 'order')
report('action sociale de l\'invite : envoyee avec son action principale',
       orders[-1]['affordance'] == 77 and orders[-1].get('super') == 88
       and orders[-1]['target'] == {'t': 'sim', 'id': 1}, str(orders[-1]))
report('hors simulation unique, une action sociale reste non transmise (option A inchangee)',
       real_order(queue, chat) is None)
mod._session = host
mod._mirror['wanted'] = True
host.mirror_ready = True
running = types.SimpleNamespace(affordance=SOCIAL, is_finishing=False)
SIMS[1].si_state = [running]
del AffordanceObjectPair.made[:]
mod._handle_order(host, dict(orders[-1]))
report('hote : action sociale recreee comme le menu du jeu (meme paire, action principale en cours)',
       AffordanceObjectPair.made == [(MIXER, SIMS[0], SOCIAL, running), ('contexte', 'su', 'haute')]
       and host.orders_replayed == 1, str(AffordanceObjectPair.made))
SIMS[1].si_state = []
del AffordanceObjectPair.made[:]
mod._handle_order(host, dict(orders[-1], id='client-99'))
report('sans action principale en cours : le mixer la pousse lui-meme (si = None)',
       AffordanceObjectPair.made[0] == (MIXER, SIMS[0], SOCIAL, None))
report('ordre avec action principale invalide : refuse',
       mod.validate_order(dict(orders[-1], super='x')) is None)

# --- 9. Fenetres du Sim de l'invite (0.20.1) -------------------------------------------------------
mod._handle_host_event(host, 'message', {'type': protocol.EVENT, 'v': 1,
                                         'data': {'kind': 'presence', 'active_sim': 2}})
report('presence de l\'invite : l\'hote connait le Sim qu\'il controle', host.guest_sim_id == 2)
report('Sim de l\'invite : autonomie limitee chez l\'hote, comme un Sim selectionne (0.21.1)',
       SIMS[1].autonomy == ('limitee', 'groupe') and mod._mirror['limited'] == {2}, str(SIMS[1].autonomy))
mod._handle_host_event(host, 'message', {'type': protocol.EVENT, 'v': 1,
                                         'data': {'kind': 'presence', 'active_sim': 1}})
report('l\'invite change de Sim : l\'ancien redevient autonome, le nouveau est limite',
       SIMS[1].autonomy == ('normale', 'groupe') and SIMS[0].autonomy == ('limitee', 'groupe')
       and mod._mirror['limited'] == {1})
AUTONOMY_SERVICE._selected_sim_autonomy_enabled = True
mod._handle_host_event(host, 'message', {'type': protocol.EVENT, 'v': 1,
                                         'data': {'kind': 'presence', 'active_sim': 1}})
report('option « autonomie du Sim selectionne » active chez l\'hote : rien n\'est limite',
       SIMS[0].autonomy == ('normale', 'groupe') and not mod._mirror['limited'])
AUTONOMY_SERVICE._selected_sim_autonomy_enabled = False
mod._handle_host_event(host, 'message', {'type': protocol.EVENT, 'v': 1,
                                         'data': {'kind': 'presence', 'active_sim': 2}})
mod._handle_host_event(host, 'disconnected', 'test')
report('invite deconnecte : son Sim redevient autonome chez l\'hote',
       SIMS[1].autonomy == ('normale', 'groupe') and not mod._mirror['limited'])
host.handshake_done = host.mirror_ready = True
mod._handle_host_event(host, 'message', {'type': protocol.EVENT, 'v': 1,
                                         'data': {'kind': 'presence', 'active_sim': 2}})
mod._mirror_tick(host, 200.0)
del SENT[:]
omega.send(0x1, 40, b'7:2')
report('fenetre du Sim de l\'invite : envoyee a l\'invite, pas ouverte chez l\'hote',
       not SENT and mod._mirror['out'][-1] == (40, b'7:2') and 7 in mod._mirror['dialogs'])
omega.send(0x1, 40, b'8:1')
report('fenetre d\'un autre Sim : reste chez l\'hote', SENT == [(0x1, 40, b'8:1')] and 8 not in mod._mirror['dialogs'])
del SENT[:]
omega.send(0x1, 41, b'9:2')
omega.send(0x1, 41, b'10:1')
report('notification du Sim de l\'invite : chez lui seulement ; autre notification : chez l\'hote (0.21.4)',
       SENT == [(0x1, 41, b'10:1')] and mod._mirror['out'][-1] == (41, b'9:2') and 9 in mod._mirror['dialogs']
       and 10 not in mod._mirror['dialogs'] and mod._mirror['notifications_sent'] == 1, str(SENT))
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'respond', 'id': 7, 'values': [3]})
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'pick', 'id': 7, 'values': [[11, 12], True, False, None]})
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'text', 'id': 7, 'values': ['nom', 'Bob']})
report('reponses de l\'invite appliquees chez l\'hote (bouton, liste, texte)',
       DIALOGS.calls == [('respond', 7, 3, CLIENT), ('pick', 7, (11, 12), True, False, None), ('text', 7, 'nom', 'Bob')]
       and mod._mirror['dialog_applied'] == 3, str(DIALOGS.calls))
del DIALOGS.calls[:]
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'respond', 'id': 8, 'values': [1]})
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'respond', 'id': 7, 'values': ['x']})
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'pick', 'id': 7, 'values': [[1], 'oui', False, None]})
mod._handle_dialog(host, {'kind': 'dialog', 'how': 'drop', 'id': 7, 'values': [1]})
report('fenetre non envoyee a l\'invite ou reponse invalide : ignoree', not DIALOGS.calls)

mod._session = guest
mod._mirror['wanted'] = False
del DIALOGS.calls[:]
DIALOGS.dialog_respond(7, 3, CLIENT)
DIALOGS.dialog_pick_result(7, (11, 12), True, False, None)
DIALOGS.dialog_text_input(7, 'nom', 'Bob')
answers = events(guest.endpoint, 'dialog')
report('invite : reponses a une fenetre de l\'hote envoyees a l\'hote, pas a son propre jeu',
       not DIALOGS.calls and [a['how'] for a in answers] == ['respond', 'pick', 'text']
       and answers[1]['values'] == [[11, 12], True, False, None], str(answers))
DIALOGS.known[5] = object()
DIALOGS.dialog_respond(5, 1, CLIENT)
report('invite : ses propres fenetres (menu Sims4MP) restent chez lui',
       DIALOGS.calls == [('respond', 5, 1, CLIENT)] and len(events(guest.endpoint, 'dialog')) == 3)
mod._maybe_send_presence(guest, 1000.0)
report('presence de l\'invite : le Sim qu\'il controle part avec (None si inconnu)',
       'active_sim' in events(guest.endpoint, 'presence')[-1])

# --- 10. Objets crees ou retires apres le chargement (0.20.2) --------------------------------------
mod._session = host
mod._mirror['wanted'] = True
host.mirror_ready = True
mod._mirror_tick(host, 300.0)
plate = GameObject(1001, 50)
MANAGER.add(plate)
sim_obj = GameObject(2, 1)
sim_obj.is_sim = True
MANAGER.add(sim_obj)
flash = GameObject(1002, 51)
MANAGER.add(flash)
MANAGER.remove(flash)
old = GameObject(900, 40)
OBJECTS[900] = old
MANAGER.remove(old)
mod._mirror_tick(host, 301.0)
sent = events(host.endpoint, 'objects')
report('hote : objet cree envoye (definition, position, rotation), objet retire envoye',
       len(sent) == 1 and sent[0]['new'] == [{'id': 1001, 'def': 50, 'p': [1.0, 0.0, 2.0],
                                              'q': [0.0, 0.7071, 0.0, 0.7071], 'level': 0}]
       and sent[0]['del'] == [900], str(sent))
report('Sims (presence) et objet cree puis retire dans le meme passage : non envoyes',
       all(e['id'] not in (2, 1002) for e in sent[0]['new']))
mod._mirror['capturing'] = False
OBJECTS.clear()

mod._session = guest
mod._mirror['wanted'] = False
del Distributor.shown[:]
del CREATED[:]
mod._handle_objects(guest, {'kind': 'objects', 'new': [sent[0]['new'][0], {'id': 1003, 'def': 666, 'p': [0, 0, 0],
                                                                              'q': [0, 0, 0, 1], 'level': 0},
                                                       {'id': 'x'}], 'del': []})
replica = OBJECTS.get(1001)
report('invite : copie de l\'objet avec le meme identifiant, posee au meme endroit, sans affichage propre',
       replica is not None and CREATED[0] == (50, 1001) and not Distributor.shown
       and replica.moved == {'transform': ('t', ('v', 1.0, 0.0, 2.0), ('q', 0.0, 0.7071, 0.0, 0.7071)),
                             'routing_surface': ('surface', 99, 0, 'monde')}, str(replica and replica.moved))
report('objet refuse par le jeu ou mal forme : compte, sans copie',
       mod._mirror['replicas_failed'] == 1 and 1003 not in OBJECTS and 1003 not in mod._mirror['replicas'])
mod._handle_objects(guest, {'kind': 'objects', 'new': [sent[0]['new'][0]], 'del': []})
report('objet deja present : pas de deuxieme copie', CREATED.count((50, 1001)) == 1)
save_obj = GameObject(900, 40)
OBJECTS[900] = save_obj
mod._handle_objects(guest, {'kind': 'objects', 'new': [], 'del': [900, 1001, 4242]})
report('invite : objets retires par l\'hote retires ici aussi, sans affichage en double',
       900 not in OBJECTS and 1001 not in OBJECTS and not Distributor.shown and mod._mirror['replicas_removed'] == 2)
MANAGER.add(GameObject(5000, 7))
report('objet ordinaire de l\'invite : affichage normal', Distributor.shown == [('ajout', 5000)])

# --- 11. Construction et achat faits par l'invite (0.20.3) -----------------------------------------
import build_buy  # noqa: E402
from objects import system as obj_system  # noqa: E402

vec = types.SimpleNamespace(x=3.0, y=0.0, z=4.0)
rot = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
TRANSFORM = types.SimpleNamespace(translation=vec, orientation=rot)
SURFACE = types.SimpleNamespace(secondary_id=1, type=1)
del BB_CALLS[:]
start = len(events(guest.endpoint, 'bb'))
obj_system.c_api_create_object(99, 60, 3001, None, 1, 0)
build_buy.c_api_set_object_location_ex(99, 3001, SURFACE, TRANSFORM, 0, None, 0)
build_buy.c_api_set_object_location(99, 3001, SURFACE, TRANSFORM)
obj_system.c_api_set_parent_object(3002, 3001, TRANSFORM, None, 7, 99)
obj_system.c_api_clear_parent_object(3002, TRANSFORM, 99, SURFACE)
recolored = ClientObjectMixin()
recolored.id = 3001
recolored.set_definition(61)                         # hors mode construction : non transmis
build_buy.c_api_buildbuy_session_begin(99, 1)
recolored.set_definition(61)
build_buy.c_api_buildbuy_session_end(99, 1)
obj_system.c_api_destroy_object(99, 3002)
gestures = events(guest.endpoint, 'bb')[start:]
report('invite : chaque geste est fait ici puis envoye a l\'hote',
       len(BB_CALLS) == 8 and [g['op'] for g in gestures] == ['create', 'place', 'place', 'parent', 'unparent',
                                                             'design', 'destroy'], str([g['op'] for g in gestures]))
report('creation : definition, etat, emplacement ; copie sans affichage propre chez l\'invite',
       gestures[0] == {'kind': 'bb', 'op': 'create', 'id': 3001, 'def': 60, 'state': None, 'loc': 1, 'content': 0}
       and 3001 in mod._mirror['replicas'], str(gestures[0]))
report('deplacement : position, rotation, etage et type de surface',
       gestures[1]['p'] == [3.0, 0.0, 4.0] and gestures[1]['q'] == [0.0, 0.0, 0.0, 1.0] and gestures[1]['s'] == [1, 1]
       and 'parent' not in gestures[2] and gestures[3]['parent'] == 3001 and gestures[3]['slot'] == 7, str(gestures[1]))
report('recoloriage transmis seulement en mode construction', gestures[5] == {'kind': 'bb', 'op': 'design',
                                                                              'id': 3001, 'def': 61})

mod._session = host
mod._mirror['wanted'] = True
host.mirror_ready = True
del BB_CALLS[:]
OBJECTS[3001] = recolored
for gesture in gestures:
    mod._handle_build_buy(host, gesture)
report('hote : gestes rejoues avec les memes fonctions du jeu, dans sa zone',
       [c[0] for c in BB_CALLS] == ['create', 'place', 'place', 'parent', 'unparent', 'design', 'destroy']
       and BB_CALLS[0] == ('create', 99, 60, 3001, None, 1, 0)
       and BB_CALLS[1][3] == ('surface', 99, 1, 1) and BB_CALLS[1][4] == ('t', ('v', 3.0, 0.0, 4.0),
                                                                          ('q', 0.0, 0.0, 0.0, 1.0))
       and mod._mirror['bb_applied'] == 7, str(BB_CALLS[:2]))
report('hote : rien n\'est renvoye a l\'invite en echo', len(events(host.endpoint, 'bb')) == 0)
del BB_CALLS[:]
for bad in ({'op': 'create', 'id': 1}, {'op': 'fly', 'id': 1}, {'op': 'place', 'id': 1, 'p': [0, 0], 'q': [0, 0, 0, 1],
                                                                's': [0, 1]}, {'op': 'destroy', 'id': 'x'}):
    mod._handle_build_buy(host, dict(bad, kind='bb'))
report('geste invalide : ignore', not BB_CALLS)
mod._mirror['wanted'] = False
mod._session = guest

# --- 12. Menus circulaires calcules chez l'hote (0.21.2) -------------------------------------------
commands_module = sys.modules['server_commands.interaction_commands']
del GENERATED[:]
start = len(events(guest.endpoint, 'pie'))
commands_module.generate_choices(1001, 2, 1.5, 0.0, 2.5, 5, 0, False, False, True, 77, 0, 0, True, CLIENT.id)
commands_module.generate_phone_choices(False, False, False, 78, None, CLIENT.id)
asked = events(guest.endpoint, 'pie')[start:]
report('invite : le clic qui ouvre un menu part a l\'hote, rien n\'est calcule chez lui',
       not GENERATED and [a['how'] for a in asked] == ['pie', 'phone']
       and asked[0]['args']['target_id'] == 1001 and asked[0]['args']['x'] == 1.5
       and asked[0]['args']['shift'] is True and asked[0]['args']['reference_id'] == 77, str(asked))
del LOCAL_SELECTS[:]
commands_module.select_choice(3, 41, CLIENT.id)
chosen = events(guest.endpoint, 'pie_select')
report('invite : son choix dans le menu part a l\'hote',
       not LOCAL_SELECTS and chosen[-1] == {'kind': 'pie_select', 'choice': 3, 'revision': 41}, str(chosen))

mod._session = host
mod._mirror['wanted'] = True
host.guest_sim_id = 2
CLIENT.choice_menu = 'menu de l\'hote'
mod._handle_pie(host, asked[0])
guest_menu = mod._mirror['guest_menu']
report('hote : menu calcule pour le Sim de l\'invite avec la commande du jeu, menu de l\'hote remis',
       GENERATED == [('pie', SIMS[1], 1001, 77, 1.5, True, CLIENT.id)] and guest_menu is not None
       and guest_menu.sim is SIMS[1] and CLIENT.choice_menu == 'menu de l\'hote'
       and commands_module._active_sim(CLIENT) == 'Sim actif de l\'hote', str(GENERATED))
mod._handle_pie(host, asked[1])
report('menu du telephone calcule de la meme facon', GENERATED[-1][:3] == ('phone', SIMS[1], 78))
mod._mirror['capturing'] = True
del SENT[:]
omega.send(0x1, 6, b'2:77')
omega.send(0x1, 171, b'2:78')
omega.send(0x1, 6, b'1:5')
report('message du menu de l\'invite : chez l\'invite seulement ; menu de l\'hote : chez l\'hote',
       SENT == [(0x1, 6, b'1:5')] and mod._mirror['out'][-2:] == [(6, b'2:77'), (171, b'2:78')]
       and not mod._mirror['pie_pending'] and mod._mirror['menus_sent'] == 2, str(SENT))
phone_menu = mod._mirror['guest_menu']
mod._handle_pie_select(host, {'kind': 'pie_select', 'choice': 3, 'revision': 1})
report('choix pour un menu perime : ignore, sans toucher au Sim', phone_menu.selected is None
       and mod._mirror['menus_stale'] == 1)
mod._handle_pie_select(host, {'kind': 'pie_select', 'choice': 3, 'revision': phone_menu.revision})
report('choix de l\'invite applique dans son menu (meme revision)', phone_menu.selected == 3
       and mod._mirror['guest_menu'] is None)
mod._mirror['capturing'] = False
mod._mirror['wanted'] = False
mod._session = guest

# --- 13. Nouveaux Sims (0.21.3) ---------------------------------------------------------------------


class Proto(object):
    def __init__(self, data=b''):
        self.data = data

    def ParseFromString(self, data):
        self.data = bytes(data)

    def SerializeToString(self):
        return self.data


class Persistence(object):
    def __init__(self):
        self.sims, self.households = {}, {}

    def get_sim_proto_buff(self, sim_id):
        return self.sims.get(sim_id)

    def add_sim_proto_buff(self, sim_id):
        self.sims[sim_id] = Proto()
        return self.sims[sim_id]

    def get_household_proto_buff(self, household_id):
        return self.households.get(household_id)

    def add_household_proto_buff(self, household_id):
        self.households[household_id] = Proto()
        return self.households[household_id]


PERSISTENCE = Persistence()
HOUSEHOLDS = {}
LOADED_HOUSEHOLDS = []


def _load_household(household_id):
    LOADED_HOUSEHOLDS.append((household_id, PERSISTENCE.households[household_id].data))
    SIMS.append(Sim(3000))                            # le jeu cree les Sims du foyer charge


services_module = sys.modules['services']
services_module.get_persistence_service = lambda: PERSISTENCE
services_module.household_manager = lambda: types.SimpleNamespace(get=HOUSEHOLDS.get, load_household=_load_household)

# Hote : profil d'un Sim cree apres la sauvegarde.
mod._session = host
mod._mirror['wanted'] = True
baby = Sim(3000)
baby.sim_info.save_sim = lambda: Proto(b'profil-bebe')
baby.sim_info.household = types.SimpleNamespace(id=70, save_data=lambda: PERSISTENCE.households.__setitem__(
    70, Proto(b'foyer-70')))
SIMS.append(baby)
mod._handle_sim_request(host, {'kind': 'sim_request', 'id': 3000})
profiles = events(host.endpoint, 'sim_profile')
report('hote : profil sauvegarde du Sim et de son foyer envoye a l\'invite',
       len(profiles) == 1 and base64.b64decode(profiles[0]['sim']) == b'profil-bebe'
       and base64.b64decode(profiles[0]['household']) == b'foyer-70' and profiles[0]['household_id'] == 70,
       str(profiles))
mod._handle_sim_request(host, {'kind': 'sim_request', 'id': 9999})
report('Sim inconnu chez l\'hote : rien n\'est envoye', len(events(host.endpoint, 'sim_profile')) == 1)
SIMS.remove(baby)
mod._mirror['wanted'] = False

# Invite : la presence trouve ce Sim inconnu, demande son profil, le charge, le fait apparaitre.
mod._session = guest
spawned = []
mod.bridge_spawn_sim = lambda sim_id, x, y, z: (
    'inconnu' if all(s.sim_info.sim_id != sim_id for s in SIMS) else spawned.append(sim_id) or 'ok')
mod.bridge_instanced_sim_ids = lambda: [1, 2]
roster = {'kind': 'roster', 'zone_id': 99, 'list': [{'sim_id': 3000, 'name': 'Bebe', 'x': 1.0, 'y': 0.0, 'z': 1.0}]}
mod._handle_roster(guest, roster)
report('invite : Sim de l\'hote inconnu ici, son profil est demande a l\'hote',
       events(guest.endpoint, 'sim_request')[-1] == {'kind': 'sim_request', 'id': 3000}
       and 3000 not in guest.roster_unknown and 3000 not in mod._mirror['replicas'])
mod._handle_sim_profile(guest, dict(profiles[0]))
report('invite : profil range dans sa sauvegarde, foyer charge par le jeu',
       PERSISTENCE.sims[3000].data == b'profil-bebe' and LOADED_HOUSEHOLDS == [(70, b'foyer-70')]
       and mod._mirror['sims_loaded'] == 1 and 3000 not in guest.roster_retry)
mod._handle_roster(guest, roster)
report('invite : la presence le fait ensuite apparaitre, sans affichage propre (copie)',
       spawned == [3000] and 3000 in mod._mirror['replicas'])
known = []
HOUSEHOLDS[71] = types.SimpleNamespace(refresh_sim_data=lambda sim_id: known.append(sim_id) or SIMS.append(Sim(sim_id)))
mod._handle_sim_profile(guest, {'kind': 'sim_profile', 'id': 3001, 'household_id': 71,
                                'sim': base64.b64encode(b'p').decode('ascii'), 'household': None})
report('foyer deja connu ici : Sim rattache par le jeu (Household.refresh_sim_data)', known == [3001])
mod._handle_sim_profile(guest, {'kind': 'sim_profile', 'id': 3002, 'sim': 'pas du base64 !'})
report('profil invalide : ignore', mod._mirror['sims_failed'] == 0 and 3002 not in PERSISTENCE.sims)
SIMS[:] = SIMS[:2]

# --- 14. Etat, commande de secours, fin ------------------------------------------------------------
del _CheatOutput.lines[:]
mod.mp_mirror('on')
report('mp.mirror on chez l\'invite : refuse (seul l\'hote choisit)',
       any('Seul l\'hôte' in line for line in _CheatOutput.lines)
       and any('vous voyez le jeu de l\'hôte' in line for line in _CheatOutput.lines), str(_CheatOutput.lines))
del notes[:]
mod._handle_client_event(guest, 'disconnected', 'test')
report('connexion perdue : simulation locale relancee et joueur prevenu',
       not mod._mirror['active'] and any('Simulation unique arrêtée' in n for n in notes))
SIM_TIMELINE.runs = 0
SIM_TIMELINE.simulate(4)
LOCAL_CANCELS.clear()
interaction_commands.cancel_common(1, None, None)
report('apres la fin : ligne du temps et croix redeviennent normales', SIM_TIMELINE.runs == 1 and LOCAL_CANCELS == [1])

mod._session = None
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
