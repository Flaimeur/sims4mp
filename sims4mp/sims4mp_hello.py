# Sims 4 Multiplayer - etape M3 : chaque joueur envoie la position de son Sim
# actif (lecture seule, mp.positions). M2 : pause imposee tant que les deux
# joueurs ne sont pas en jeu, file d'attente bloquee pendant l'attente. M1 : role lu
# depuis le lanceur, connexion automatique, notifications ; etat en lecture
# seule (mp.state).
# Compatible Python 3.7 (version embarquee par Les Sims 4) : pas de walrus,
# pas de match, pas d'annotations avancees.
#
# Commandes : mp.hello, mp.host [port], mp.join <ip> [port], mp.status,
#             mp.ping, mp.state, mp.positions, mp.disconnect
#
# Connexion automatique (M1) : a la fin de chaque chargement de partie
# (zone.Zone.on_loading_screen_animation_finished, verifie dans simulation.zip),
# le mod lit sims4mp_settings.json ecrit par le lanceur (Documents\Electronic
# Arts\, retrouve a partir du dossier Mods, lecture seule, validation stricte) :
# role host -> ecoute ; role join -> connexion non bloquante a l'hote. Un echec
# est retente au plus toutes les AUTO_RETRY_INTERVAL secondes. mp.disconnect
# arrete la connexion automatique jusqu'au prochain chargement.
#
# Etat envoye par le host (EVENT kind "state"), API verifiees dans simulation.zip :
#   heure     services.time_service().sim_now (.hour/.minute/.day/.week)
#   foyer     services.active_household() -> .id, .name, .funds.money
#   Sims      household.sim_info_gen() -> .first_name, .last_name
#   humeur    sim_info.get_mood() -> .__name__, .guid64
#   lot       sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
#             puis sim.is_on_active_lot() ; zone : services.current_zone_id()
# Aucune ecriture dans la partie. La position n'est pas envoyee.
#
# Pompe : zone.Zone.update est enveloppe. Verifie dans simulation.zip :
# areaserver.c_api_server_tick(absolute_ticks) appelle zone.update(absolute_ticks)
# sur la zone courante (si elle est instanciee et hors sauvegarde).
# La pompe ne fait que lire/ecrire les sockets et ecrire le journal. Les seuls
# acces au jeu passent par la section "Pont vers le jeu" : lecture de l'heure
# et affichage de notifications, sans modifier l'etat du jeu. Aucun thread :
# la pompe tourne dans Zone.update, donc sur le thread principal.
#
# Attente de l'autre joueur (M2). Chaque mod envoie EVENT {"kind": "presence"}
# toutes les PRESENCE_INTERVAL s pendant qu'il est en jeu (la pompe ne tourne
# que dans Zone.update : un ecran de chargement ou le menu principal coupent
# donc la presence). Tant qu'une partie a deux est prevue (session ou reglage
# du lanceur) et que la presence de l'autre manque depuis PRESENCE_TIMEOUT s :
#   - pause : services.game_clock_service().push_speed(ClockSpeedMode.PAUSED,
#     source=GameSpeedChangeSource.SITUATION, ...) puis remove_request(...) a
#     la fin. Verifie dans clock.pyc : game_speed_requests_gen parcourt les
#     sources par valeur croissante (SITUATION=0 d'abord) ; le bouton Play
#     passe par set_speed_internal (source GAMEPLAY=2) et les fenetres par
#     UI_MODAL=1, donc la pause du mod l'emporte. Si une autre demande
#     SITUATION la masque, elle est reposee au tick suivant.
#   - file : interactions.interaction_queue.InteractionQueue.append est
#     enveloppe ; une interaction is_user_directed (choix du joueur) est
#     refusee avec TestResult(False, ...), comme append le fait lui-meme quand
#     la file est verrouillee (verifie dans interaction_queue.pyc). Les actions
#     autonomes et celles deja en file ne sont pas touchees.
# mp.disconnect leve l'attente (jeu en solo).
#
# Positions (M3, lecture seule). Toutes les POSITION_INTERVAL s, chaque mod lit
# le Sim actif et l'envoie s'il a bouge (EVENT {"kind": "position", ...}).
# API verifiees dans simulation.zip : services.client_manager()
# .get_first_client().active_sim ; ClientObjectMixin.position (.x/.y/.z) et
# .level (routing_surface.secondary_id) ; sim.sim_info.sim_id ; sim.queue
# (InteractionQueue, pose dans Sim.__init__) et queue.running -> .affordance
# .__name__ ; services.sim_info_manager().get(sim_id). L'autre cote valide et
# garde la derniere position ; mp.positions la compare au meme Sim local.
# Rien n'est deplace.

import functools
import json
import os
import time
import traceback

import sims4.commands

MOD_NAME = 'sims4mp'
MOD_VERSION = '0.7.0'
LOG_FILE_NAME = 'sims4mp.log'
DEFAULT_PORT = 7777
PUMP_INTERVAL = 0.05     # secondes reelles minimum entre deux poll()
MAX_PUMP_ERRORS = 20     # au-dela, la session est arretee
STATE_INTERVAL = 5.0     # secondes reelles minimum entre deux envois d'etat
STATE_MAX_SIMS = 16      # limite du nombre de Sims acceptes dans un etat
STATE_MAX_TEXT = 64      # longueur maximale d'un texte recu
STATE_MAX_FUNDS = 10 ** 12
LOT_VALUES = ('lot actif', 'hors lot', 'absent')
SETTINGS_NAME = 'sims4mp_settings.json'   # ecrit par le lanceur, lu ici seulement
SETTINGS_KEYS = frozenset(['role', 'ip', 'port'])
SETTINGS_MAX_SIZE = 4096
AUTO_PORT_MIN = 1024                      # memes bornes que le lanceur
AUTO_RETRY_INTERVAL = 30.0                # secondes reelles entre deux tentatives
PRESENCE_INTERVAL = 2.0                   # secondes reelles entre deux « je suis en jeu »
PRESENCE_TIMEOUT = 8.0                    # sans nouvelles depuis : l'autre n'est plus en jeu
QUEUE_NOTICE_INTERVAL = 5.0               # au plus une notification « action refusee » par 5 s
POSITION_INTERVAL = 1.0                   # secondes reelles entre deux lectures de la position
POSITION_MIN_MOVE = 0.05                  # deplacement minimal (unites du jeu) pour renvoyer
POSITION_MAX_COORD = 100000.0
POSITION_LEVELS = (-16, 64)


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

def _find_log_dir():
    # __file__ pointe a l'interieur de l'archive .ts4script
    # (ex. ...\Mods\sims4mp_hello.ts4script\sims4mp_hello.pyc).
    # On remonte jusqu'au premier vrai dossier : celui qui contient l'archive.
    try:
        path = os.path.abspath(__file__)
        while path and not os.path.isdir(path):
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        if os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.expanduser('~')


LOG_PATH = os.path.join(_find_log_dir(), LOG_FILE_NAME)
_mods_dir = _find_log_dir()      # dossier qui contient l'archive (Mods ou un sous-dossier)


def log(message):
    try:
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write('[{}] {}\n'.format(stamp, message))
    except Exception:
        # Le journal ne doit jamais faire planter le jeu.
        pass


# ---------------------------------------------------------------------------
# Import de la couche reseau (protege : mp.hello doit marcher meme si ca echoue)
# ---------------------------------------------------------------------------

