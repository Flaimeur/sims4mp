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
module('server_commands.interaction_commands', cancel_common=cancel_common)


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
       MSG_UI_NOTIFICATION_SHOW=41, MSG_CONNECTION_STATUS_CONNECTED=210, MSG_SIM_MOOD_UPDATE=159)


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

    def find_interaction_by_id(self, interaction_id):
        return self._interactions.get(interaction_id)

    def find_continuation_by_id(self, interaction_id):
        return None


SLEEP = Interaction(555)
SIMS = [Sim(1), Sim(2, [SLEEP])]
CLIENT = types.SimpleNamespace(id=0xABC)
module('services',
       client_manager=lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT),
       current_zone=lambda: ZONE,
       time_service=lambda: types.SimpleNamespace(sim_timeline=SIM_TIMELINE),
       sim_info_manager=lambda: types.SimpleNamespace(
           instanced_sims_gen=lambda: iter(SIMS),
           get=lambda sim_id: next((s.sim_info for s in SIMS if s.sim_info.sim_id == sim_id), None)),
       get_instance_manager=lambda kind: types.SimpleNamespace(get=INTERACTIONS.get),
       ui_dialog_service=lambda: DIALOGS)

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


report('accroches installees : ligne du temps, horloge, PNJ, croix, fenetres',
       mod._mirror['hooks'] == ['ligne du temps', 'horloge', 'PNJ', 'croix', 'fenetres'], str(mod._mirror['hooks']))

# --- 1. Hote : choix, annonce, confirmation ---------------------------------------------------
host = mod.NetSession('host', Endpoint())
host.handshake_done = True
mod._session = host
mod._gate['waiting'] = False
report('desactivee par defaut : rien n\'est recopie', not mod.mirror_on(host) and not mod._mirror['capturing'])
text = mod.mirror_set_wanted(True)
report('menu de l\'hote : simulation unique demandee a l\'invite',
       events(host.endpoint, 'mirror') == [{'kind': 'mirror', 'on': True}] and 'demandée' in text, text)
report('pas encore active tant que l\'invite n\'a pas confirme', not mod.mirror_on(host))
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
mod._mirror_tick(host, 200.0)
del SENT[:]
omega.send(0x1, 40, b'7:2')
report('fenetre du Sim de l\'invite : envoyee a l\'invite, pas ouverte chez l\'hote',
       not SENT and mod._mirror['out'][-1] == (40, b'7:2') and 7 in mod._mirror['dialogs'])
omega.send(0x1, 40, b'8:1')
report('fenetre d\'un autre Sim : reste chez l\'hote', SENT == [(0x1, 40, b'8:1')] and 8 not in mod._mirror['dialogs'])
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

# --- 10. Etat, commande de secours, fin ------------------------------------------------------------
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
