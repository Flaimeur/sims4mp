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
    def __init__(self, sim_id, interactions=()):
        self.sim_info = types.SimpleNamespace(sim_id=sim_id)
        self._interactions = {i.id: i for i in interactions}

    def find_interaction_by_id(self, interaction_id):
        return self._interactions.get(interaction_id)

    def find_continuation_by_id(self, interaction_id):
        return None


SLEEP = Interaction(555)
SIMS = [Sim(1), Sim(2, [SLEEP])]
module('services',
       client_manager=lambda: types.SimpleNamespace(get_first_client=lambda: types.SimpleNamespace(id=0xABC)),
       current_zone=lambda: ZONE,
       time_service=lambda: types.SimpleNamespace(sim_timeline=SIM_TIMELINE),
       sim_info_manager=lambda: types.SimpleNamespace(instanced_sims_gen=lambda: iter(SIMS)))

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import omega  # noqa: E402
import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
from server_commands import interaction_commands  # noqa: E402

results = []
notes = []
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


report('accroches installees : ligne du temps, horloge, PNJ, croix',
       mod._mirror['hooks'] == ['ligne du temps', 'horloge', 'PNJ', 'croix'], str(mod._mirror['hooks']))

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
mod.bridge_order_from_interaction = lambda q, i, kind='pie': {
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

# --- 8. Etat, commande de secours, fin -------------------------------------------------------------
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