try:
    import protocol
    import transport
    NET_IMPORT_ERROR = None
except Exception:
    protocol = None
    transport = None
    NET_IMPORT_ERROR = traceback.format_exc()


# ---------------------------------------------------------------------------
# Test d'import et de fonctionnement de socket / select
# ---------------------------------------------------------------------------

def run_network_test():
    """Retourne une liste de (nom_du_test, ok, detail)."""
    results = []

    try:
        import socket
        results.append(('import socket', True, getattr(socket, '__file__', 'builtin')))
    except Exception as e:
        results.append(('import socket', False, repr(e)))
        socket = None

    try:
        import select
        results.append(('import select', True, getattr(select, '__file__', 'builtin')))
    except Exception as e:
        results.append(('import select', False, repr(e)))
        select = None

    # Test fonctionnel limite a la boucle locale (127.0.0.1) :
    # aucune ouverture sur le reseau, pas de demande du pare-feu.
    if socket is not None and select is not None:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            sock.bind(('127.0.0.1', 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            readable, _, _ = select.select([sock], [], [], 0)
            results.append(('socket+select local', True,
                            'port {} , select ok ({} pret)'.format(port, len(readable))))
        except Exception as e:
            results.append(('socket+select local', False, repr(e)))
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    results.append(('import protocol/transport', NET_IMPORT_ERROR is None,
                    'ok' if NET_IMPORT_ERROR is None else NET_IMPORT_ERROR.strip().splitlines()[-1]))
    return results


def _log_network_test(results):
    for name, ok, detail in results:
        log('  {} : {} ({})'.format(name, 'OK' if ok else 'ECHEC', detail))


# ---------------------------------------------------------------------------
# Pont vers le jeu (lecture seule + interface, thread principal uniquement)
# ---------------------------------------------------------------------------
# Imports locaux : ces modules du jeu ne doivent pas bloquer le chargement
# du mod s'ils changent apres un patch.

def show_notification(title, text):
    # Meme appel que la commande du jeu ui_dialog_notification_test
    # (server_commands/ui_commands.pyc), mais sans _connection : on prend le
    # premier client, comme le font de nombreux scripts du jeu.
    import services
    from sims4.localization import LocalizationHelperTuning
    from ui.ui_dialog_notification import UiDialogNotification

    client = services.client_manager().get_first_client()
    owner = client.active_sim if client is not None else None
    dialog = UiDialogNotification.TunableFactory().default(
        owner,
        text=lambda: LocalizationHelperTuning.get_raw_text(text),
        title=lambda: LocalizationHelperTuning.get_raw_text(title),
    )
    dialog.show_dialog()


def bridge_notify(text):
    """Notification protegee : une erreur est journalisee, jamais propagee."""
    try:
        show_notification('Sims4MP', text)
        return True
    except Exception:
        log('ECHEC notification :\n' + traceback.format_exc())
        return False


_read_failures = set()


def _log_read_failure(field):
    # Trace complete la premiere fois pour un champ, une ligne ensuite
    # (les lectures sont repetees toutes les 5 s).
    tb = traceback.format_exc()
    if field in _read_failures:
        log('lecture echouee : {} ({})'.format(field, tb.strip().splitlines()[-1]))
    else:
        _read_failures.add(field)
        log('lecture echouee : {}\n{}'.format(field, tb))


def _read(field, func):
    """Appelle func() ; en cas d'erreur, journalise le champ et renvoie None."""
    try:
        return func()
    except Exception:
        _log_read_failure(field)
        return None


def _game_time_text():
    import services
    now = services.time_service().sim_now
    return '{:02d}:{:02d} (jour {}, semaine {})'.format(
        now.hour(), now.minute(), now.day(), now.week())


def bridge_game_time():
    """Heure de jeu courante en texte, ou None si indisponible."""
    return _read('game_time', _game_time_text)


def _active_household():
    import services
    return services.active_household()


def _current_zone_id():
    import services
    return services.current_zone_id()


def bridge_local_household_id():
    household = _read('household', _active_household)
    if household is None:
        return None
    return _read('household_id', lambda: household.id)


def bridge_current_zone_id():
    return _read('zone_id', _current_zone_id)


def _sim_name(sim_info):
    parts = [sim_info.first_name or '', sim_info.last_name or '']
    name = ' '.join(p.strip() for p in parts if p and p.strip())
    return name or None


def _sim_mood(sim_info):
    mood = sim_info.get_mood()
    if mood is None:
        return None, None
    name = mood.__name__
    if name.startswith('Mood_'):
        name = name[len('Mood_'):]
    return name, mood.guid64


def _sim_lot(sim_info):
    from objects import ALL_HIDDEN_REASONS
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
    if sim is None:
        return 'absent'
    return 'lot actif' if sim.is_on_active_lot() else 'hors lot'


def bridge_read_state():
    """Instantane en lecture seule. Chaque champ est lu independamment."""
    state = {
        'kind': 'state',
        'game_time': bridge_game_time(),
        'zone_id': bridge_current_zone_id(),
        'household': None,
        'household_id': None,
        'funds': None,
        'sims': [],
    }
    household = _read('household', _active_household)
    if household is None:
        log('lecture : aucun foyer actif')
        return state
    state['household'] = _read('household', lambda: household.name)
    state['household_id'] = _read('household_id', lambda: household.id)
    state['funds'] = _read('funds', lambda: household.funds.money)

    sim_infos = _read('sims', lambda: list(household.sim_info_gen())) or []
    for index, sim_info in enumerate(sim_infos[:STATE_MAX_SIMS]):
        prefix = 'sims[{}].'.format(index)
        mood = _read(prefix + 'mood', lambda: _sim_mood(sim_info))
        if mood is None:
            mood = (None, None)
        state['sims'].append({
            'name': _read(prefix + 'name', lambda: _sim_name(sim_info)),
            'mood': mood[0],
            'mood_id': mood[1],
            'lot': _read(prefix + 'lot', lambda: _sim_lot(sim_info)),
        })
    return state


def _active_sim():
    import services
    client = services.client_manager().get_first_client()
    return client.active_sim if client is not None else None


def _running_action(sim):
    running = sim.queue.running
    if running is None:
        return None
    return running.affordance.__name__


def bridge_read_position():
    """Position du Sim actif (lecture seule), ou None s'il n'y en a pas."""
    sim = _read('active_sim', _active_sim)
    if sim is None:
        return None
    position = _read('position', lambda: sim.position)
    sim_id = _read('sim_id', lambda: sim.sim_info.sim_id)
    if position is None or sim_id is None:
        return None
    return {
        'kind': 'position',
        'sim_id': sim_id,
        'name': _read('sim_name', lambda: _sim_name(sim.sim_info)),
        'zone_id': bridge_current_zone_id(),
        'x': round(float(position.x), 3),
        'y': round(float(position.y), 3),
        'z': round(float(position.z), 3),
        'level': _read('level', lambda: sim.level),
        'action': _read('action', lambda: _running_action(sim)),
    }


def _local_sim_position(sim_id):
    import services
    from objects import ALL_HIDDEN_REASONS
    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        return 'inconnu', None
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
    if sim is None:
        return 'absent', None
    position = sim.position
    return 'present', (float(position.x), float(position.y), float(position.z), sim.level)


def bridge_local_sim_position(sim_id):
    """('present', (x, y, z, niveau)), ('absent', None) : pas sur ce lot,
    ('inconnu', None) : ce Sim n'existe pas dans cette partie. None si erreur."""
    return _read('local_sim', lambda: _local_sim_position(sim_id))


# Seules ecritures du mod dans le jeu : la demande de pause (horloge) et le
# refus d'une action du joueur (file d'attente), voir l'en-tete.
PAUSE_REASON = 'Sims4MP : attente de l\'autre joueur'


def bridge_push_pause():
    """Pose une demande de pause prioritaire et la renvoie (pour la retirer)."""
    import services
    from clock import ClockSpeedMode, GameSpeedChangeSource
    return services.game_clock_service().push_speed(
        ClockSpeedMode.PAUSED, source=GameSpeedChangeSource.SITUATION,
        validity_check=None, reason=PAUSE_REASON, immediate=True)


def bridge_remove_pause(request):
    import services
    from clock import GameSpeedChangeSource
    services.game_clock_service().remove_request(
        request, source=GameSpeedChangeSource.SITUATION, reason=PAUSE_REASON, immediate=True)


def bridge_is_paused():
    import services
    from clock import ClockSpeedMode
    return services.game_clock_service().clock_speed == ClockSpeedMode.PAUSED


def bridge_refused_action():
    """Resultat renvoye par InteractionQueue.append pour une action refusee."""
    from event_testing.results import TestResult
    return TestResult(False, 'Sims4MP : en attente de l\'autre joueur.')


# ---------------------------------------------------------------------------
# Session reseau (aucun objet du jeu ici)
# ---------------------------------------------------------------------------

class NetSession(object):

    def __init__(self, role, endpoint):
        self.role = role                # 'host' ou 'client'
        self.endpoint = endpoint        # transport.Server ou transport.Client
        self.handshake_done = False
        self.peer = None
        self.close_after_flush = False  # host : deconnecter apres envoi du REJECT
        self.errors = 0
        self.polls = 0
        self.started_at = time.monotonic()
        self.next_ping_seq = 1
        self.pending_pings = {}         # client : seq -> time.monotonic() a l'envoi
        self.last_ping = None           # client : texte du dernier resultat
        # Etat (host) : dernier etat envoye, pour affichage et detection des changements.
        self.state_checked_at = 0.0
        self.state_sent = None
        self.state_sent_at = None
        self.state_sent_to_peer = None  # remis a None a chaque nouveau client
        # Etat (client) : dernier etat recu et accepte.
        self.state_received = None
        self.state_received_at = None
        self.state_warning = None
        # Presence (M2) : derniere presence recue de l'autre, dernier envoi.
        self.peer_seen_at = None
        self.presence_sent_at = 0.0
        # Positions (M3) : derniere envoyee, derniere recue de l'autre joueur.
        self.position_checked_at = 0.0
        self.position_sent = None
        self.remote_position = None
        self.remote_position_at = None


# ---------------------------------------------------------------------------
# Etat : validation et affichage (aucun objet du jeu ici)
# ---------------------------------------------------------------------------

def _clean_text(value):
    if not isinstance(value, str):
        return None
    text = ''.join(ch for ch in value if ch >= ' ' and ch != '\x7f')
    return text[:STATE_MAX_TEXT] or None


def _clean_int(value, minimum, maximum):
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if not minimum <= value <= maximum:
        return None
    return value


def validate_state(data):
    """Renvoie une copie propre de l'etat recu : tout champ invalide devient None."""
    invalid = []

    def check(name, raw, clean):
        if raw is not None and clean is None:
            invalid.append(name)
        return clean

    state = {
        'game_time': check('game_time', data.get('game_time'), _clean_text(data.get('game_time'))),
        'household': check('household', data.get('household'), _clean_text(data.get('household'))),
        'household_id': check('household_id', data.get('household_id'),
                              _clean_int(data.get('household_id'), 0, 2 ** 64)),
        'funds': check('funds', data.get('funds'),
                       _clean_int(data.get('funds'), -STATE_MAX_FUNDS, STATE_MAX_FUNDS)),
        'zone_id': check('zone_id', data.get('zone_id'), _clean_int(data.get('zone_id'), 0, 2 ** 64)),
        'sims': [],
    }
    sims = data.get('sims')
    if sims is not None and not isinstance(sims, list):
        invalid.append('sims')
        sims = []
    for index, sim in enumerate((sims or [])[:STATE_MAX_SIMS]):
        if not isinstance(sim, dict):
            invalid.append('sims[{}]'.format(index))
            continue
        prefix = 'sims[{}].'.format(index)
        lot = sim.get('lot')
        state['sims'].append({
            'name': check(prefix + 'name', sim.get('name'), _clean_text(sim.get('name'))),
            'mood': check(prefix + 'mood', sim.get('mood'), _clean_text(sim.get('mood'))),
            'mood_id': check(prefix + 'mood_id', sim.get('mood_id'),
                             _clean_int(sim.get('mood_id'), 0, 2 ** 64)),
            'lot': check(prefix + 'lot', lot, lot if lot in LOT_VALUES else None),
        })
    if sims and len(sims) > STATE_MAX_SIMS:
        invalid.append('sims (tronque a {})'.format(STATE_MAX_SIMS))
    return state, invalid


def _state_summary(state):
    return 'heure {} , argent {} , foyer {} (id {}) , zone {} , {} Sim(s)'.format(
        state.get('game_time'), state.get('funds'), state.get('household'),
        state.get('household_id'), state.get('zone_id'), len(state.get('sims') or []))


def _state_lines(state, same_zone):
    funds = state.get('funds')
    lines = [
        'Heure de jeu : {}'.format(state.get('game_time') or 'inconnue'),
        'Argent : {}'.format('{} simflouz'.format(funds) if funds is not None else 'inconnu'),
        'Foyer : {} (id {})'.format(state.get('household') or 'inconnu', state.get('household_id')),
    ]
    sims = state.get('sims') or []
    lines.append('Sims ({}) :'.format(len(sims)))
    for sim in sims:
        if sim.get('mood'):
            mood = '{} (id {})'.format(sim['mood'], sim.get('mood_id'))
        else:
            mood = 'humeur inconnue'
        if same_zone:
            lot = sim.get('lot') or 'lot inconnu'
        else:
            lot = 'zone différente'
        lines.append('  - {} : {} , {}'.format(sim.get('name') or '(sans nom)', mood, lot))
    return lines


_session = None
_pump = {'installed': False, 'calls': 0, 'last_poll': 0.0, 'error': None}


def _describe(message):
    text = repr(message.get('data'))
    if len(text) > 200:
        text = text[:200] + '...'
    return '{} {}'.format(message.get('type'), text)


def _send(session, message):
    if session.endpoint.send(message):
        log('[{}] envoi : {}'.format(session.role, _describe(message)))
    else:
        log('[{}] envoi impossible (non connecte) : {}'.format(session.role, _describe(message)))


def _handle_host_event(session, kind, value):
    server = session.endpoint
    if kind == 'connected':
        session.peer = value
        session.handshake_done = False
        # Nouveau client : il recevra l'etat complet des le handshake.
        session.state_sent_to_peer = None
        session.state_checked_at = 0.0
        session.peer_seen_at = None
        session.presence_sent_at = 0.0
        session.position_sent = None
        session.remote_position = None
    elif kind == 'disconnected':
        if session.handshake_done:
            bridge_notify('L\'autre joueur a quitté la partie. En attente d\'une nouvelle connexion…')
        session.peer_seen_at = None
        session.peer = None
        session.handshake_done = False
        session.close_after_flush = False
    elif kind == 'message':
        msg_type = value['type']
        data = value['data']
        if msg_type == protocol.HELLO:
            if data.get('protocol') == protocol.PROTOCOL_VERSION:
                _send(session, protocol.welcome('Sims4MP host ' + MOD_VERSION))
                session.handshake_done = True
                peer = session.peer[0] if isinstance(session.peer, tuple) and session.peer else '?'
                bridge_notify('Un joueur a rejoint la partie ({}).'.format(peer))
                if data.get('mod_version') != MOD_VERSION:
                    # Un mod plus ancien n'envoie pas de presence : la pause durerait.
                    bridge_notify('Versions du mod différentes (vous {}, l\'autre joueur {!s:.16}). '
                                  'Installez la même version des deux côtés.'.format(
                                      MOD_VERSION, data.get('mod_version')))
            else:
                _send(session, protocol.reject('protocole {} attendu, recu {}'.format(
                    protocol.PROTOCOL_VERSION, data.get('protocol'))))
                session.close_after_flush = True
        elif not session.handshake_done:
            log('[host] message ignore avant HELLO : ' + msg_type)
        elif msg_type == protocol.PING:
            game_time = bridge_game_time()
            _send(session, protocol.pong(data.get('seq'), data.get('sent_at'),
                                         {'game_time': game_time}))
            bridge_notify('Ping reçu du client')
        elif msg_type == protocol.EVENT:
            if data.get('kind') == 'presence':
                session.peer_seen_at = time.monotonic()
            elif data.get('kind') == 'position':
                _handle_position(session, data)
            else:
                # Le host est la seule source d'etat : rien d'autre n'est accepte du client.
                log('[host] EVENT du client ignore (kind {!r})'.format(data.get('kind')))
        elif msg_type == protocol.BYE:
            server.disconnect_client()
            session.peer = None
            session.handshake_done = False
            log('[host] client deconnecte (BYE)')


def _handle_client_event(session, kind, value):
    global _session
    client = session.endpoint
    if kind == 'connected':
        session.peer = value
    elif kind == 'disconnected':
        log('[client] session terminee')
        _session = None
        if _auto['target'] is not None:
            # Pas de nouvelle tentative en boucle : la prochaine dans 30 s au plus tot.
            _auto['next_try'] = time.monotonic() + AUTO_RETRY_INTERVAL
            if session.handshake_done:
                bridge_notify('Connexion à l\'hôte perdue. Nouvelle tentative dans {:.0f} s.'.format(
                    AUTO_RETRY_INTERVAL))
            elif _auto['attempts'] == 1:
                bridge_notify('Hôte injoignable pour l\'instant. Nouvelle tentative toutes les {:.0f} s.'.format(
                    AUTO_RETRY_INTERVAL))
    elif kind == 'message':
        msg_type = value['type']
        if msg_type == protocol.WELCOME:
            session.handshake_done = True
            bridge_notify('Connecté à l\'hôte : la partie à deux est prête.')
        elif msg_type == protocol.REJECT:
            log('[client] refuse par le host : {}'.format(value['data'].get('reason')))
            client.close()
            _session = None
        elif msg_type == protocol.PONG:
            _handle_pong(session, value['data'])
        elif msg_type == protocol.EVENT:
            if value['data'].get('kind') == 'state':
                _handle_state(session, value['data'])
            elif value['data'].get('kind') == 'presence':
                session.peer_seen_at = time.monotonic()
            elif value['data'].get('kind') == 'position':
                _handle_position(session, value['data'])
            else:
                log('[client] EVENT ignore (kind {!r})'.format(value['data'].get('kind')))
        elif msg_type == protocol.BYE:
            client.close()
            _session = None
            log('[client] host deconnecte (BYE)')


def _handle_pong(session, data):
    # La latence est calculee avec l'heure d'envoi gardee localement :
    # on ne fait pas confiance a la valeur renvoyee par le host.
    sent_at = session.pending_pings.pop(data.get('seq'), None)
    if sent_at is None:
        log('[client] PONG inattendu (seq {!r})'.format(data.get('seq')))
        return
    latency_ms = (time.monotonic() - sent_at) * 1000.0
    host_info = data.get('host_info')
    game_time = host_info.get('game_time') if isinstance(host_info, dict) else None
    if not isinstance(game_time, str):
        game_time = 'inconnue'
    result = 'Pong du host : {:.0f} ms, heure de jeu du host : {}'.format(latency_ms, game_time)
    session.last_ping = result
    log('[client] ' + result)
    bridge_notify(result)


def _handle_state(session, data):
    # Stocke en memoire le dernier etat seulement. Rien n'est ecrit dans la
    # partie ni renvoye au host.
    state, invalid = validate_state(data)
    log('[client] recu state : ' + _state_summary(state))
    if invalid:
        log('[client] champs invalides ignores : ' + ', '.join(invalid))

    local_id = bridge_local_household_id()
    host_id = state['household_id']
    if local_id is None or host_id is None:
        session.state_warning = 'Comparaison du foyer impossible (host {} , client {}).'.format(host_id, local_id)
        log('[client] ' + session.state_warning)
    elif local_id != host_id:
        session.state_warning = 'Foyer différent : le host joue « {} » (id {}), le client id {}. Etat ignoré.'.format(
            state['household'], host_id, local_id)
        log('[client] state ignore : foyer different (host {} , client {})'.format(host_id, local_id))
        return
    else:
        session.state_warning = None

    session.state_received = state
    session.state_received_at = time.monotonic()


def _maybe_send_state(session, now):
    """Host : lit et envoie l'etat au plus toutes les STATE_INTERVAL s, s'il a change."""
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.state_checked_at < STATE_INTERVAL:
        return
    session.state_checked_at = now
    state = bridge_read_state()
    if state == session.state_sent_to_peer:
        return
    # data = {"kind": "state", ...} comme demande : protocol.event() utiliserait
    # un autre format (name/payload), d'ou make_message directement.
    if session.endpoint.send(protocol.make_message(protocol.EVENT, state)):
        session.state_sent_to_peer = state
        session.state_sent = state
        session.state_sent_at = now
        log('[host] envoi state : ' + _state_summary(state))


def pump_tick():
    """Appele a chaque Zone.update. Ne bloque jamais (select timeout 0)."""
    _pump['calls'] += 1
    if _pump['calls'] == 1:
        log('pompe : premier appel de Zone.update recu')

    now = time.monotonic()
    _auto_tick(now)                       # connexion automatique, au plus toutes les 30 s
    session = _session
    if session is not None and now - _pump['last_poll'] >= PUMP_INTERVAL:
        _pump['last_poll'] = now
        _poll_session(session, now)
    _gate_tick(time.monotonic())          # pause et file : a chaque tick, meme sans session


def _poll_session(session, now):
    session.polls += 1

    for kind, value in session.endpoint.poll():
        if kind == 'message':
            # Les etats sont journalises en resume par _handle_state, les presences pas du tout.
            if value['type'] != protocol.EVENT or value['data'].get('kind') not in ('state', 'presence', 'position'):
                log('[{}] recu : {}'.format(session.role, _describe(value)))
        else:
            log('[{}] {} : {}'.format(session.role, kind, value))
        if session.role == 'host':
            _handle_host_event(session, kind, value)
        else:
            _handle_client_event(session, kind, value)

    if session.close_after_flush:
        conn = session.endpoint.conn
        if conn is None or not conn.wants_write():
            session.endpoint.disconnect_client()
            session.close_after_flush = False
            session.peer = None
            log('[host] client deconnecte apres REJECT')

    if session.role == 'host' and _session is session:
        _maybe_send_state(session, now)
    if _session is session:
        _maybe_send_presence(session, now)
        _maybe_send_position(session, now)


# ---------------------------------------------------------------------------
# Positions (M3, lecture seule)
# ---------------------------------------------------------------------------

def _clean_float(value, limit):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or not -limit <= value <= limit:      # NaN ou hors bornes
        return None
    return value


def validate_position(data):
    """Copie propre d'une position recue, ou None si elle est inutilisable."""
    if not isinstance(data, dict):
        return None
    sim_id = _clean_int(data.get('sim_id'), 1, 2 ** 64)
    coords = [_clean_float(data.get(axis), POSITION_MAX_COORD) for axis in ('x', 'y', 'z')]
    if sim_id is None or None in coords:
        return None
    return {
        'sim_id': sim_id,
        'name': _clean_text(data.get('name')),
        'zone_id': _clean_int(data.get('zone_id'), 0, 2 ** 64),
        'x': coords[0], 'y': coords[1], 'z': coords[2],
        'level': _clean_int(data.get('level'), POSITION_LEVELS[0], POSITION_LEVELS[1]),
        'action': _clean_text(data.get('action')),
    }


def _moved(old, new):
    if old is None:
        return True
    if any(old.get(k) != new.get(k) for k in ('sim_id', 'zone_id', 'level', 'action')):
        return True
    return any(abs(old[k] - new[k]) >= POSITION_MIN_MOVE for k in ('x', 'y', 'z'))


def _maybe_send_position(session, now):
    """Lit le Sim actif au plus toutes les POSITION_INTERVAL s et l'envoie s'il a change."""
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.position_checked_at < POSITION_INTERVAL:
        return
    session.position_checked_at = now
    position = bridge_read_position()
    if position is None or not _moved(session.position_sent, position):
        return
    if session.endpoint.send(protocol.make_message(protocol.EVENT, position)):
        if session.position_sent is None or session.position_sent.get('sim_id') != position['sim_id']:
            log('[{}] envoi position : Sim {} ({})'.format(session.role, position['name'], position['sim_id']))
        session.position_sent = position


def _handle_position(session, data):
    position = validate_position(data)
    if position is None:
        log('[{}] position invalide ignoree'.format(session.role))
        return
    previous = session.remote_position
    session.remote_position = position
    session.remote_position_at = time.monotonic()
    if previous is None or previous['sim_id'] != position['sim_id']:
        log('[{}] l\'autre joueur controle {} ({})'.format(session.role, position['name'], position['sim_id']))
        bridge_notify('L\'autre joueur contrôle {}.'.format(position['name'] or 'un Sim'))


def _position_text(position):
    level = position.get('level')
    return 'x {:.2f} , y {:.2f} , z {:.2f}{}'.format(
        position['x'], position['y'], position['z'], '' if level is None else ' , niveau {}'.format(level))


def position_lines(session, now):
    """Texte de mp.positions (aucun objet du jeu ici, sauf la recherche du Sim local)."""
    lines = []
    sent = session.position_sent
    if sent is None:
        lines.append('Mon Sim : aucune position envoyee')
    else:
        lines.append('Mon Sim : {} ({}) , {} , action {}'.format(
            sent['name'], sent['sim_id'], _position_text(sent), sent['action'] or 'aucune'))
    remote = session.remote_position
    if remote is None:
        lines.append('Sim de l\'autre joueur : aucune position recue')
        return lines
    lines.append('Sim de l\'autre joueur : {} ({}) , {} , action {} (il y a {:.0f} s)'.format(
        remote['name'], remote['sim_id'], _position_text(remote), remote['action'] or 'aucune',
        now - session.remote_position_at))
    if sent is not None and sent['sim_id'] == remote['sim_id']:
        lines.append('  Vous controlez tous les deux ce Sim')
    local_zone = bridge_current_zone_id()
    if local_zone is None or remote['zone_id'] != local_zone:
        lines.append('  Zone differente (autre {} , ici {}) : comparaison impossible'.format(
            remote['zone_id'], local_zone))
        return lines
    found = bridge_local_sim_position(remote['sim_id'])
    if found is None:
        lines.append('  Lecture du meme Sim ici impossible (voir le journal)')
    elif found[0] == 'inconnu':
        lines.append('  Ce Sim n\'existe pas dans cette partie : ce n\'est pas la meme sauvegarde')
    elif found[0] == 'absent':
        lines.append('  Ce Sim existe ici mais n\'est pas sur le lot')
    else:
        x, y, z, level = found[1]
        gap = ((x - remote['x']) ** 2 + (z - remote['z']) ** 2) ** 0.5
        lines.append('  Ici : x {:.2f} , y {:.2f} , z {:.2f} , niveau {} -> ecart {:.2f}'.format(
            x, y, z, level, gap))
    return lines


# ---------------------------------------------------------------------------
# Attente de l'autre joueur : presence, pause imposee, file bloquee (M2)
# ---------------------------------------------------------------------------

_gate = {
    'waiting': False,        # attente en cours (pause imposee, actions du joueur refusees)
    'request': None,         # demande de pause posee dans l'horloge du jeu
    'repushed': 0,           # demande reposee parce qu'une autre la masquait
    'refused': 0,            # actions du joueur refusees
    'notice_at': None,       # derniere notification « action refusee »
    'error': None,           # derniere erreur de l'horloge (journalisee une fois par message)
}


def _maybe_send_presence(session, now):
    """« Je suis en jeu », toutes les PRESENCE_INTERVAL s une fois le handshake fait."""
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.presence_sent_at < PRESENCE_INTERVAL:
        return
    session.presence_sent_at = now
    # Pas de journal a chaque envoi : une ligne toutes les 2 s noierait le reste.
    session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'presence'}))


def multiplayer_expected():
    """Une partie a deux est prevue : session ouverte ou reglage du lanceur actif."""
    return _session is not None or _auto['target'] is not None


def peer_in_game(now):
    session = _session
    return (session is not None and session.handshake_done and session.endpoint.is_connected
            and session.peer_seen_at is not None and now - session.peer_seen_at <= PRESENCE_TIMEOUT)


def _clock_error(where):
    text = traceback.format_exc()
    last = text.strip().splitlines()[-1]
    if _gate['error'] != last:
        log('attente : {} impossible :\n{}'.format(where, text))
    _gate['error'] = last


def _hold_pause():
    try:
        if _gate['request'] is None:
            _gate['request'] = bridge_push_pause()
            log('attente : pause imposee')
        elif not bridge_is_paused():
            # Une autre demande prioritaire masque la notre : on la repose au-dessus.
            bridge_remove_pause(_gate['request'])
            _gate['request'] = bridge_push_pause()
            _gate['repushed'] += 1
            log('attente : pause reposee ({})'.format(_gate['repushed']))
    except Exception:
        _clock_error('pause')


def _release_pause():
    request = _gate['request']
    _gate['request'] = None
    if request is None:
        return
    try:
        bridge_remove_pause(request)
        log('attente : pause levee')
    except Exception:
        _clock_error('levee de la pause')


def _gate_tick(now):
    """Appele a chaque tick : pose ou leve la pause selon la presence de l'autre."""
    if multiplayer_expected() and not peer_in_game(now):
        if not _gate['waiting']:
            _gate['waiting'] = True
            log('attente : l\'autre joueur n\'est pas en jeu')
            bridge_notify('En attente de l\'autre joueur : la partie reste en pause. '
                          '(mp.disconnect pour jouer seul)')
        _hold_pause()
    elif _gate['waiting']:
        _gate['waiting'] = False
        _release_pause()
        if multiplayer_expected():
            log('attente : les deux joueurs sont en jeu')
            bridge_notify('Les deux joueurs sont en jeu : la partie peut reprendre.')
        else:
            log('attente : partie a deux annulee')
            bridge_notify('Partie à deux arrêtée : vous jouez seul.')


def _is_user_directed(interaction):
    try:
        return bool(interaction.is_user_directed)
    except Exception:
        return False


def queue_refuses(interaction):
    """Vrai si l'action doit etre refusee : attente en cours et choix du joueur."""
    if not _gate['waiting'] or not _is_user_directed(interaction):
        return False
    _gate['refused'] += 1
    now = time.monotonic()
    if _gate['notice_at'] is None or now - _gate['notice_at'] >= QUEUE_NOTICE_INTERVAL:
        _gate['notice_at'] = now
        bridge_notify('Action refusée : l\'autre joueur n\'est pas encore en jeu.')
    return True


def _install_queue_hook():
    from interactions.interaction_queue import InteractionQueue
    original = InteractionQueue.append
    if getattr(original, '_sims4mp_hook', False):
        log('attente : file d\'attente deja enveloppee')
        return

    @functools.wraps(original)
    def append(self, interaction, *args, **kwargs):
        refused = None
        try:
            if queue_refuses(interaction):
                refused = bridge_refused_action()
        except Exception:
            # En cas d'erreur du mod, le jeu garde son comportement normal.
            log('ERREUR file d\'attente :\n' + traceback.format_exc())
        if refused is not None:
            return refused
        return original(self, interaction, *args, **kwargs)

    append._sims4mp_hook = True
    InteractionQueue.append = append
    log('attente : interactions.interaction_queue.InteractionQueue.append enveloppe')


def _safe_pump_tick():
    # Aucune exception ne doit remonter dans Zone.update.
    global _session
    try:
        pump_tick()
    except Exception:
        tb = traceback.format_exc()
        _pump['error'] = tb.strip().splitlines()[-1]
        log('ERREUR pompe :\n' + tb)
        session = _session
        if session is not None:
            session.errors += 1
            if session.errors >= MAX_PUMP_ERRORS:
                log('pompe : trop d\'erreurs, arret de la session')
                _close_session()


def _install_pump_hook():
    import zone
    original = zone.Zone.update
    if getattr(original, '_sims4mp_hook', False):
        log('pompe : deja installee')
        return

    @functools.wraps(original)
    def update(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        _safe_pump_tick()
        return result

    update._sims4mp_hook = True
    zone.Zone.update = update
    log('pompe : zone.Zone.update enveloppe')


def _close_session(send_bye=False):
    global _session
    session = _session
    _session = None
    if session is None:
        return
    try:
        if send_bye and session.endpoint.is_connected:
            _send(session, protocol.bye('deconnexion demandee'))
            # Un poll pour envoyer le BYE avant de fermer (non bloquant).
            for kind, value in session.endpoint.poll():
                log('[{}] {} : {}'.format(session.role, kind, value))
    except Exception:
        log('ERREUR envoi BYE :\n' + traceback.format_exc())
    session.endpoint.close()
    log('[{}] session fermee'.format(session.role))


def _local_ips():
    try:
        import socket
        return [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2]
                if not ip.startswith('127.')]
    except Exception:
        return []


def _parse_port(value, output):
    if value is None:
        return DEFAULT_PORT
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        output('Port invalide : {} (1 a 65535)'.format(value))
        return None
    return port


def _network_ready(output):
    if NET_IMPORT_ERROR is not None:
        output('Couche reseau indisponible (voir le journal).')
        log('couche reseau indisponible :\n' + NET_IMPORT_ERROR)
        return False
    if not _pump['installed']:
        output('Pompe non installee : ' + str(_pump['error']))
        return False
    return True


# ---------------------------------------------------------------------------
# Demarrage host / client (commun aux commandes et a la connexion automatique)
# ---------------------------------------------------------------------------

def _start_host(port):
    """Ouvre l'ecoute. Renvoie (True, None) ou (False, raison)."""
    global _session
    server = transport.Server('0.0.0.0', port)
    try:
        server.start()
    except OSError as e:
        log('host : echec ecoute port {} : {!r}'.format(port, e))
        return False, 'impossible d\'écouter sur le port {} ({})'.format(port, e)
    _session = NetSession('host', server)
    log('[host] ecoute sur 0.0.0.0:{} (IP locales : {})'.format(server.port, _local_ips()))
    return True, None


def _start_client(ip, port):
    """Connexion non bloquante a l'hote (terminee par la pompe). (True, None) ou (False, raison)."""
    global _session
    client = transport.Client(ip, port)
    try:
        client.connect()
    except OSError as e:
        log('client : echec connexion {}:{} : {!r}'.format(ip, port, e))
        return False, 'connexion impossible à {}:{} ({})'.format(ip, port, e)
    _session = NetSession('client', client)
    # Mis en file : envoye des que la connexion est etablie.
    _send(_session, protocol.hello(MOD_VERSION))
    log('[client] connexion en cours vers {}:{}'.format(ip, port))
    return True, None


# ---------------------------------------------------------------------------
# Reglage du lanceur et connexion automatique (M1)
# ---------------------------------------------------------------------------
# Le reglage est ecrit par le lanceur dans Documents\Electronic Arts\. On le
# retrouve depuis le dossier Mods (Documents\Electronic Arts\<jeu>\Mods), sans
# chemin ecrit en dur. Lecture seule : le mod n'ecrit jamais ce fichier.

_auto = {
    'target': None,          # ('host', port) ou ('join', ip, port) ; None : rien d'automatique
    'next_try': 0.0,         # time.monotonic() avant lequel on ne retente pas
    'attempts': 0,
    'last_error': None,
    'loads': 0,              # nombre de fins de chargement vues
}


def settings_path(mods_dir=None):
    """Chemin du reglage, ou None si le dossier Mods n'est pas retrouve."""
    path = os.path.abspath(mods_dir or _mods_dir)
    while True:
        if os.path.basename(path).lower() == 'mods':
            game_dir = os.path.dirname(path)          # ...\Les Sims 4
            return os.path.join(os.path.dirname(game_dir), SETTINGS_NAME)
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _valid_ipv4(text):
    """Adresse IPv4 utilisable pour se connecter (pas de module ipaddress requis)."""
    if not isinstance(text, str):
        return False
    parts = text.split('.')
    if len(parts) != 4:
        return False
    numbers = []
    for part in parts:
        if not part.isdigit() or not part.isascii() or (len(part) > 1 and part[0] == '0'):
            return False
        numbers.append(int(part))
    if any(n > 255 for n in numbers):
        return False
    if numbers == [0, 0, 0, 0] or numbers == [255, 255, 255, 255] or 224 <= numbers[0] <= 239:
        return False
    return True


def validate_settings(data):
    """(reglage, None) si valide, sinon (None, raison). Memes regles que le lanceur."""
    if not isinstance(data, dict):
        return None, 'objet JSON attendu'
    if set(data) != SETTINGS_KEYS:
        return None, 'cles attendues : role, ip, port'
    role, ip, port = data['role'], data['ip'], data['port']
    if role not in ('host', 'join'):
        return None, 'role inconnu'
    if isinstance(port, bool) or not isinstance(port, int) or not AUTO_PORT_MIN <= port <= 65535:
        return None, 'port invalide (1024 a 65535)'
    if not isinstance(ip, str):
        return None, 'ip invalide'
    ip = ip.strip()
    if role == 'join' and not _valid_ipv4(ip):
        return None, 'ip de l\'hote invalide'
    return {'role': role, 'ip': ip, 'port': port}, None


def read_settings(path):
    """(reglage, None), (None, None) si absent, ou (None, raison) si invalide."""
    if path is None or not os.path.isfile(path):
        return None, None
    try:
        if os.path.getsize(path) > SETTINGS_MAX_SIZE:
            return None, 'fichier trop grand'
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, 'illisible ({})'.format(e.__class__.__name__)
    return validate_settings(data)


def _auto_start(now):
    """Tente le demarrage prevu par le reglage. Ne bloque jamais."""
    target = _auto['target']
    if target is None or _session is not None:
        return
    _auto['attempts'] += 1
    _auto['next_try'] = now + AUTO_RETRY_INTERVAL
    if target[0] == 'host':
        ok, reason = _start_host(target[1])
        if ok:
            _auto['last_error'] = None
            bridge_notify('Vous hébergez la partie (port {}). En attente de l\'autre joueur…'.format(target[1]))
            return
    else:
        ok, reason = _start_client(target[1], target[2])
        if ok:
            _auto['last_error'] = None
            log('auto : connexion lancee vers {}:{} (tentative {})'.format(target[1], target[2], _auto['attempts']))
            return
    _auto['last_error'] = reason
    log('auto : echec ({}), nouvelle tentative dans {:.0f} s'.format(reason, AUTO_RETRY_INTERVAL))
    if _auto['attempts'] == 1:
        bridge_notify('Sims4MP : {}. Nouvelle tentative toutes les {:.0f} s.'.format(reason, AUTO_RETRY_INTERVAL))


def _auto_tick(now):
    """Appele par la pompe : relance la connexion automatique, au plus toutes les 30 s."""
    if _auto['target'] is not None and _session is None and now >= _auto['next_try']:
        _auto_start(now)


def on_zone_loaded():
    """Fin d'un chargement de partie : lit le reglage et demarre une seule fois."""
    _auto['loads'] += 1
    if NET_IMPORT_ERROR is not None or not _pump['installed']:
        log('auto : couche reseau ou pompe indisponible, rien d\'automatique')
        return
    if _session is not None:
        log('auto : session deja active ({}), rien a faire'.format(_session.role))
        return
    path = settings_path()
    settings, reason = read_settings(path)
    if settings is None:
        _auto['target'] = None
        if reason is None:
            log('auto : aucun reglage du lanceur ({}), connexion manuelle (mp.host / mp.join)'.format(path))
        else:
            log('auto : reglage ignore ({}) : {}'.format(path, reason))
            bridge_notify('Réglage Sims4MP ignoré ({}). Utilisez le lanceur, ou mp.host / mp.join.'.format(reason))
        return
    if settings['role'] == 'host':
        _auto['target'] = ('host', settings['port'])
    else:
        _auto['target'] = ('join', settings['ip'], settings['port'])
    _auto['attempts'] = 0
    log('auto : reglage lu ({}) : {}'.format(path, _auto['target']))
    _auto_start(time.monotonic())


def _safe_on_zone_loaded():
    # Aucune exception ne doit remonter dans le chargement du jeu.
    try:
        on_zone_loaded()
    except Exception:
        log('ERREUR connexion automatique :\n' + traceback.format_exc())


def _install_zone_loaded_hook():
    import zone
    original = zone.Zone.on_loading_screen_animation_finished
    if getattr(original, '_sims4mp_hook', False):
        log('auto : hook de chargement deja installe')
        return

    @functools.wraps(original)
    def on_loading_screen_animation_finished(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        _safe_on_zone_loaded()
        return result

    on_loading_screen_animation_finished._sims4mp_hook = True
    zone.Zone.on_loading_screen_animation_finished = on_loading_screen_animation_finished
    log('auto : zone.Zone.on_loading_screen_animation_finished enveloppe')


# ---------------------------------------------------------------------------
# Commandes de triche
# ---------------------------------------------------------------------------

@sims4.commands.Command('mp.hello', command_type=sims4.commands.CommandType.Live)
def mp_hello(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        log('mp.hello appele')
        results = run_network_test()
        _log_network_test(results)

        all_ok = all(ok for _, ok, _ in results)
        summary = 'Reseau : OK' if all_ok else 'Reseau : ECHEC (voir le journal)'
        lines = ['{} : {}'.format(name, 'OK' if ok else 'ECHEC') for name, ok, _ in results]

        # Sortie console de triche : fonctionne meme si la notification echoue.
        output('[{}] version {} - Hello ! {}'.format(MOD_NAME, MOD_VERSION, summary))
        for line in lines:
            output('  ' + line)
        output('Journal : ' + LOG_PATH)

        try:
            show_notification('Sims4MP', 'Hello ! ' + summary + '\n' + '\n'.join(lines))
            log('notification affichee')
        except Exception:
            log('ECHEC notification :\n' + traceback.format_exc())
            output('Notification impossible (voir le journal).')
    except Exception:
        log('ERREUR mp.hello :\n' + traceback.format_exc())
        output('Erreur dans mp.hello (voir le journal).')


@sims4.commands.Command('mp.host', command_type=sims4.commands.CommandType.Live)
def mp_host(port=None, _connection=None):
    global _session
    output = sims4.commands.CheatOutput(_connection)
    try:
        if not _network_ready(output):
            return
        if _session is not None:
            output('Session deja active ({}). Faites mp.disconnect.'.format(_session.role))
            return
        port = _parse_port(port, output)
        if port is None:
            return
        ok, reason = _start_host(port)
        if not ok:
            output('Echec : ' + reason)
            return
        server = _session.endpoint
        ips = _local_ips()
        output('Host en ecoute sur le port {}.'.format(server.port))
        # Plusieurs IP possibles (cartes virtuelles, VPN...) : on les affiche toutes.
        output('Sur le client : mp.join <ip> {}'.format(server.port))
        output('IP de ce PC : {}'.format(', '.join(ips) if ips else 'inconnues (ipconfig)'))
    except Exception:
        log('ERREUR mp.host :\n' + traceback.format_exc())
        output('Erreur dans mp.host (voir le journal).')


@sims4.commands.Command('mp.join', command_type=sims4.commands.CommandType.Live)
def mp_join(ip=None, port=None, _connection=None):
    global _session
    output = sims4.commands.CheatOutput(_connection)
    try:
        if not _network_ready(output):
            return
        if _session is not None:
            output('Session deja active ({}). Faites mp.disconnect.'.format(_session.role))
            return
        if not ip:
            output('Usage : mp.join <ip> [port]')
            return
        port = _parse_port(port, output)
        if port is None:
            return
        ok, reason = _start_client(ip, port)
        if not ok:
            output('Echec : ' + reason)
            return
        output('Connexion en cours vers {}:{}... (mp.status)'.format(ip, port))
    except Exception:
        log('ERREUR mp.join :\n' + traceback.format_exc())
        output('Erreur dans mp.join (voir le journal).')


@sims4.commands.Command('mp.status', command_type=sims4.commands.CommandType.Live)
def mp_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        output('[{}] version {}'.format(MOD_NAME, MOD_VERSION))
        output('Pompe installee : {}'.format('oui' if _pump['installed'] else 'NON'))
        output('Appels Zone.update : {}'.format(_pump['calls']))
        if _pump['error']:
            output('Derniere erreur pompe : ' + _pump['error'])
        session = _session
        if session is None:
            output('Session : aucune')
        else:
            if session.role == 'host':
                state = 'client connecte' if session.endpoint.is_connected else 'en attente d\'un client'
                output('Role : host, port {} , {}'.format(session.endpoint.port, state))
            else:
                output('Role : client, etat {}'.format(session.endpoint.state))
            output('Pair : {}'.format(session.peer))
            output('Handshake : {}'.format('OK' if session.handshake_done else 'non'))
            output('Poll effectues : {} , erreurs : {}'.format(session.polls, session.errors))
            if session.last_ping:
                output('Dernier ping : ' + session.last_ping)
        target = _auto['target']
        if target is None:
            output('Connexion automatique : aucune (reglage absent, invalide ou mp.disconnect)')
        else:
            output('Connexion automatique : {} (tentatives {}){}'.format(
                'host port {}'.format(target[1]) if target[0] == 'host' else 'join {}:{}'.format(target[1], target[2]),
                _auto['attempts'], ' , derniere erreur : ' + _auto['last_error'] if _auto['last_error'] else ''))
        if _gate['waiting']:
            output('Attente de l\'autre joueur : pause imposee, actions du joueur refusees ({})'.format(
                _gate['refused']))
        elif multiplayer_expected():
            output('Autre joueur : en jeu')
        if _gate['error']:
            output('Derniere erreur horloge : ' + _gate['error'])
        output('Reglage du lanceur : {}'.format(settings_path()))
        output('Journal : ' + LOG_PATH)
    except Exception:
        log('ERREUR mp.status :\n' + traceback.format_exc())
        output('Erreur dans mp.status (voir le journal).')


@sims4.commands.Command('mp.ping', command_type=sims4.commands.CommandType.Live)
def mp_ping(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        session = _session
        if session is None or session.role != 'client':
            output('mp.ping se lance sur le client (apres mp.join).')
            return
        if not session.handshake_done:
            output('Handshake pas encore termine (mp.status).')
            return
        seq = session.next_ping_seq
        session.next_ping_seq += 1
        # Garde-fou : on oublie les vieux pings restes sans reponse.
        if len(session.pending_pings) >= 20:
            session.pending_pings.clear()
        sent_at = time.monotonic()
        session.pending_pings[seq] = sent_at
        _send(session, protocol.ping(seq, sent_at))
        output('PING {} envoye. Resultat en notification et dans mp.status.'.format(seq))
    except Exception:
        log('ERREUR mp.ping :\n' + traceback.format_exc())
        output('Erreur dans mp.ping (voir le journal).')


@sims4.commands.Command('mp.state', command_type=sims4.commands.CommandType.Live)
def mp_state(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        session = _session
        if session is None:
            output('Aucune session active (mp.host ou mp.join).')
            return
        now = time.monotonic()
        if session.role == 'host':
            if session.state_sent is None:
                output('Aucun etat envoye pour l\'instant (il faut un client connecte).')
                return
            output('[{}] Etat envoye par ce host (il y a {:.0f} s) :'.format(
                MOD_NAME, now - session.state_sent_at))
            for line in _state_lines(session.state_sent, same_zone=True):
                output(line)
            return

        if session.state_warning:
            output('ATTENTION : ' + session.state_warning)
        state = session.state_received
        if state is None:
            output('Aucun etat recu du host pour l\'instant.')
            return
        local_zone = bridge_current_zone_id()
        same_zone = local_zone is not None and local_zone == state.get('zone_id')
        output('[{}] Etat recu du host (il y a {:.0f} s) :'.format(
            MOD_NAME, now - session.state_received_at))
        for line in _state_lines(state, same_zone=same_zone):
            output(line)
        if not same_zone:
            output('Lot non affiche : zone différente (host {} , client {}).'.format(
                state.get('zone_id'), local_zone))
    except Exception:
        log('ERREUR mp.state :\n' + traceback.format_exc())
        output('Erreur dans mp.state (voir le journal).')


@sims4.commands.Command('mp.positions', command_type=sims4.commands.CommandType.Live)
def mp_positions(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        session = _session
        if session is None or not session.handshake_done:
            output('Aucune partie a deux connectee (mp.status).')
            return
        for line in position_lines(session, time.monotonic()):
            output(line)
    except Exception:
        log('ERREUR mp.positions :\n' + traceback.format_exc())
        output('Erreur dans mp.positions (voir le journal).')


@sims4.commands.Command('mp.disconnect', command_type=sims4.commands.CommandType.Live)
def mp_disconnect(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        # La connexion automatique s'arrete aussi (jusqu'au prochain chargement de partie).
        stopped_auto = _auto['target'] is not None
        _auto['target'] = None
        if _session is None:
            _gate_tick(time.monotonic())          # leve la pause tout de suite
            output('Aucune session active.' + (' Connexion automatique arretee.' if stopped_auto else ''))
            return
        _close_session(send_bye=True)
        _gate_tick(time.monotonic())
        output('Session fermee.' + (' Connexion automatique arretee.' if stopped_auto else ''))
    except Exception:
        log('ERREUR mp.disconnect :\n' + traceback.format_exc())
        output('Erreur dans mp.disconnect (voir le journal).')


# ---------------------------------------------------------------------------
# Au chargement du mod (demarrage du jeu)
# ---------------------------------------------------------------------------

try:
    log('==== {} {} charge ===='.format(MOD_NAME, MOD_VERSION))
    _log_network_test(run_network_test())
except Exception:
    log('ERREUR au chargement :\n' + traceback.format_exc())

try:
    _install_pump_hook()
    _pump['installed'] = True
except Exception:
    _pump['error'] = traceback.format_exc().strip().splitlines()[-1]
    log('ERREUR installation pompe :\n' + traceback.format_exc())

try:
    _install_zone_loaded_hook()
except Exception:
    # Sans ce hook, mp.host / mp.join restent utilisables a la main.
    log('ERREUR installation connexion automatique :\n' + traceback.format_exc())

try:
    _install_queue_hook()
except Exception:
    # Sans ce hook, la pause reste imposee mais la file n'est pas bloquee.
    log('ERREUR installation blocage de la file :\n' + traceback.format_exc())
