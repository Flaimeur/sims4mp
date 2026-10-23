# Sims 4 Multiplayer - mp.menu (0.15.3) : ouvre la fenetre Sims4MP sans passer par la roue.
# Diagnostic menu (0.15.2) : create_pie_menu_message suivi, le journal
# note si le bouton Sims4MP est dans le message final de la roue (nom, priorite).
# mp.solo (0.15.1) : jouer seul jusqu'a la fermeture du jeu (session
# fermee, pause levee, reglage du lanceur ignore aux chargements suivants).
# Latence (0.15.0) : TCP_NODELAY regle par le mod sur la socket connectee
# (transport.py inchange), envoi immediat en fin de passage de pompe et au clic (ordres,
# annulations) via Connection.handle_write, pompe toutes les 20 ms au lieu de 50.
# Diagnostic menu (0.14.4) : l'erreur avalee par ProtocolBufferRollback
# pendant la construction d'un bouton de la roue (create_pie_menu_message) est notee.
# Diagnostic menu (0.14.3) : ChoiceMenu.add_potential_aops / add_aop
# sont suivis pour noter dans le journal si l'entree est proposee a la roue Maj + clic et
# la raison d'un refus du jeu (une ligne par situation differente).
# Correctif menu (0.14.2) : tests regles de la base remplaces par des
# listes vides (event_testing.tests.TestList) au lieu de couper _tunable_tests_enabled, qui
# faisait planter Interaction.test (UnboundLocalError target_result, entree cachee en 0.14.1).
# Correctif menu (0.14.1) : la base de « Sims4MP… » n'est plus un
# selecteur (PickerSuperInteractionMixin.potential_interactions : roue vide = entree cachee)
# et l'entree reste disponible quand la sauvegarde est verrouillee (allow_while_save_locked).
# Annulation (0.14.0) : chaque ordre envoye ou rejoue est relie a
# l'action du jeu correspondante ; la croix du joueur (Interaction.cancel_user, appele
# par interaction_commands.cancel_common) sur une action reliee envoie l'annulation,
# que l'autre PC applique avec interaction.cancel(FinishingType.USER_CANCEL)
# (action rejouee obtenue par EnqueueResult.interaction).
# Correctifs (0.13.1) : une action n'est envoyee qu'apres avoir
# ete acceptee par la file du jeu ; actions autonomes limitees (1 par Sim et par
# seconde, pas la meme deux fois en 20 s) ; voyages jamais rejoues (l'autre joueur
# est prevenu) ; pings automatiques et refus d'autonomie moins bavards au journal.
# Fiabilite (0.13.0) : chez l'invite connecte, la sauvegarde est
# verrouillee par le verrou du jeu (persistence_service.lock_save) ; resynchro
# complete depuis le menu (et d'office a chaque nouvelle connexion) ; toutes les
# 30 s l'hote envoie un resume (argent, heure, Sims presents et positions) que
# l'invite compare, alerte et rapport des ecarts aux deux ; journal tourne au-dela
# de 2 Mo (sims4mp.old.log) ; menu « Enregistrer un rapport » (sims4mp_rapport.txt).
# Notifications plus claires (0.12.0) : role de l'autre joueur
# (hote / invite) et portrait du Sim concerne, regroupement des notifications
# repetees, resume a la connexion (role, version, ping, Sim de l'autre), ping
# silencieux toutes les 10 s ; alertes de desynchro (titre « Sims4MP · alerte »,
# urgentes) : heure fortement recalee, action non rejouee, Sim present d'un seul
# cote, connexion lente.
# Menu Sims4MP (0.11.0) : Maj + clic sur le sol (triches du
# jeu actives) -> « Sims4MP… » : niveau des notifications, etat de la partie,
# jouer seul. Les commandes mp.* restent en secours.
# Etape M6 : chaque Sim a un PC qui fait foi (l'invite pour
# le Sim qu'il controle, l'hote pour tous les autres : famille, PNJ). Ce PC envoie
# ses positions, ses besoins et aussi les actions choisies par son autonomie
# (SOURCE_AUTONOMY) ; l'autre PC refuse l'autonomie de ce Sim et rejoue ces actions
# (SOURCE_SCRIPT, Priority.Low). Sims presents : services.sim_info_manager()
# .instanced_sims_gen() (verifie dans simulation.zip). Les PNJ presents d'un seul
# cote ne sont pas crees chez l'autre.
# Etape M5 : chaque action choisie au menu par un joueur
# (marcher, s'asseoir, dormir, discuter...) est envoyee au clic et rejouee sur
# l'autre PC ; besoins du Sim controle recopies chez l'autre (le PC qui
# controle le Sim fait foi, l'hote si les deux controlent le meme).
# Etape M4 : synchro en jeu de l'argent (gains et depenses
# des deux cotes), de l'heure et de la vitesse (celles de l'hote) et des
# positions (le double du Sim de l'autre joueur marche jusqu'a lui).
# M3 : chaque joueur envoie la position de son Sim
# actif (mp.positions). M2 : pause imposee tant que les deux
# joueurs ne sont pas en jeu, file d'attente bloquee pendant l'attente. M1 : role lu
# depuis le lanceur, connexion automatique, notifications ; etat en lecture
# seule (mp.state).
# Compatible Python 3.7 (version embarquee par Les Sims 4) : pas de walrus,
# pas de match, pas d'annotations avancees.
#
# Commandes : mp.hello, mp.host [port], mp.join <ip> [port], mp.status,
#             mp.ping, mp.state, mp.positions, mp.traffic [on|off], mp.disconnect
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
#
# Synchro (M4). API verifiees dans simulation.zip :
#   argent  household.funds (FamilyFunds) : .money, .add(montant, raison, sim),
#           .try_remove(montant, raison, sim, require_full_amount) ; raison
#           Consts_pb2.TELEMETRY_MONEY_CHEAT, comme sims.modify_funds / motherlode.
#           Chaque PC envoie la difference de solde vue depuis la derniere
#           lecture (EVENT money, delta) ; l'autre l'applique. A la connexion,
#           l'hote envoie son solde et l'invite s'y aligne une fois.
#   heure   services.game_clock_service().now().absolute_seconds() (secondes de
#           jeu), .advance_game_time(hours, minutes, seconds), .clock_speed ;
#           ClockSpeedMode(valeur) et ClockSpeedMode.values comme
#           clock_commands.set_speed_internal / set_clock_speed. L'hote envoie
#           heure et vitesse ; l'invite avance son heure s'il est en retard,
#           se met en pause s'il est en avance, et prend la vitesse de l'hote
#           (demande SITUATION, comme la pause de M2). Ecart tolere : 1,5 s reelle
#           au rythme mesure de l'horloge de l'hote (au moins 20 s de jeu).
#           Boutons de vitesse de l'invite : GameClock.set_clock_speed / push_speed /
#           pop_speed sont enveloppes ; une demande en source GAMEPLAY (clock_commands :
#           set_speed, request_pause, unrequest_pause) part a l'hote, qui l'applique
#           avec set_clock_speed(..., source=GAMEPLAY) comme set_speed_internal.
#   marche  comme la commande du jeu sims.gohere (server_commands/sim_commands) :
#           sims4.math.Vector3, routing.SurfaceIdentifier(zone, niveau,
#           SurfaceType.SURFACETYPE_WORLD), _build_terrain_interaction_target_and_context
#           (sim, pos, surface, PickType.PICK_TERRAIN, objects.terrain.TerrainPoint)
#           puis sim.push_super_affordance(CommandTuning.TERRAIN_GOHERE_AFFORDANCE,
#           cible, contexte) ; teleportation : TERRAIN_TELEPORT_AFFORDANCE (sims.teleport).
#           Les deux joueurs peuvent controler le meme Sim : le dernier ordre donne
#           gagne. Les ordres du joueur sont notes dans InteractionQueue.append
#           (interaction.is_user_directed, file de queue.sim) ; chaque position part
#           avec l'age du dernier ordre local a ce Sim. Le double ne suit l'autre que
#           si son ordre est plus recent ; sans ordre de part et d'autre, l'autre
#           joueur mene son Sim, et pour un Sim controle des deux cotes c'est l'hote.
#
# Ordres (M5). Dans InteractionQueue.append, une interaction du joueur
# (interaction.source == InteractionContext.SOURCE_PIE_MENU, affordance.is_super)
# part aussitot : Sim (queue.sim.sim_info.sim_id), action (affordance.guid64) et
# cible (objet .id, Sim, ou point de terrain ; une partie d'objet -> part_owner).
# L'autre PC retrouve l'action par services.get_instance_manager(Types.INTERACTION)
# et la cible par services.object_manager() / sim_info_manager(), puis
# sim.push_super_affordance(action, cible, InteractionContext(sim,
# SOURCE_SCRIPT_WITH_USER_INTENT, Priority.High)) ; pour le terrain, le meme
# contexte que sims.gohere. Chaque ordre a un identifiant : jamais rejoue deux fois.
# Besoins : sim_info.commodity_tracker.get_all_commodities() filtre is_visible et
# hors competences (comme household_commands._set_motive_decay), envoyes toutes
# les 5 s par le PC qui fait foi, ecrits par tracker.set_value(stat.stat_type, v).
#
# Prototype P1 (simulation unique, lecture seule) : mp.traffic on mesure ce que
# la simulation envoie a l'affichage. Verifie dans simulation.zip :
# server.client.Client.send_message(msg_id, msg) appelle omega.send(client.id,
# msg_id, msg.SerializeToString()) ; omega.send appelle le natif _omega.send et
# leve KeyError pour une session inconnue. Le mod enveloppe omega.send pour
# compter messages et octets par type (noms MSG_* de Consts_pb2) et par
# session, puis appelle l'original sans rien changer.

import functools
import json
import os
import time
import traceback
import weakref

import sims4.commands

MOD_NAME = 'sims4mp'
MOD_VERSION = '0.15.3'
LOG_FILE_NAME = 'sims4mp.log'
DEFAULT_PORT = 7777
PUMP_INTERVAL = 0.02     # secondes reelles minimum entre deux poll() (0.15.0 : 0.05 avant)
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
MONEY_INTERVAL = 0.5                      # secondes reelles entre deux lectures de l'argent
MONEY_MAX_DELTA = 10 ** 9
CLOCK_INTERVAL = 1.0                      # host : envoi de l'heure et de la vitesse
CLOCK_TOLERANCE_REAL = 1.5                # ecart toléré : 1,5 s reelle de temps de l'hote...
CLOCK_MIN_TOLERANCE = 20.0                # ... et au moins 20 s de jeu
CLOCK_DEFAULT_RATE = 60.0                 # s de jeu par s reelle tant que le rythme n'est pas mesure
PLAYER_SPEEDS = (0, 1, 2, 3)              # ClockSpeedMode : pause, normale, 2, 3 (boutons du joueur)
CLOCK_CONFIRM = 2                         # messages de suite au-dela de la tolerance avant correction
CLOCK_GRACE = 3.0                         # s reelles sans correction apres un changement de vitesse
AUTO_PING_INTERVAL = 10.0                 # invite : ping silencieux pour mesurer la latence
SLOW_RTT_MS = 400.0                       # au-dela : alerte « connexion lente »
SUMMARY_DELAY = 4.0                       # resume de connexion, une fois les premieres infos recues
ALERT_CLOCK_JUMP = 300.0                  # heure recalee de plus (s de jeu) : alerte
DIGEST_INTERVAL = 30.0                    # hote : resume de la partie pour le detecteur d'ecarts
DIGEST_MAX_SIMS = 64
DIGEST_TIME_GAP = 600.0                   # ecart d'heure signale au-dela (s de jeu)
DIGEST_FAR = 3.0                          # Sim « loin de sa place » au-dela
LOG_MAX_SIZE = 2 * 1024 * 1024            # journal plus gros au chargement : sims4mp.old.log
REPORT_NAME = 'sims4mp_rapport.txt'
REPORT_LOG_LINES = 200
AUTO_ORDER_GAP = 1.0                      # au plus une action autonome envoyee par Sim et par seconde
AUTO_ORDER_REPEAT = 20.0                  # meme action autonome du meme Sim : pas renvoyee avant
AUTO_FAIL_LOG = 60.0                      # refus d'action autonome : une ligne par action et par minute
LINKS_MAX = 300                           # actions reliees a un ordre gardees (annulation)
SPEED_REQUEST_DEDUP = 1.0                 # meme vitesse demandee a moins d'1 s d'intervalle : une seule
WALK_MIN = 0.75                           # ecart minimal (unites du jeu) pour faire marcher le double
WALK_RETARGET = 0.5                       # nouvelle destination si elle a bouge d'au moins
WALK_RETRY = 3.0                          # secondes reelles avant de redonner le meme ordre
WALK_TIMEOUT = 15.0                       # toujours loin apres : teleportation
TELEPORT_DIST = 40.0                      # plus loin, ou autre niveau : teleportation directe
ORDER_MAX_AGE = 3600.0                    # ordre plus ancien : comme s'il n'y en avait pas
ACTION_HOLD = 20.0                        # apres une action rejouee, le double n'est pas recale
PLACE_MIN = 5.0                           # pose directe seulement au-dela de cet ecart
SIMS_MAX = 32                             # Sims par message de positions (M6)
ORDERS_SEEN_MAX = 500                     # identifiants d'ordres deja rejoues gardes en memoire
NEEDS_INTERVAL = 5.0                      # secondes reelles entre deux envois des besoins
NEEDS_RESEND = 30.0                       # renvoi complet meme sans changement
NEEDS_EPSILON = 1.0                       # ecart minimal (sur ~ -100..100) pour envoyer ou ecrire
NEEDS_MAX = 64                            # besoins acceptes par message
NEEDS_LIMIT = 100000.0


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

def show_notification(title, text, sim_id=None, urgent=False):
    # Meme appel que la commande du jeu ui_dialog_notification_test
    # (server_commands/ui_commands.pyc), mais sans _connection : on prend le
    # premier client, comme le font de nombreux scripts du jeu. Portrait du Sim :
    # show_dialog(icon_override=IconInfoData(obj_instance=sim)), transmis a build_msg ;
    # alerte : reglage urgency = UiDialogNotificationUrgency.URGENT (verifies dans simulation.zip).
    import services
    from sims4.localization import LocalizationHelperTuning
    from ui.ui_dialog_notification import UiDialogNotification

    client = services.client_manager().get_first_client()
    owner = client.active_sim if client is not None else None
    options = {}
    if urgent:
        options['urgency'] = UiDialogNotification.UiDialogNotificationUrgency.URGENT
    dialog = UiDialogNotification.TunableFactory().default(
        owner,
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text),
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        **options
    )
    icon = None
    if sim_id is not None:
        from distributor.shared_messages import IconInfoData
        from objects import ALL_HIDDEN_REASONS
        sim_info = services.sim_info_manager().get(sim_id)
        sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if sim_info is not None else None
        if sim is not None:
            icon = IconInfoData(obj_instance=sim)
    if icon is not None:
        dialog.show_dialog(icon_override=icon)
    else:
        dialog.show_dialog()


NOTIFY_LEVELS = ('tout', 'important', 'rien')
NOTIFY_REPEAT = 30.0                      # meme notification (meme cle) au plus une fois par 30 s
ALERT_REPEAT = 120.0                      # meme alerte au plus une fois par 2 min
_notify = {'level': 'tout', 'hidden': 0, 'last': {}, 'grouped': 0}


def bridge_notify(text, important=True, sim_id=None, alert=False, key=None):
    """Notification protegee : une erreur est journalisee, jamais propagee. Le niveau choisi
    dans le menu Sims4MP filtre : « important » cache les secondaires, « rien » cache tout.
    sim_id : portrait du Sim concerne. alert : alerte de desynchro (titre et urgence).
    key : notifications de meme cle regroupees (une seule par 30 s, 2 min pour une alerte)."""
    level = _notify['level']
    if level == 'rien' or (level == 'important' and not important):
        _notify['hidden'] += 1
        log('notification masquee ({}) : {}'.format(level, text))
        return False
    if key is not None:
        now = time.monotonic()
        last = _notify['last'].get(key)
        if last is not None and now - last < (ALERT_REPEAT if alert else NOTIFY_REPEAT):
            _notify['grouped'] += 1
            log('notification regroupee ({}) : {}'.format(key, text))
            return False
        _notify['last'][key] = now
    try:
        show_notification('Sims4MP · alerte' if alert else 'Sims4MP', text, sim_id, alert)
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


# --- Synchro (M4) : lectures et ecritures, voir l'en-tete -------------------

def bridge_funds():
    """(id du foyer actif, solde) ou None."""
    household = _active_household()
    if household is None:
        return None
    return household.id, int(household.funds.money)


def bridge_apply_funds(delta):
    """Ajoute (delta > 0) ou retire (delta < 0) de l'argent au foyer actif ; renvoie le nouveau solde."""
    from protocolbuffers import Consts_pb2
    household = _active_household()
    funds = household.funds
    sim = _active_sim()
    if delta > 0:
        funds.add(delta, Consts_pb2.TELEMETRY_MONEY_CHEAT, sim)
    elif delta < 0:
        funds.try_remove(-delta, Consts_pb2.TELEMETRY_MONEY_CHEAT, sim, require_full_amount=False)
    return int(funds.money)


def bridge_clock():
    """(secondes de jeu depuis le debut, vitesse) de l'horloge locale."""
    import services
    clock = services.game_clock_service()
    return float(clock.now().absolute_seconds()), int(clock.clock_speed)


def bridge_advance_clock(seconds):
    import services
    services.game_clock_service().advance_game_time(0, 0, int(seconds))


def bridge_valid_speed(value):
    from clock import ClockSpeedMode
    return value in ClockSpeedMode.values


def bridge_push_speed(value):
    import services
    from clock import ClockSpeedMode, GameSpeedChangeSource
    return services.game_clock_service().push_speed(
        ClockSpeedMode(value), source=GameSpeedChangeSource.SITUATION,
        validity_check=None, reason='Sims4MP : vitesse de l\'hote', immediate=True)


def _terrain_target(sim, x, y, z, level):
    import routing
    import services
    import sims4.math
    from objects.terrain import TerrainPoint
    from server.pick_info import PickType
    from server_commands.sim_commands import _build_terrain_interaction_target_and_context
    position = sims4.math.Vector3(x, y, z)
    surface = routing.SurfaceIdentifier(services.current_zone_id(), level or 0,
                                        routing.SurfaceType.SURFACETYPE_WORLD)
    return _build_terrain_interaction_target_and_context(sim, position, surface, PickType.PICK_TERRAIN,
                                                         TerrainPoint)


def bridge_place_sim(sim_id, x, y, z, level):
    """Repli : pose le Sim a la position (ClientObjectMixin.move_to -> Location.clone(translation,
    routing_surface), verifie dans simulation.zip). Renvoie True si fait."""
    import routing
    import services
    import sims4.math
    from objects import ALL_HIDDEN_REASONS
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if sim_info is not None else None
    if sim is None:
        return False
    surface = routing.SurfaceIdentifier(services.current_zone_id(), level or 0,
                                        routing.SurfaceType.SURFACETYPE_WORLD)
    sim.move_to(translation=sims4.math.Vector3(x, y, z), routing_surface=surface)
    return True


def bridge_player_speed():
    """Vitesse demandee par les boutons du joueur (derniere demande GAMEPLAY), ou None."""
    import services
    from clock import GameSpeedChangeSource
    requests = services.game_clock_service().speed_controllers[GameSpeedChangeSource.GAMEPLAY]
    return int(requests[-1].speed) if len(requests) else None


def bridge_set_player_speed(value):
    """Comme le bouton de vitesse du joueur (clock_commands.set_speed_internal)."""
    import services
    from clock import ClockSpeedMode, GameSpeedChangeSource
    services.game_clock_service().set_clock_speed(
        ClockSpeedMode(value), source=GameSpeedChangeSource.GAMEPLAY,
        reason='Sims4MP : vitesse demandee par l\'autre joueur', immediate=True)


# --- Ordres des joueurs (M5) et besoins ----------------------------------------

def bridge_interaction_kind(interaction):
    """'pie' : choisie au menu par le joueur ; 'auto' : decidee par l'autonomie ; None : autre."""
    from interactions.context import InteractionContext
    source = interaction.source
    if source == InteractionContext.SOURCE_PIE_MENU:
        return 'pie'
    if source == InteractionContext.SOURCE_AUTONOMY:
        return 'auto'
    return None


def bridge_instanced_sim_ids():
    """Identifiants des Sims presents (instancies, visibles) dans la zone."""
    import services
    return [sim.sim_info.sim_id for sim in services.sim_info_manager().instanced_sims_gen()]


def bridge_sim_snapshot(sim_id):
    """Position et action en cours d'un Sim present, comme bridge_read_position, ou None."""
    import services
    from objects import ALL_HIDDEN_REASONS
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if sim_info is not None else None
    if sim is None:
        return None
    position = sim.position
    return {
        'sim_id': sim_id,
        'name': _read('sim_name', lambda: _sim_name(sim_info)),
        'zone_id': bridge_current_zone_id(),
        'x': round(float(position.x), 3), 'y': round(float(position.y), 3), 'z': round(float(position.z), 3),
        'level': _read('level', lambda: sim.level),
        'action': _read('action', lambda: _running_action(sim)),
    }


def bridge_order_from_interaction(queue, interaction, kind='pie'):
    """Description d'une action pour la rejouer ailleurs, ou None. kind 'pie' : choisie au menu
    (SOURCE_PIE_MENU) ; 'auto' : decidee par l'autonomie (SOURCE_AUTONOMY). Super-interactions seules."""
    if bridge_interaction_kind(interaction) != kind:
        return None
    affordance = interaction.affordance
    if not getattr(affordance, 'is_super', False):
        return None
    target = interaction.target
    if target is None:
        where = {'t': 'none'}
    elif getattr(target, 'is_terrain', False):
        position = target.position
        where = {'t': 'terrain', 'x': float(position.x), 'y': float(position.y), 'z': float(position.z),
                 'level': target.level}
    elif getattr(target, 'is_sim', False):
        where = {'t': 'sim', 'id': target.sim_info.sim_id}
    else:
        if getattr(target, 'is_part', False):
            target = target.part_owner                 # le jeu choisit la place (canape, lit double...)
        where = {'t': 'obj', 'id': target.id}
    return {'sim_id': queue.sim.sim_info.sim_id, 'affordance': affordance.guid64,
            'name': affordance.__name__, 'target': where, 'auto': kind == 'auto'}


def bridge_replay_order(sim_id, affordance_id, where, auto=False):
    """Rejoue l'ordre : meme Sim, meme action, meme cible. Renvoie (True, None) ou (False, raison).
    Ordre du joueur : contexte SOURCE_SCRIPT_WITH_USER_INTENT, priorite haute ; action de
    l'autonomie : SOURCE_SCRIPT, priorite basse (comme une decision du Sim, pas un ordre)."""
    import services
    import sims4.resources
    from interactions.context import InteractionContext
    from interactions.priority import Priority
    from objects import ALL_HIDDEN_REASONS
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if sim_info is not None else None
    if sim is None:
        return False, 'Sim absent ici'
    affordance = services.get_instance_manager(sims4.resources.Types.INTERACTION).get(affordance_id)
    if affordance is None:
        return False, 'action inconnue ici (pack ou mod different ?)'
    kind = where['t']
    if kind == 'terrain':
        target, context = _terrain_target(sim, where['x'], where['y'], where['z'], where['level'])
    else:
        if kind == 'none':
            target = None
        elif kind == 'sim':
            other = services.sim_info_manager().get(where['id'])
            target = other.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if other is not None else None
        else:
            target = services.object_manager().get(where['id'])
        if kind != 'none' and target is None:
            return False, 'cible absente ici (objet cree apres le chargement ?)'
        if auto:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
        else:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, Priority.High)
    result = sim.push_super_affordance(affordance, target, context)
    if not result:
        return False, 'refusee par le jeu ({})'.format(result)
    # EnqueueResult.interaction (event_testing/results.pyc) : l'action rejouee, pour l'annulation.
    return True, getattr(result, 'interaction', None)


def bridge_cancel_interaction(interaction):
    """Annule comme la croix du joueur (FinishingType.USER_CANCEL), sans fenetre de confirmation."""
    from interactions.interaction_finisher import FinishingType
    if getattr(interaction, 'is_finishing', False):
        return False
    interaction.cancel(FinishingType.USER_CANCEL, cancel_reason_msg='Sims4MP : annulee par l\'autre joueur')
    return True


def bridge_read_needs(sim_id):
    """Besoins visibles du Sim (commodites is_visible, hors competences) : {guid64: valeur}."""
    import services
    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        return None
    values = {}
    for stat in sim_info.commodity_tracker.get_all_commodities():
        if getattr(stat, 'is_visible', False) and not getattr(stat, 'is_skill', False):
            values[int(stat.guid64)] = float(stat.get_value())
    return values


def bridge_write_needs(sim_id, values):
    """Recopie des besoins recus ; ne touche que les commodites deja presentes. Renvoie le nombre ecrit."""
    import services
    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        return 0
    tracker = sim_info.commodity_tracker
    written = 0
    for stat in tracker.get_all_commodities():
        if not getattr(stat, 'is_visible', False) or getattr(stat, 'is_skill', False):
            continue
        value = values.get(int(stat.guid64))
        if value is not None and abs(float(stat.get_value()) - value) > NEEDS_EPSILON:
            tracker.set_value(stat.stat_type, value)
            written += 1
    return written


def bridge_move_sim(sim_id, x, y, z, level, teleport):
    """Fait marcher (ou teleporte) le Sim sim_id vers la position. Renvoie True si l'ordre est accepte."""
    import services
    from objects import ALL_HIDDEN_REASONS
    from server_commands.sim_commands import CommandTuning
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS) if sim_info is not None else None
    if sim is None:
        return False
    target, context = _terrain_target(sim, x, y, z, level)
    affordance = CommandTuning.TERRAIN_TELEPORT_AFFORDANCE if teleport else CommandTuning.TERRAIN_GOHERE_AFFORDANCE
    return bool(sim.push_super_affordance(affordance, target, context))


# Attente (M2) : la demande de pause (horloge) et le refus d'une action du
# joueur (file d'attente), voir l'en-tete.
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


def bridge_paused_value():
    from clock import ClockSpeedMode
    return int(ClockSpeedMode.PAUSED)


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
        # Notifications plus claires (0.12.0) : latence, resume a la connexion.
        self.rtt_ms = None
        self.nodelay_sock = None          # socket deja reglee en TCP_NODELAY (0.15.0)
        self.auto_pings = set()
        self.auto_ping_at = 0.0
        self.summary_due = None
        # Fiabilite (0.13.0) : resynchro, detecteur d'ecarts.
        self.resyncs = 0
        self.digest_sent_at = 0.0
        self.last_gaps = None
        # Actions autonomes (0.13.1) : envoi limite, refus journalises avec parcimonie.
        self.auto_sent = {}             # sim_id -> (moment, signature) du dernier envoi
        self.auto_skipped = 0
        self.auto_failed_logged = {}    # nom d'action -> moment de la derniere ligne de journal
        self.cancels_sent = 0           # annulations (D1)
        self.cancels_applied = 0
        # Positions (M3) : derniere envoyee, derniere recue de l'autre joueur.
        self.position_checked_at = 0.0
        self.position_sent = None
        self.remote_position = None
        self.remote_position_at = None
        self._reset_sync()

    def _reset_sync(self):
        # Synchro (M4) : remise a zero a chaque nouvel autre joueur.
        self.money_checked_at = 0.0
        self.money_household = None     # foyer dont le solde est suivi
        self.money_known = None         # solde a la derniere lecture (ou apres application)
        self.money_total_sent = False   # host : solde envoye pour l'alignement initial
        self.money_aligned = False      # invite : aligne sur le solde de l'hote
        self.money_sent = 0             # nombre de differences envoyees / appliquees
        self.money_applied = 0
        self.clock_sent_at = 0.0
        self.host_clock = None          # invite : (secondes, vitesse, recu_a) de l'hote
        self.host_rate = None           # rythme mesure de l'horloge de l'hote (s de jeu / s reelle)
        self.clock_ahead = False
        self.clock_jumps = 0
        self.last_gap = None
        self.clock_strikes = 0          # messages de suite avec un ecart au-dela de la tolerance
        self.clock_grace_until = 0.0    # pas de correction d'heure avant (changement de vitesse)
        self.clock_prev = None          # hote : (secondes, moment, vitesse) de la derniere mesure
        self.clock_rate = None          # hote : rythme mesure de son horloge
        self.speed_requests = 0         # demandes de vitesse envoyees (invite) ou appliquees (hote)
        self.last_speed_request = None  # invite : (vitesse, moment) de la derniere demande envoyee
        self.walk = None                # dernier ordre de marche donne au double
        self.walks = 0
        self.teleports = 0
        self.walk_status = 'aucune position recue'
        # Ordres des joueurs (M5) et besoins.
        self.order_counter = 0
        self.orders_seen = []           # identifiants deja rejoues (anti double comptage)
        self.orders_sent = 0
        self.orders_replayed = 0
        self.orders_failed = 0
        self.last_order = None          # texte du dernier ordre rejoue ou refuse
        self.action_hold = {}           # sim_id -> moment jusqu'auquel le double n'est pas recale
        self.needs_checked_at = 0.0
        self.needs_sent = {}            # sim_id -> (valeurs, moment) du dernier envoi
        self.needs_written = 0
        # Autres Sims (M6) : l'hote fait foi pour tous ceux que personne ne controle.
        self.autonomy_refused = 0       # actions autonomes refusees ici (l'autre PC fait foi)
        self.sims_checked_at = 0.0
        self.sims_sent = {}             # sim_id -> derniere position envoyee
        self.sims_remote = {}           # sim_id -> derniere position recue
        self.sims_walk = {}             # sim_id -> marche en cours
        self.sims_status = {}           # sim_id -> dernier etat
        self.sims_followed_at = 0.0


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
        session._reset_sync()
    elif kind == 'disconnected':
        if session.handshake_done:
            bridge_notify('L\'invité a quitté la partie. En attente d\'une nouvelle connexion…',
                          sim_id=session.remote_position['sim_id'] if session.remote_position else None)
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
                bridge_notify('L\'invité a rejoint la partie ({}).'.format(peer))
                session.summary_due = time.monotonic() + SUMMARY_DELAY
                if data.get('mod_version') != MOD_VERSION:
                    # Un mod plus ancien n'envoie pas de presence : la pause durerait.
                    bridge_notify('Versions du mod différentes (vous {}, l\'invité {!s:.16}). '
                                  'Installez la même version des deux côtés.'.format(
                                      MOD_VERSION, data.get('mod_version')), alert=True)
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
            if not data.get('auto'):
                bridge_notify('Ping reçu de l\'invité', important=False)
        elif msg_type == protocol.EVENT:
            if data.get('kind') == 'presence':
                session.peer_seen_at = time.monotonic()
                _note_rtt(session, data.get('rtt'))
            elif data.get('kind') == 'position':
                _handle_position(session, data)
            elif data.get('kind') == 'money':
                _handle_money(session, data)
            elif data.get('kind') == 'speed_request':
                _handle_speed_request(session, data)
            elif data.get('kind') == 'order':
                _handle_order(session, data)
            elif data.get('kind') == 'needs':
                _handle_needs(session, data)
            elif data.get('kind') == 'sims':
                _handle_sims(session, data)
            elif data.get('kind') == 'resync_request':
                do_resync(session)
            elif data.get('kind') == 'travel':
                _handle_travel(session, data)
            elif data.get('kind') == 'cancel':
                _handle_cancel(session, data)
            elif data.get('kind') == 'gaps':
                _handle_gaps(session, data)
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
            session.summary_due = time.monotonic() + SUMMARY_DELAY
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
                _note_rtt(session, value['data'].get('rtt'))
            elif value['data'].get('kind') == 'position':
                _handle_position(session, value['data'])
            elif value['data'].get('kind') == 'money':
                _handle_money(session, value['data'])
            elif value['data'].get('kind') == 'clock':
                _handle_clock(session, value['data'])
            elif value['data'].get('kind') == 'order':
                _handle_order(session, value['data'])
            elif value['data'].get('kind') == 'needs':
                _handle_needs(session, value['data'])
            elif value['data'].get('kind') == 'sims':
                _handle_sims(session, value['data'])
            elif value['data'].get('kind') == 'resync':
                _handle_resync(session)
            elif value['data'].get('kind') == 'travel':
                _handle_travel(session, value['data'])
            elif value['data'].get('kind') == 'cancel':
                _handle_cancel(session, value['data'])
            elif value['data'].get('kind') == 'digest':
                _handle_digest(session, value['data'])
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
    if data.get('seq') in session.auto_pings:
        # Ping automatique : latence gardee (resume, alerte de connexion lente), sans notification.
        session.auto_pings.discard(data.get('seq'))
        _note_rtt(session, latency_ms)
        return
    _note_rtt(session, latency_ms)
    host_info = data.get('host_info')
    game_time = host_info.get('game_time') if isinstance(host_info, dict) else None
    if not isinstance(game_time, str):
        game_time = 'inconnue'
    result = 'Pong du host : {:.0f} ms, heure de jeu du host : {}'.format(latency_ms, game_time)
    session.last_ping = result
    log('[client] ' + result)
    bridge_notify(result, important=False)


# -- latence, resume de connexion (notifications plus claires) --

def _note_rtt(session, value):
    """Garde la latence (ms) mesuree par l'invite ; alerte si la connexion est lente."""
    rtt = _clean_float(value, 600000.0)
    if rtt is None or rtt < 0:
        return
    session.rtt_ms = rtt
    if rtt > SLOW_RTT_MS:
        bridge_notify('Connexion lente avec {} : {:.0f} ms. Les actions peuvent arriver en retard.'.format(
            _other_label(session), rtt), alert=True, key='slow')


def _other_label(session):
    return 'l\'invité' if session.role == 'host' else 'l\'hôte'


def _auto_ping_tick(session, now):
    """Invite : un ping silencieux toutes les AUTO_PING_INTERVAL s pour mesurer la latence."""
    if session.role != 'client' or not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.auto_ping_at < AUTO_PING_INTERVAL:
        return
    session.auto_ping_at = now
    seq = session.next_ping_seq
    session.next_ping_seq += 1
    if len(session.pending_pings) >= 20:
        session.pending_pings.clear()
        session.auto_pings.clear()
    session.pending_pings[seq] = now
    session.auto_pings.add(seq)
    session.endpoint.send(protocol.make_message(protocol.PING, {'seq': seq, 'sent_at': now, 'auto': True}))


def summary_text(session):
    """Resume affiche une fois apres la connexion."""
    remote = session.remote_position
    parts = ['Vous êtes {}'.format('l\'hôte' if session.role == 'host' else 'l\'invité'),
             'mod {}'.format(MOD_VERSION)]
    if session.rtt_ms is not None:
        parts.append('ping {:.0f} ms'.format(session.rtt_ms))
    if remote is not None:
        parts.append('{} contrôle {}'.format(_other_label(session), remote['name'] or 'un Sim'))
    return 'Partie à deux : ' + ' · '.join(parts) + '.'


def _summary_tick(session, now):
    if session.summary_due is not None and now >= session.summary_due and session.handshake_done:
        session.summary_due = None
        remote = session.remote_position
        bridge_notify(summary_text(session), sim_id=remote['sim_id'] if remote else None)


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
    _release_clock_if_unused(_session)    # vitesse de l'hote retiree hors session d'invite
    _traffic_tick(now)                    # P1 : resume du trafic dans le journal
    _save_lock_tick(_session)             # invite connecte : sauvegarde verrouillee


def _connected_conn(session):
    """Connexion ouverte de la session (transport.Connection), ou None."""
    if not session.endpoint.is_connected:
        return None
    conn = getattr(session.endpoint, 'conn', None)
    if conn is None or conn.closed:
        return None
    return conn


def _set_nodelay(session):
    """TCP_NODELAY sur la socket connectee, une fois : sinon Windows peut garder un petit
    message ~200 ms (Nagle + accuse de reception differe), d'ou un ping eleve meme en local."""
    conn = _connected_conn(session)
    if conn is None or conn.sock is session.nodelay_sock:
        return
    session.nodelay_sock = conn.sock
    try:
        import socket
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        log('[{}] reseau : envoi immediat des petits messages (TCP_NODELAY)'.format(session.role))
    except Exception as exc:
        log('[{}] reseau : TCP_NODELAY impossible ({})'.format(session.role, exc))


def _flush_now(session):
    """Envoie tout de suite ce qui a ete prepare pendant ce passage (reponses, ordres),
    au lieu d'attendre le poll suivant. Une erreur sera vue par ce poll suivant."""
    conn = _connected_conn(session)
    if conn is not None and conn.wants_write():
        conn.handle_write()


def _poll_session(session, now):
    session.polls += 1
    _set_nodelay(session)

    for kind, value in session.endpoint.poll():
        if kind == 'message':
            # Les etats sont journalises en resume par _handle_state, les presences pas du tout.
            quiet = ((value['type'] == protocol.EVENT
                      and (value['data'].get('kind') in ('state', 'presence', 'position', 'clock', 'needs', 'sims',
                                                         'digest', 'gaps')
                           or (value['data'].get('kind') == 'order' and value['data'].get('auto') is True)))
                     # pings automatiques (latence) : toutes les 10 s, inutiles dans le journal
                     or (value['type'] == protocol.PING and value['data'].get('auto') is True)
                     or (value['type'] == protocol.PONG and value['data'].get('seq') in session.auto_pings))
            if not quiet:
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
        _money_tick(session, now)
        _clock_tick(session, now)
        _walk_tick(session, now)
        _needs_tick(session, now)
        _maybe_send_sims(session, now)
        _auto_ping_tick(session, now)
        _summary_tick(session, now)
        _digest_tick(session, now)
        _flush_now(session)


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
        # Age (s reelles) du dernier ordre donne a ce Sim par l'autre joueur, ou None.
        'order_age': _clean_float(data.get('order_age'), ORDER_MAX_AGE),
        'order_seq': _clean_int(data.get('order_seq'), 0, 2 ** 31),
    }


def record_local_order(sim_id):
    """Le joueur de ce PC vient de donner un ordre a ce Sim (file d'attente du jeu)."""
    orders = _sync['orders']
    seq = orders[sim_id][1] + 1 if sim_id in orders else 1
    orders[sim_id] = (time.monotonic(), seq)


def _with_order(position, now):
    """Ajoute a la position l'age et le numero du dernier ordre local donne a ce Sim."""
    order = _sync['orders'].get(position['sim_id'])
    age = now - order[0] if order is not None else None
    position['order_age'] = round(age, 2) if age is not None and age <= ORDER_MAX_AGE else None
    position['order_seq'] = order[1] if order is not None else 0
    return position


def _moved(old, new):
    if old is None:
        return True
    if any(old.get(k) != new.get(k) for k in ('sim_id', 'zone_id', 'level', 'action', 'order_seq')):
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
    if position is None:
        return
    _with_order(position, now)
    if not _moved(session.position_sent, position):
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
    # Moment (horloge locale) du dernier ordre de l'autre joueur a ce Sim.
    position['order_time'] = (session.remote_position_at - position['order_age']
                              if position['order_age'] is not None else None)
    if previous is None or previous['sim_id'] != position['sim_id']:
        log('[{}] l\'autre joueur controle {} ({})'.format(session.role, position['name'], position['sim_id']))
        bridge_notify('{} contrôle {}.'.format(_other_label(session).capitalize(), position['name'] or 'un Sim'),
                      important=False, sim_id=position['sim_id'])
        session.walk = None
    _maybe_walk(session, session.remote_position_at)


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
# Synchro en jeu (M4) : argent, heure et vitesse, marche du double
# ---------------------------------------------------------------------------

_sync = {
    'orders': {},            # sim_id -> (moment, numero) du dernier ordre du joueur de ce PC
    'links': {},             # identifiant d'ordre -> weakref de l'action du jeu (annulation)
    'link_ids': {},          # id(action) -> identifiant d'ordre
    'pushing': False,        # vrai pendant un ordre donne par le mod (pas un ordre du joueur)
    'clock_request': None,   # invite : demande de vitesse posee dans l'horloge
    'clock_value': None,     # ... et sa valeur
    'errors': {},            # derniere erreur par sujet (journalisee une fois par message)
}


def _sync_error(where):
    text = traceback.format_exc()
    last = text.strip().splitlines()[-1]
    if _sync['errors'].get(where) != last:
        log('synchro : {} impossible :\n{}'.format(where, text))
    _sync['errors'][where] = last


def _safe(where, func, *args):
    try:
        return func(*args)
    except Exception:
        _sync_error(where)
        return None


# -- argent --

def _money_flush(session):
    """Envoie la difference de solde vue depuis la derniere lecture. Renvoie le solde lu."""
    read = _safe('lecture argent', bridge_funds)
    if read is None:
        return None
    household_id, money = read
    if session.money_household != household_id:
        session.money_household = household_id      # nouveau foyer : simple point de depart
        session.money_known = money
        return money
    delta = money - session.money_known
    if delta and session.endpoint.send(protocol.make_message(
            protocol.EVENT, {'kind': 'money', 'delta': delta, 'household_id': household_id})):
        session.money_known = money
        session.money_sent += 1
        log('[{}] argent : {:+d} envoye (solde {})'.format(session.role, delta, money))
    return money


def _money_tick(session, now):
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.money_checked_at < MONEY_INTERVAL:
        return
    session.money_checked_at = now
    money = _money_flush(session)
    if session.role == 'host' and money is not None and not session.money_total_sent:
        # Alignement initial : l'invite prend une fois le solde de l'hote.
        if session.endpoint.send(protocol.make_message(protocol.EVENT, {
                'kind': 'money', 'total': money, 'household_id': session.money_household})):
            session.money_total_sent = True


def _apply_money(session, delta, reason):
    _money_flush(session)                               # ne pas perdre une depense locale en cours
    if session.money_household is None:
        return False
    money = _safe('argent', bridge_apply_funds, delta)
    if money is None:
        return False
    session.money_known = money
    session.money_applied += 1
    log('[{}] argent : {:+d} applique ({}), solde {}'.format(session.role, delta, reason, money))
    return True


def _handle_money(session, data):
    household_id = _clean_int(data.get('household_id'), 0, 2 ** 64)
    local = _safe('lecture argent', bridge_funds)
    if household_id is None or local is None or local[0] != household_id:
        log('[{}] argent ignore : foyer different (recu {} , ici {})'.format(
            session.role, household_id, local[0] if local else None))
        return
    if 'total' in data:
        total = _clean_int(data.get('total'), -STATE_MAX_FUNDS, STATE_MAX_FUNDS)
        if session.role != 'client' or total is None or session.money_aligned:
            return
        session.money_aligned = True
        _money_flush(session)
        delta = total - (session.money_known if session.money_known is not None else local[1])
        if delta and _apply_money(session, delta, 'alignement sur l\'hote'):
            bridge_notify('Argent aligné sur l\'hôte : {} simflouz.'.format(total), important=False)
        return
    delta = _clean_int(data.get('delta'), -MONEY_MAX_DELTA, MONEY_MAX_DELTA)
    if not delta:
        log('[{}] argent : difference invalide ignoree'.format(session.role))
        return
    _apply_money(session, delta, 'autre joueur')


# -- heure et vitesse (celles de l'hote) --

def _clock_tick(session, now):
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if session.role != 'host' or now - session.clock_sent_at < CLOCK_INTERVAL:
        return
    session.clock_sent_at = now
    read = _safe('lecture heure', bridge_clock)
    if read is None:
        return
    # Rythme exact de l'horloge de l'hote (s de jeu par s reelle) depuis le dernier envoi,
    # pour que l'invite ait la bonne tolerance meme juste apres un changement de vitesse.
    previous = session.clock_prev
    if previous is None or previous[2] != read[1]:
        session.clock_prev = (read[0], now, read[1])     # nouvelle vitesse : rythme a remesurer
        session.clock_rate = None
    elif now - previous[1] >= 0.2:
        session.clock_rate = max(0.0, (read[0] - previous[0]) / (now - previous[1]))
        session.clock_prev = (read[0], now, read[1])
    message = {'kind': 'clock', 'seconds': read[0], 'speed': read[1]}
    if session.clock_rate is not None:
        message['rate'] = round(session.clock_rate, 3)
    session.endpoint.send(protocol.make_message(protocol.EVENT, message))


def _set_clock_request(value):
    """Pose (ou remplace) la demande de vitesse de l'invite ; None la retire."""
    old = _sync['clock_request']
    if old is not None and value is not None and value == _sync['clock_value']:
        current = _safe('lecture vitesse', bridge_clock)
        if current is not None and current[1] == value:
            return                                   # deja a la bonne vitesse
    if old is not None:
        _sync['clock_request'] = None
        _safe('vitesse', bridge_remove_pause, old)
    _sync['clock_value'] = value
    if value is not None:
        _sync['clock_request'] = _safe('vitesse', bridge_push_speed, value)


def _handle_clock(session, data):
    seconds = _clean_float(data.get('seconds'), 10.0 ** 13)
    speed = _clean_int(data.get('speed'), 0, 16)
    if seconds is None or seconds < 0 or speed is None or not _safe('vitesse', bridge_valid_speed, speed):
        log('[client] heure de l\'hote invalide ignoree')
        return
    now = time.monotonic()
    previous = session.host_clock
    sent_rate = _clean_float(data.get('rate'), 100000.0)
    if previous is None or previous[1] != speed:
        session.host_rate = None                     # nouvelle vitesse : rythme a remesurer
        if previous is not None:
            session.clock_grace_until = now + CLOCK_GRACE
    elif now - previous[2] >= 0.2:
        rate = (seconds - previous[0]) / (now - previous[2])
        if 0.0 <= rate <= 10000.0:
            session.host_rate = rate if session.host_rate is None else 0.7 * session.host_rate + 0.3 * rate
    if sent_rate is not None and sent_rate >= 0.0:
        session.host_rate = sent_rate                # mesure exacte faite par l'hote
    session.host_clock = (seconds, speed, now)
    if _gate['waiting']:
        return                                       # la pause d'attente passe avant
    local = _safe('lecture heure', bridge_clock)
    if local is None:
        return
    rate = session.host_rate if session.host_rate is not None else (CLOCK_DEFAULT_RATE if speed else 0.0)
    tolerance = max(CLOCK_MIN_TOLERANCE, rate * CLOCK_TOLERANCE_REAL)
    gap = local[0] - seconds                         # > 0 : l'invite est en avance
    session.last_gap = gap
    # Un ecart doit se confirmer sur deux messages de suite avant correction (pas de yo-yo
    # sur un message en retard ou un changement de vitesse en cours).
    session.clock_strikes = session.clock_strikes + 1 if abs(gap) > tolerance else 0
    if session.clock_strikes < CLOCK_CONFIRM and not session.clock_ahead:
        gap = 0.0
    if now < session.clock_grace_until:
        # Changement de vitesse en cours : les deux horloges n'ont pas encore la meme vitesse.
        gap = 0.0 if not session.clock_ahead else min(gap, tolerance)
    if gap < -tolerance:
        try:
            bridge_advance_clock(-gap)
        except Exception:
            _sync_error('avance de l\'heure')
        else:
            session.clock_jumps += 1
            log('[client] heure : en retard de {:.0f} s de jeu, avancee'.format(-gap))
            if -gap > ALERT_CLOCK_JUMP:
                bridge_notify('Heure recalée sur l\'hôte : +{:.0f} min de jeu.'.format(-gap / 60.0),
                              alert=True, key='clock')
            gap = 0.0
    if gap > tolerance and not session.clock_ahead:
        session.clock_ahead = True
        log('[client] heure : en avance de {:.0f} s de jeu, pause jusqu\'a etre rattrape'.format(gap))
    elif gap < tolerance / 4.0 and session.clock_ahead:
        session.clock_ahead = False
        log('[client] heure : rattrapee par l\'hote')
    paused = _safe('vitesse', bridge_paused_value)
    _set_clock_request(paused if session.clock_ahead and paused is not None else speed)


def _handle_speed_request(session, data):
    """Hote : l'invite a appuye sur un bouton de vitesse ; l'hote l'applique comme le sien."""
    speed = _clean_int(data.get('speed'), 0, 16)
    if speed is None or speed not in PLAYER_SPEEDS or not _safe('vitesse', bridge_valid_speed, speed):
        log('[host] demande de vitesse invalide ignoree ({!r})'.format(data.get('speed')))
        return
    try:
        bridge_set_player_speed(speed)
    except Exception:
        _sync_error('vitesse demandee')
        return
    session.speed_requests += 1
    session.clock_sent_at = 0.0                     # l'invite recoit la nouvelle vitesse tout de suite
    log('[host] vitesse {} demandee par l\'invite, appliquee'.format(speed))


def on_player_speed_change():
    """Invite : un bouton de vitesse du joueur a ete utilise ; la demande part a l'hote."""
    session = _session
    if session is None or session.role != 'client' or not session.handshake_done:
        return
    speed = _safe('lecture vitesse du joueur', bridge_player_speed)
    if speed is None or speed not in PLAYER_SPEEDS:
        # 4 (INTERACTION_STARTUP_SPEED) et 5 (SUPER_SPEED3) sont poses par le jeu lui-meme
        # (sommeil de tous les Sims...), pas par un bouton : jamais transmis.
        return
    now = time.monotonic()
    last = session.last_speed_request
    if last is not None and last[0] == speed and now - last[1] < SPEED_REQUEST_DEDUP:
        return                                       # meme demande juste avant (push puis pop)
    if session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'speed_request', 'speed': speed})):
        session.last_speed_request = (speed, now)
        session.clock_grace_until = now + CLOCK_GRACE  # l'hote change de vitesse : pas de correction
        session.speed_requests += 1
        log('[client] vitesse {} demandee a l\'hote'.format(speed))


def _install_speed_hook():
    """Enveloppe GameClock.set_clock_speed / push_speed / pop_speed : apres l'original, une
    demande en source GAMEPLAY (boutons du joueur, clock_commands) est signalee."""
    import inspect
    from clock import GameClock, GameSpeedChangeSource
    for name in ('set_clock_speed', 'push_speed', 'pop_speed'):
        original = getattr(GameClock, name)
        if getattr(original, '_sims4mp_hook', False):
            continue
        signature = inspect.signature(original)

        def make(original, signature):
            @functools.wraps(original)
            def wrapper(self, *args, **kwargs):
                result = original(self, *args, **kwargs)
                try:
                    bound = signature.bind(self, *args, **kwargs)
                    bound.apply_defaults()
                    if bound.arguments.get('source') == GameSpeedChangeSource.GAMEPLAY:
                        on_player_speed_change()
                except Exception:
                    _sync_error('suivi des boutons de vitesse')
                return result
            wrapper._sims4mp_hook = True
            return wrapper
        setattr(GameClock, name, make(original, signature))
    log('synchro : boutons de vitesse suivis (GameClock.set_clock_speed / push_speed / pop_speed)')


def _release_clock_if_unused(session):
    if _sync['clock_request'] is not None and (
            session is None or session.role != 'client' or not session.handshake_done):
        _set_clock_request(None)
        log('synchro : vitesse de l\'hote retiree')


# -- marche du double --

def _walk_status(session, text):
    """Pourquoi le double bouge ou non : affiche par mp.positions, journalise s'il change."""
    if session.walk_status != text:
        session.walk_status = text
        log('[{}] double : {}'.format(session.role, text))


def _maybe_walk(session, now):
    """Fait marcher le double du Sim de l'autre joueur vers sa derniere position."""
    remote = session.remote_position
    if remote is None:
        return _walk_status(session, 'aucune position recue')
    if _gate['waiting']:
        return _walk_status(session, 'en attente de l\'autre joueur')
    local_zone = bridge_current_zone_id()
    if remote['zone_id'] is None or remote['zone_id'] != local_zone:
        return _walk_status(session, 'autre lot (zone {} , ici {})'.format(remote['zone_id'], local_zone))
    mine = _read('active_sim', _active_sim)
    mine_id = _read('sim_id', lambda: mine.sim_info.sim_id) if mine is not None else None
    # Le dernier ordre donne a ce Sim gagne ; sans ordre de part et d'autre, l'autre joueur
    # mene son Sim, et pour un Sim controle des deux cotes c'est l'hote.
    local_order = _sync['orders'].get(remote['sim_id'])
    local_time = local_order[0] if local_order is not None and now - local_order[0] <= ORDER_MAX_AGE else None
    remote_time = remote.get('order_time')
    if local_time is not None and (remote_time is None or local_time >= remote_time):
        return _walk_status(session, 'votre dernier ordre a ce Sim est le plus recent : il le suit')
    if local_time is None and remote_time is None and mine_id == remote['sim_id'] and session.role == 'host':
        return _walk_status(session, 'meme Sim des deux cotes, aucun ordre recent : l\'hote garde la main')
    hold = session.action_hold.get(remote['sim_id'])
    if hold is not None and now < hold:
        return _walk_status(session, 'action de l\'autre joueur rejouee : pas de recalage pendant {:.0f} s'.format(
            ACTION_HOLD))
    status, session.walk = _move_toward(session, remote, now, session.walk)
    if status is not None:
        _walk_status(session, status)
        _alert_missing_sim(session, remote, status)


def _move_toward(session, remote, now, walk):
    """Rapproche l'exemplaire local du Sim de la position recue. Renvoie (etat ou None, marche en cours)."""
    found = bridge_local_sim_position(remote['sim_id'])
    if found is None:
        return 'lecture du Sim impossible (voir le journal)', walk
    if found[0] == 'inconnu':
        return 'Sim inconnu ici : ce n\'est pas la meme sauvegarde', walk
    if found[0] != 'present':
        return 'Sim absent du lot ici', walk
    x, y, z, level = found[1]
    gap = ((x - remote['x']) ** 2 + (z - remote['z']) ** 2) ** 0.5
    target = (remote['x'], remote['z'], remote['level'])
    if gap < WALK_MIN and (remote['level'] is None or level == remote['level']):
        return 'en place', None
    same = (walk is not None and walk['target'][2] == target[2]
            and ((walk['target'][0] - target[0]) ** 2 + (walk['target'][1] - target[1]) ** 2) ** 0.5 < WALK_RETARGET)
    teleport = ((remote['level'] is not None and level is not None and level != remote['level'])
                or gap > TELEPORT_DIST or (same and now - walk['started'] > WALK_TIMEOUT))
    if same and not teleport:
        return None, walk                            # deja en route vers ce point
    if walk is not None and not same and not teleport and now - walk['at'] < 1.0:
        return None, walk                            # au plus un nouvel ordre par seconde
    args = (remote['sim_id'], remote['x'], remote['y'], remote['z'], remote['level'])
    placed = None
    _sync['pushing'] = True                          # ces ordres ne sont pas ceux du joueur
    try:
        ok = _safe('marche', bridge_move_sim, *(args + (teleport,)))
        if not ok and not teleport:
            teleport = True
            ok = _safe('teleportation', bridge_move_sim, *(args + (True,)))
        # Pose directe seulement si le Sim est vraiment loin : refuser la marche veut souvent dire
        # qu'il est occupe (assis, au lit...), et le poser l'arracherait a son action.
        if not ok and gap > PLACE_MIN:
            placed = _safe('placement', bridge_place_sim, *args)
    finally:
        _sync['pushing'] = False
    if not ok:
        if placed:
            session.teleports += 1
            return 'pose directement (ordres de marche refuses, voir le journal)', None
        if gap <= PLACE_MIN:
            return 'occupe : laisse en place ({:.1f} d\'ecart)'.format(gap), {
                'target': target, 'started': now, 'at': now}
        return 'impossible de le deplacer (voir le journal)', walk
    if teleport:
        session.teleports += 1
        log('[{}] Sim {} teleporte ({:.1f} d\'ecart)'.format(session.role, remote['sim_id'], gap))
        return 'teleporte', None
    session.walks += 1
    return 'marche vers l\'autre joueur', {'target': target, 'started': now if not same else walk['started'],
                                           'at': now}


# -- ordres des joueurs (M5) --

def send_player_order(order, interaction=None):
    """Envoie a l'autre PC l'action que le joueur de ce PC vient de choisir (au clic).
    Renvoie l'identifiant de l'ordre, relie a l'action locale pour une annulation."""
    session = _session
    if session is None or not session.handshake_done or not session.endpoint.is_connected or _gate['waiting']:
        return None
    session.order_counter += 1
    message = dict(order, kind='order', id='{}-{}'.format(session.role, session.order_counter))
    if not session.endpoint.send(protocol.make_message(protocol.EVENT, message)):
        return None
    _flush_now(session)                              # l'ordre part au clic, sans attendre la pompe
    session.orders_sent += 1
    if not order.get('auto'):
        log('[{}] ordre envoye : {} -> {} ({})'.format(session.role, order['name'], order['target']['t'],
                                                        message['id']))
    if interaction is not None:
        link_order(message['id'], interaction)
    return message['id']


# -- annulation (D1) : l'ordre et l'action locale sont relies des deux cotes --

def link_order(order_id, interaction):
    """Relie un ordre (envoye ou rejoue) a l'action du jeu correspondante sur ce PC."""
    if interaction is None:
        return
    links = _sync['links']
    try:
        ref = weakref.ref(interaction)
    except TypeError:
        ref = lambda: interaction                   # objet sans weakref (tests) : reference simple
    links[order_id] = ref
    _sync['link_ids'][id(interaction)] = order_id
    while len(links) > LINKS_MAX:
        old_id = next(iter(links))
        old = links.pop(old_id)()
        if old is not None:
            _sync['link_ids'].pop(id(old), None)


def order_of(interaction):
    order_id = _sync['link_ids'].get(id(interaction))
    if order_id is None:
        return None
    ref = _sync['links'].get(order_id)
    return order_id if ref is not None and ref() is interaction else None


def on_user_cancel(interaction):
    """La croix du joueur de ce PC sur une action reliee : l'annulation part vers l'autre PC."""
    session = _session
    if _sync['pushing'] or not _connected(session):
        return
    order_id = order_of(interaction)
    if order_id is None:
        return
    if session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'cancel', 'order_id': order_id})):
        _flush_now(session)
        session.cancels_sent += 1
        log('[{}] annulation envoyee ({})'.format(session.role, order_id))


def _handle_cancel(session, data):
    order_id = data.get('order_id')
    if not isinstance(order_id, str) or not 0 < len(order_id) <= 40:
        return
    ref = _sync['links'].get(order_id)
    interaction = ref() if ref is not None else None
    if interaction is None:
        log('[{}] annulation {} : action deja terminee ici'.format(session.role, order_id))
        return
    _sync['pushing'] = True                          # pas d'annulation renvoyee en echo
    try:
        done = _safe('annulation', bridge_cancel_interaction, interaction)
    finally:
        _sync['pushing'] = False
    if done:
        session.cancels_applied += 1
        log('[{}] annulation {} appliquee'.format(session.role, order_id))
        bridge_notify('{} a annulé une action.'.format(_other_label(session).capitalize()), important=False,
                      key='cancel')


def validate_order(data):
    """Copie propre d'un ordre recu, ou None."""
    order_id = data.get('id')
    sim_id = _clean_int(data.get('sim_id'), 1, 2 ** 64)
    affordance = _clean_int(data.get('affordance'), 1, 2 ** 64)
    where = data.get('target')
    if (not isinstance(order_id, str) or not 0 < len(order_id) <= 40 or not order_id.isprintable()
            or sim_id is None or affordance is None or not isinstance(where, dict)):
        return None
    kind = where.get('t')
    if kind == 'none':
        clean = {'t': 'none'}
    elif kind in ('sim', 'obj'):
        target_id = _clean_int(where.get('id'), 1, 2 ** 64)
        if target_id is None:
            return None
        clean = {'t': kind, 'id': target_id}
    elif kind == 'terrain':
        coords = [_clean_float(where.get(axis), POSITION_MAX_COORD) for axis in ('x', 'y', 'z')]
        if None in coords:
            return None
        clean = {'t': 'terrain', 'x': coords[0], 'y': coords[1], 'z': coords[2],
                 'level': _clean_int(where.get('level'), POSITION_LEVELS[0], POSITION_LEVELS[1])}
    else:
        return None
    return {'id': order_id, 'sim_id': sim_id, 'affordance': affordance,
            'name': _clean_text(data.get('name')) or str(affordance), 'target': clean,
            'auto': data.get('auto') is True}


def _handle_order(session, data):
    order = validate_order(data)
    if order is None:
        log('[{}] ordre invalide ignore'.format(session.role))
        return
    if order['id'] in session.orders_seen:
        return                                       # deja rejoue : jamais deux fois
    session.orders_seen.append(order['id'])
    del session.orders_seen[:-ORDERS_SEEN_MAX]
    if _gate['waiting']:
        session.last_order = '{} : ignore (attente de l\'autre joueur)'.format(order['name'])
        return
    if order['auto'] and _needs_authority(session, order['sim_id'], _my_active_id()):
        return                                       # action autonome d'un Sim dont ce PC fait foi
    if is_travel(order['name']):
        log('[{}] voyage recu non rejoue : {}'.format(session.role, order['name']))
        return                                       # (mod plus ancien en face) : jamais de voyage rejoue
    _sync['pushing'] = True                          # pas un ordre du joueur de ce PC
    try:
        result = _safe('ordre rejoue', bridge_replay_order, order['sim_id'], order['affordance'], order['target'],
                       order['auto'])
    finally:
        _sync['pushing'] = False
    ok, reason = result if result is not None else (False, 'erreur (voir le journal)')
    label = '{}{}'.format(order['name'], ' (autonomie)' if order['auto'] else '')
    if ok:
        link_order(order['id'], reason)                # reason : l'action rejouee (pour l'annulation)
        reason = None
        session.orders_replayed += 1
        session.action_hold[order['sim_id']] = time.monotonic() + ACTION_HOLD
        if not order['auto']:
            session.walk = None
        session.sims_walk.pop(order['sim_id'], None)
        session.last_order = '{} : rejouee'.format(label)
    else:
        session.orders_failed += 1
        session.last_order = '{} : non rejouee, {}'.format(label, reason)
        if not order['auto']:
            bridge_notify('Action de {} non rejouée chez vous : {} ({}).'.format(
                _other_label(session), order['name'], reason), alert=True, sim_id=order['sim_id'],
                key='order-{}'.format(order['name']))
    if not order['auto']:
        log('[{}] ordre {} {}'.format(session.role, order['id'], session.last_order))
    elif not ok:
        # Actions autonomes refusees : au plus une ligne par action et par minute.
        now = time.monotonic()
        key = order['name']
        if now - session.auto_failed_logged.get(key, -AUTO_FAIL_LOG) >= AUTO_FAIL_LOG:
            session.auto_failed_logged[key] = now
            log('[{}] ordre {} {}'.format(session.role, order['id'], session.last_order))


def on_player_order(queue, interaction):
    """Appele par la file d'attente du jeu pour chaque ordre du joueur de ce PC."""
    order = _safe('lecture de l\'ordre', bridge_order_from_interaction, queue, interaction)
    if order is None:
        return
    if is_travel(order['name']):
        session = _session
        if _connected(session):
            session.endpoint.send(protocol.make_message(protocol.EVENT, {
                'kind': 'travel', 'sim_id': order['sim_id'], 'name': order['name']}))
            log('[{}] voyage non rejoue chez l\'autre, prevenu : {}'.format(session.role, order['name']))
        return
    send_player_order(order, interaction)


def _handle_travel(session, data):
    sim_id = _clean_int(data.get('sim_id'), 1, 2 ** 64)
    log('[{}] l\'autre joueur voyage ({})'.format(session.role, _clean_text(data.get('name'))))
    bridge_notify('{} part sur un autre lot. Pour continuer ensemble, rejoignez-le sur le même lot '
                  '(voyage non synchronisé).'.format(_other_label(session).capitalize()),
                  alert=True, sim_id=sim_id, key='travel')


# -- qui fait foi pour chaque Sim (M6) --
# L'invite fait foi pour le Sim qu'il controle (sauf si l'hote controle le meme) ;
# l'hote fait foi pour tous les autres : sa famille, les PNJ, le Sim qu'il controle.

def _my_active_id():
    mine = _read('active_sim', _active_sim)
    return _read('sim_id', lambda: mine.sim_info.sim_id) if mine is not None else None


def sim_owner(session, sim_id, mine_id):
    """'host' ou 'client' : le PC qui fait foi pour ce Sim."""
    other_id = session.remote_position['sim_id'] if session.remote_position else None
    host_active, client_active = (mine_id, other_id) if session.role == 'host' else (other_id, mine_id)
    if sim_id is not None and sim_id == client_active and client_active != host_active:
        return 'client'
    return 'host'


def _needs_authority(session, sim_id, mine_id):
    """Vrai si ce PC fait foi pour ce Sim (besoins, autonomie, position)."""
    return sim_owner(session, sim_id, mine_id) == session.role


def _connected(session):
    return (session is not None and session.handshake_done and session.endpoint.is_connected
            and not _gate['waiting'])


def autonomy_refused(queue, interaction):
    """Vrai si l'autonomie de ce Sim est refusee ici : l'autre PC fait foi et envoie ses actions."""
    session = _session
    if _sync['pushing'] or not _connected(session) or bridge_interaction_kind(interaction) != 'auto':
        return False
    sim_id = queue.sim.sim_info.sim_id
    if _needs_authority(session, sim_id, _my_active_id()):
        return False
    session.autonomy_refused += 1
    return True


def on_autonomy_action(queue, interaction):
    """Action decidee par l'autonomie d'un Sim dont ce PC fait foi : envoyee a l'autre PC,
    au plus une par Sim et par AUTO_ORDER_GAP s, et jamais la meme deux fois de suite
    dans les AUTO_ORDER_REPEAT s (l'autonomie repropose souvent la meme action)."""
    session = _session
    if not _connected(session):
        return
    sim_id = queue.sim.sim_info.sim_id
    if not _needs_authority(session, sim_id, _my_active_id()):
        return
    order = _safe('lecture de l\'action autonome', bridge_order_from_interaction, queue, interaction, 'auto')
    if order is None or is_travel(order['name']):
        return
    now = time.monotonic()
    last = session.auto_sent.get(sim_id)
    signature = (order['affordance'], repr(order['target']))
    if last is not None and (now - last[0] < AUTO_ORDER_GAP
                             or (last[1] == signature and now - last[0] < AUTO_ORDER_REPEAT)):
        session.auto_skipped += 1
        return
    session.auto_sent[sim_id] = (now, signature)
    send_player_order(order, interaction)


def is_travel(name):
    """Actions de voyage (telephone « Voyager avec », carte...) : jamais rejouees chez l'autre,
    elles changeraient son lot ; l'autre joueur est seulement prevenu."""
    return 'travel' in (name or '').lower()


# -- positions de tous les Sims dont ce PC fait foi (M6) --

def _maybe_send_sims(session, now):
    if not (session.endpoint.is_connected and session.handshake_done):
        return
    if now - session.sims_checked_at < POSITION_INTERVAL:
        return
    session.sims_checked_at = now
    mine_id = _my_active_id()
    ids = _safe('liste des Sims', bridge_instanced_sim_ids) or []
    changed = []
    for sim_id in ids:
        if sim_id == mine_id or not _needs_authority(session, sim_id, mine_id):
            continue                                 # mon Sim part deja par « position »
        snapshot = _safe('position d\'un Sim', bridge_sim_snapshot, sim_id)
        if snapshot is None or not _moved(session.sims_sent.get(sim_id), snapshot):
            continue
        changed.append(snapshot)
        if len(changed) >= SIMS_MAX:
            break
    if changed and session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'sims', 'list': changed})):
        for snapshot in changed:
            session.sims_sent[snapshot['sim_id']] = snapshot


def _follow_sim(session, sim_id, now):
    entry = session.sims_remote.get(sim_id)
    if entry is None or _gate['waiting']:
        return
    position = entry
    if position['zone_id'] is None or position['zone_id'] != bridge_current_zone_id():
        return
    hold = session.action_hold.get(sim_id)
    if hold is not None and now < hold:
        return
    status, session.sims_walk[sim_id] = _move_toward(session, position, now, session.sims_walk.get(sim_id))
    if status is not None:
        session.sims_status[sim_id] = status
        _alert_missing_sim(session, position, status)


def _alert_missing_sim(session, position, status):
    """Alerte (une fois par Sim et par 2 min) : Sim present chez l'autre, pas ici."""
    if status.startswith('Sim absent') or status.startswith('Sim inconnu'):
        bridge_notify('{} est sur le lot chez {}, pas chez vous : il ne peut pas être synchronisé.'.format(
            position['name'] or 'Un Sim', _other_label(session)), alert=True, important=False,
            key='absent-{}'.format(position['sim_id']))


def _handle_sims(session, data):
    entries = data.get('list')
    if not isinstance(entries, list) or len(entries) > SIMS_MAX:
        log('[{}] positions des Sims invalides ignorees'.format(session.role))
        return
    mine_id = _my_active_id()
    now = time.monotonic()
    for entry in entries:
        position = validate_position(entry)
        if position is None or _needs_authority(session, position['sim_id'], mine_id):
            continue
        session.sims_remote[position['sim_id']] = position
        _follow_sim(session, position['sim_id'], now)


def _needs_tick(session, now):
    if not (session.endpoint.is_connected and session.handshake_done) or _gate['waiting']:
        return
    if now - session.needs_checked_at < NEEDS_INTERVAL:
        return
    session.needs_checked_at = now
    mine_id = _my_active_id()
    # Tous les Sims presents dont ce PC fait foi (M6) ; a defaut de liste, le Sim controle.
    ids = _safe('liste des Sims', bridge_instanced_sim_ids) or ([mine_id] if mine_id is not None else [])
    for sim_id in ids:
        if not _needs_authority(session, sim_id, mine_id):
            continue
        values = _safe('lecture des besoins', bridge_read_needs, sim_id)
        if not values:
            continue
        last = session.needs_sent.get(sim_id)
        if (last is not None and now - last[1] < NEEDS_RESEND
                and all(abs(last[0].get(k, NEEDS_LIMIT) - v) <= NEEDS_EPSILON for k, v in values.items())):
            continue
        payload = {str(k): round(v, 2) for k, v in list(values.items())[:NEEDS_MAX]}
        if session.endpoint.send(protocol.make_message(protocol.EVENT, {
                'kind': 'needs', 'sim_id': sim_id, 'values': payload})):
            session.needs_sent[sim_id] = (values, now)


def _handle_needs(session, data):
    sim_id = _clean_int(data.get('sim_id'), 1, 2 ** 64)
    raw = data.get('values')
    if sim_id is None or not isinstance(raw, dict) or len(raw) > NEEDS_MAX:
        log('[{}] besoins invalides ignores'.format(session.role))
        return
    values = {}
    for key, value in raw.items():
        guid = (_clean_int(int(key), 1, 2 ** 64)
                if isinstance(key, str) and key.isascii() and key.isdigit() and len(key) <= 20 else None)
        number = _clean_float(value, NEEDS_LIMIT)
        if guid is not None and number is not None:
            values[guid] = number
    if _needs_authority(session, sim_id, _my_active_id()):
        return                                       # ce PC fait foi pour ce Sim
    written = _safe('ecriture des besoins', bridge_write_needs, sim_id, values)
    if written:
        session.needs_written += written


def _walk_tick(session, now):
    # Reessaie de temps en temps : double arrive, bloque ou ordre refuse.
    if session.walk is not None and now - session.walk['at'] >= WALK_RETRY:
        _maybe_walk(session, now)
    # Autres Sims (M6) : recalage periodique sur la derniere position recue.
    if session.sims_remote and now - session.sims_followed_at >= WALK_RETRY:
        session.sims_followed_at = now
        for sim_id in list(session.sims_remote):
            _follow_sim(session, sim_id, now)


def sync_lines(session):
    lines = ['Argent : {} difference(s) envoyee(s), {} appliquee(s){}'.format(
        session.money_sent, session.money_applied,
        ' , solde suivi {}'.format(session.money_known) if session.money_known is not None else '')]
    if session.role == 'client':
        clock = session.host_clock
        lines.append('Heure : {}{}{}{}{}'.format(
            'vitesse de l\'hote {}'.format(clock[1]) if clock else 'rien recu de l\'hote',
            ' , ecart {:+.0f} s de jeu'.format(session.last_gap) if session.last_gap is not None else '',
            ' , en avance : pause' if session.clock_ahead else '',
            ' , {} avance(s) d\'heure'.format(session.clock_jumps) if session.clock_jumps else '',
            ' , {} demande(s) de vitesse envoyee(s)'.format(session.speed_requests) if session.speed_requests else ''))
    else:
        lines.append('Heure : envoyee a l\'invite ; {} demande(s) de vitesse de l\'invite appliquee(s)'.format(
            session.speed_requests))
    lines.append('Double de l\'autre joueur : {} ; {} ordre(s) de marche, {} teleportation(s)'.format(
        session.walk_status, session.walks, session.teleports))
    lines.append('Actions : {} envoyee(s), {} rejouee(s), {} non rejouee(s){}'.format(
        session.orders_sent, session.orders_replayed, session.orders_failed,
        ' ; derniere : {}'.format(session.last_order) if session.last_order else ''))
    lines.append('Besoins : {} valeur(s) recopiee(s) depuis l\'autre PC'.format(session.needs_written))
    lines.append('Annulations : {} envoyee(s), {} appliquee(s)'.format(session.cancels_sent,
                                                                        session.cancels_applied))
    moving = sum(1 for status in session.sims_status.values() if status.startswith('marche'))
    lines.append('Autres Sims ({}) : {} suivi(s), {} en marche ; autonomie refusee ici {} fois'.format(
        'l\'hote fait foi' if session.role == 'client' else 'ce PC fait foi',
        len(session.sims_remote), moving, session.autonomy_refused))
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
    presence = {'kind': 'presence'}
    if session.role == 'client' and session.rtt_ms is not None:
        presence['rtt'] = round(session.rtt_ms, 1)        # l'hote connait ainsi la latence
    session.endpoint.send(protocol.make_message(protocol.EVENT, presence))


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
        bridge_notify('Action refusée : l\'autre joueur n\'est pas encore en jeu.', important=False)
    return True


# ---------------------------------------------------------------------------
# Prototype P1 : mesure du trafic simulation -> affichage (lecture seule)
# ---------------------------------------------------------------------------

TRAFFIC_REPORT_INTERVAL = 60.0           # resume dans le journal, en secondes reelles

_traffic = {
    'enabled': False,
    'installed': False,
    'started_at': None,
    'reported_at': None,
    'total': [0, 0],                      # messages, octets
    'by_type': {},                        # msg_id -> [messages, octets, plus gros]
    'by_session': {},                     # session -> [messages, octets]
    'errors': 0,
    'names': None,                        # msg_id -> nom MSG_* (Consts_pb2), lu a la demande
}


def traffic_reset(now):
    _traffic.update(started_at=now, reported_at=now, total=[0, 0], by_type={}, by_session={}, errors=0)


def traffic_record(session_id, msg_id, data):
    """Compte un message (appele pour chaque omega.send pendant la mesure)."""
    size = len(data) if isinstance(data, (bytes, bytearray)) else 0
    total = _traffic['total']
    total[0] += 1
    total[1] += size
    entry = _traffic['by_type'].get(msg_id)
    if entry is None:
        entry = _traffic['by_type'][msg_id] = [0, 0, 0]
    entry[0] += 1
    entry[1] += size
    if size > entry[2]:
        entry[2] = size
    per = _traffic['by_session'].get(session_id)
    if per is None:
        per = _traffic['by_session'][session_id] = [0, 0]
    per[0] += 1
    per[1] += size


def _message_names():
    if _traffic['names'] is None:
        names = {}
        try:
            from protocolbuffers import Consts_pb2
            for name in dir(Consts_pb2):
                value = getattr(Consts_pb2, name)
                if name.startswith('MSG_') and isinstance(value, int) and value not in names:
                    names[value] = name
        except Exception:
            log('trafic : noms des messages illisibles :\n' + traceback.format_exc())
        _traffic['names'] = names
    return _traffic['names']


def traffic_lines(now, top=12):
    started = _traffic['started_at']
    if started is None:
        return ['Mesure jamais lancee (mp.traffic on).']
    elapsed = max(now - started, 0.001)
    count, size = _traffic['total']
    lines = ['Trafic simulation -> affichage {} depuis {:.0f} s : {} messages, {:.1f} Ko '
             '({:.1f} msg/s, {:.1f} Ko/s){}'.format(
                 'en cours' if _traffic['enabled'] else 'arrete', elapsed, count, size / 1024.0,
                 count / elapsed, size / 1024.0 / elapsed,
                 ' , {} erreur(s)'.format(_traffic['errors']) if _traffic['errors'] else '')]
    names = _message_names()
    ranked = sorted(_traffic['by_type'].items(), key=lambda item: item[1][1], reverse=True)
    for msg_id, (n, octets, biggest) in ranked[:top]:
        lines.append('  {} ({}) : {} msg, {:.1f} Ko, max {} octets'.format(
            names.get(msg_id, '?'), msg_id, n, octets / 1024.0, biggest))
    if len(ranked) > top:
        lines.append('  ... {} autre(s) type(s)'.format(len(ranked) - top))
    sessions = ', '.join('{:x} : {} msg'.format(s, v[0]) if isinstance(s, int) else '{} : {} msg'.format(s, v[0])
                         for s, v in sorted(_traffic['by_session'].items(), key=lambda kv: -kv[1][0]))
    lines.append('Sessions (clients) : {}'.format(sessions or 'aucune'))
    return lines


def _traffic_tick(now):
    if _traffic['enabled'] and now - _traffic['reported_at'] >= TRAFFIC_REPORT_INTERVAL:
        _traffic['reported_at'] = now
        log('trafic :\n  ' + '\n  '.join(traffic_lines(now)))


def _install_traffic_hook():
    import omega
    original = omega.send
    if getattr(original, '_sims4mp_hook', False):
        log('trafic : omega.send deja enveloppe')
        return

    @functools.wraps(original)
    def send(session_id, msg_id, data, *args, **kwargs):
        if _traffic['enabled']:
            try:
                traffic_record(session_id, msg_id, data)
            except Exception:
                _traffic['errors'] += 1
        return original(session_id, msg_id, data, *args, **kwargs)

    send._sims4mp_hook = True
    omega.send = send
    _traffic['installed'] = True
    log('trafic : omega.send enveloppe (mesure arretee par defaut, mp.traffic on)')


# ---------------------------------------------------------------------------
# Menu Sims4MP dans la roue d'actions (Maj + clic sur le sol)
# ---------------------------------------------------------------------------
# Verifie dans simulation.zip : la roue liste les super_affordances de la cible
# (ScriptObject.super_affordances lit cls._super_affordances) ; le sol est
# services.terrain_service.terrain_object(). L'action est creee a l'execution comme
# le jeu le fait pour ses statistiques (statistics/runtime_statistic.RuntimeStatistic
# .generate) : sous-classe d'une ImmediateSuperInteraction reglee (type(base)(nom,
# (base,), {...})), cle sims4.resources.get_resource_key(nom, manager.TYPE), puis
# manager.register_tuned_class. Reglages surcharges : display_name, cheat (roue
# Maj + clic), allow_user_directed, allow_autonomous, visible. Fenetre :
# ui.ui_dialog.UiDialog + UiDialogResponse(dialog_response_id, text,
# ui_request=UiDialogUiRequest.NO_REQUEST), set_responses, show_dialog(on_response),
# reponse lue dans dialog.response.

MENU_NAME = 'sims4mp_menu'
MENU_LABEL = 'Sims4MP…'
MENU_CHOICES = (
    (1, 'Notifications : toutes'),
    (2, 'Notifications : importantes seulement'),
    (3, 'Notifications : aucune'),
    (4, 'État de la partie'),
    (7, 'Resynchroniser maintenant'),
    (8, 'Enregistrer un rapport'),
    (5, 'Jouer seul (se déconnecter)'),
    (6, 'Fermer'),
)
_menu = {'affordance': None, 'error': None, 'opened': 0, 'seen': set()}
MENU_SEEN_MAX = 20                                    # diagnostics de roue differents notes au plus


def _raw(text):
    from sims4.localization import LocalizationHelperTuning
    return lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text)


def menu_status_lines():
    """Resume court pour la fenetre « Etat de la partie »."""
    session = _session
    lines = ['Sims4MP {} , notifications : {}'.format(MOD_VERSION, _notify['level'])]
    if session is None:
        target = _auto['target']
        lines.append('Aucune partie à deux en cours.' if target is None else
                     'Connexion automatique prévue : {}.'.format('hôte' if target[0] == 'host' else
                                                                 'invité vers {}'.format(target[1])))
        return lines
    lines.append('Rôle : {} , autre joueur : {}'.format(
        'hôte' if session.role == 'host' else 'invité',
        'connecté' if session.handshake_done and session.endpoint.is_connected else 'non connecté'))
    if _gate['waiting']:
        lines.append('En attente de l\'autre joueur (pause).')
    if _save_lock['holder'] is not None:
        lines.append('Sauvegarde désactivée ici : seul l\'hôte sauvegarde.')
    if session.last_gaps is not None:
        lines.append('Derniers écarts : {}'.format(', '.join(session.last_gaps) or 'aucun'))
    return lines + sync_lines(session)


def on_menu_choice(choice):
    """Reponse de la fenetre du menu."""
    if choice in (1, 2, 3):
        _notify['level'] = NOTIFY_LEVELS[choice - 1]
        log('menu : notifications {}'.format(_notify['level']))
        if choice != 3:
            bridge_notify('Notifications : {}.'.format('toutes' if choice == 1 else 'importantes seulement'))
    elif choice == 4:
        bridge_show_dialog('État de la partie', '\n'.join(menu_status_lines()), ((6, 'Fermer'),), None)
    elif choice == 7:
        request_resync()
    elif choice == 8:
        path = write_report()
        bridge_notify('Rapport enregistré : {}'.format(path) if path else 'Rapport impossible (voir le journal).')
    elif choice == 5:
        stopped = _auto['target'] is not None or _session is not None
        _auto['target'] = None
        if _session is not None:
            _close_session(send_bye=True)
        _gate_tick(time.monotonic())
        _release_clock_if_unused(None)
        log('menu : jouer seul ({})'.format('partie a deux arretee' if stopped else 'deja seul'))


def bridge_show_dialog(title, text, choices, on_choice):
    """Fenetre du jeu avec un bouton par choix ; on_choice(id) a la reponse."""
    import services
    from ui.ui_dialog import UiDialog, UiDialogResponse
    client = services.client_manager().get_first_client()
    owner = client.active_sim if client is not None else None
    dialog = UiDialog.TunableFactory().default(owner, text=_raw(text), title=_raw(title))
    dialog.set_responses(tuple(
        UiDialogResponse(dialog_response_id=choice_id, text=_raw(label),
                         ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST)
        for choice_id, label in choices))

    def on_response(shown):
        try:
            if on_choice is not None:
                on_choice(shown.response)
        except Exception:
            log('ERREUR menu :\n' + traceback.format_exc())
    dialog.show_dialog(on_response=on_response)


def open_menu():
    _menu['opened'] += 1
    bridge_show_dialog('Sims4MP', '\n'.join(menu_status_lines()[:2]), MENU_CHOICES, on_menu_choice)


def _menu_affordance_class(base):
    """Sous-classe de base (action reglee du jeu) : seule la presentation et l'effet changent."""
    from event_testing.results import TestResult
    from event_testing.tests import TestList

    def _run_interaction_gen(self, timeline):
        try:
            open_menu()
        except Exception:
            log('ERREUR ouverture du menu :\n' + traceback.format_exc())
        return True
        yield                                         # generateur, comme les autres interactions

    @classmethod
    def _test(cls, *args, **kwargs):
        return TestResult.TRUE

    return {
        'INSTANCE_SUBCLASSES_ONLY': True,
        'display_name': staticmethod(_raw(MENU_LABEL)),
        'cheat': True,                                # roue Maj + clic (triches du jeu actives)
        'debug': False,
        'allow_user_directed': True,
        'allow_autonomous': False,
        'visible': True,
        '_test': _test,
        # Interaction.test lance test_globals.run_tests puis tests.run_tests : listes vides
        # (TestList(()).run_tests renvoie TestResult.TRUE), pour que les tests regles de la
        # base ne cachent pas l'entree. Ne pas couper _tunable_tests_enabled : Interaction.test
        # plante alors (target_result non defini, 0.14.1). Le verrou de sauvegarde de
        # l'invite griserait l'entree sans allow_while_save_locked.
        'tests': TestList(()),
        'test_globals': TestList(()),
        'allow_while_save_locked': True,
        '_run_interaction_gen': _run_interaction_gen,
    }


def _menu_base_ok(affordance):
    """Action immediate simple : pas un selecteur (sa roue liste des choix, vide = cachee)."""
    from interactions.base.immediate_interaction import ImmediateSuperInteraction
    from interactions.base.picker_interaction import PickerSuperInteractionMixin
    return issubclass(affordance, ImmediateSuperInteraction) and not issubclass(affordance, PickerSuperInteractionMixin)


def bridge_create_menu_affordance():
    """Cree (une fois) et enregistre l'action « Sims4MP… »."""
    import services
    import sims4.resources
    manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)
    terrain = services.terrain_service.terrain_object()
    candidates = [a for a in type(terrain)._super_affordances if _menu_base_ok(a)]
    if not candidates:
        candidates = [a for a in manager.types.values() if _menu_base_ok(a)]
    if not candidates:
        raise RuntimeError('aucune action immediate du jeu a reprendre')
    base = candidates[0]
    key = sims4.resources.get_resource_key(MENU_NAME, manager.TYPE)
    attributes = _menu_affordance_class(base)
    attributes['guid64'] = key.instance
    menu = type(base)(MENU_NAME, (base,), attributes)
    menu.reloadable = False
    manager.register_tuned_class(menu, key)
    log('menu : action creee (base {} , cle {})'.format(base.__name__, key.instance))
    return menu


def bridge_inject_menu(affordance):
    """Ajoute l'action a la roue du sol (une seule fois). Renvoie True si ajoutee."""
    import services
    terrain_class = type(services.terrain_service.terrain_object())
    current = tuple(terrain_class._super_affordances)
    if affordance in current:
        return False
    terrain_class._super_affordances = current + (affordance,)
    return True


def install_menu():
    """Appele a chaque fin de chargement : cree l'action une fois et la remet sur le sol."""
    try:
        if _menu['affordance'] is None:
            _menu['affordance'] = bridge_create_menu_affordance()
        if bridge_inject_menu(_menu['affordance']):
            log('menu : « {} » ajoute a la roue Maj + clic du sol'.format(MENU_LABEL))
        _menu['error'] = None
    except Exception:
        _menu['error'] = traceback.format_exc().strip().splitlines()[-1]
        log('ERREUR menu Sims4MP :\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
# Fiabilite (0.13.0) : seul l'hote sauvegarde, resynchro, detecteur d'ecarts, rapport
# ---------------------------------------------------------------------------
# Verrou de sauvegarde du jeu (services/persistence_service.pyc) :
# services.get_persistence_service().lock_save(porteur) / unlock_save(porteur) ;
# le motif affiche vient de porteur.get_lock_save_reason().

_save_lock = {'holder': None}


class _GuestSaveLock(object):
    """Porteur du verrou de sauvegarde chez l'invite."""

    def get_lock_save_reason(self):
        from sims4.localization import LocalizationHelperTuning
        return LocalizationHelperTuning.get_raw_text('Partie à deux : seul l\'hôte sauvegarde la partie commune.')


def bridge_lock_save(holder):
    import services
    services.get_persistence_service().lock_save(holder)


def bridge_unlock_save(holder):
    import services
    services.get_persistence_service().unlock_save(holder)


def _save_lock_tick(session):
    """Invite connecte : sauvegarde verrouillee ; sinon deverrouillee."""
    wanted = session is not None and session.role == 'client' and session.handshake_done
    holder = _save_lock['holder']
    if wanted and holder is None:
        holder = _GuestSaveLock()
        try:
            bridge_lock_save(holder)
        except Exception:
            _sync_error('verrou de sauvegarde')
            return
        _save_lock['holder'] = holder
        log('sauvegarde : verrouillee chez l\'invite')
        bridge_notify('Sauvegarde désactivée chez vous : seul l\'hôte sauvegarde la partie commune.',
                      key='save-lock')
    elif not wanted and holder is not None:
        _save_lock['holder'] = None
        _safe('fin du verrou de sauvegarde', bridge_unlock_save, holder)
        log('sauvegarde : deverrouillee')


def request_resync():
    """Menu : resynchro complete (l'invite la demande a l'hote ; l'hote l'envoie directement)."""
    session = _session
    if session is None or not session.handshake_done:
        bridge_notify('Aucune partie à deux en cours : rien à resynchroniser.')
        return
    if session.role == 'client':
        session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'resync_request'}))
        log('[client] resynchro demandee a l\'hote')
        bridge_notify('Resynchronisation demandée à l\'hôte…')
    else:
        do_resync(session)


def do_resync(session):
    """Hote : renvoie tout (argent, heure, positions, besoins) au prochain passage de la pompe."""
    session.money_total_sent = False                 # l'invite se realigne sur le solde de l'hote
    session.needs_sent.clear()
    session.sims_sent.clear()
    session.position_sent = None
    session.clock_sent_at = 0.0
    session.resyncs += 1
    session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'resync'}))
    log('[host] resynchro complete envoyee')
    bridge_notify('Resynchronisation complète envoyée à l\'invité.')


def _handle_resync(session):
    """Invite : prepare l'application immediate de tout ce que l'hote renvoie."""
    session.money_aligned = False
    session.walk = None
    session.sims_walk.clear()
    session.action_hold.clear()
    session.clock_grace_until = 0.0
    session.clock_strikes = CLOCK_CONFIRM - 1        # le prochain ecart d'heure est corrige aussitot
    session.position_sent = None
    session.needs_sent.clear()
    session.resyncs += 1
    log('[client] resynchro complete recue')
    bridge_notify('Resynchronisation complète reçue de l\'hôte.')


# -- detecteur d'ecarts : toutes les 30 s, l'hote envoie un resume ; l'invite compare --

def bridge_digest():
    """Resume de la partie locale : argent, foyer, heure, positions des Sims presents."""
    funds = _safe('lecture argent', bridge_funds)
    clock = _safe('lecture heure', bridge_clock)
    sims = {}
    for sim_id in (_safe('liste des Sims', bridge_instanced_sim_ids) or [])[:DIGEST_MAX_SIMS]:
        snapshot = _safe('position d\'un Sim', bridge_sim_snapshot, sim_id)
        if snapshot is not None:
            sims[str(sim_id)] = [round(snapshot['x'], 1), round(snapshot['z'], 1)]
    return {'kind': 'digest', 'household_id': funds[0] if funds else None, 'money': funds[1] if funds else None,
            'seconds': clock[0] if clock else None, 'sims': sims}


def _digest_tick(session, now):
    if session.role != 'host' or not (session.endpoint.is_connected and session.handshake_done):
        return
    if _gate['waiting'] or now - session.digest_sent_at < DIGEST_INTERVAL:
        return
    session.digest_sent_at = now
    session.endpoint.send(protocol.make_message(protocol.EVENT, bridge_digest()))


def compare_digest(session, remote, local):
    """Liste lisible des ecarts entre le resume de l'hote et la partie de l'invite."""
    gaps = []
    if (remote.get('household_id') == local.get('household_id') and isinstance(remote.get('money'), int)
            and isinstance(local.get('money'), int) and remote['money'] != local['money']):
        gaps.append('argent {:+d} § par rapport à l\'hôte'.format(local['money'] - remote['money']))
    if isinstance(remote.get('seconds'), (int, float)) and isinstance(local.get('seconds'), (int, float)):
        drift = local['seconds'] - remote['seconds']
        if abs(drift) > DIGEST_TIME_GAP:
            gaps.append('heure {:+.0f} min de jeu'.format(drift / 60.0))
    remote_sims = remote.get('sims') if isinstance(remote.get('sims'), dict) else {}
    local_sims = local.get('sims') or {}
    only_host = [k for k in remote_sims if k not in local_sims]
    only_here = [k for k in local_sims if k not in remote_sims]
    if only_host:
        gaps.append('{} Sim(s) seulement chez l\'hôte'.format(len(only_host)))
    if only_here:
        gaps.append('{} Sim(s) seulement chez vous'.format(len(only_here)))
    mine = _my_active_id()
    far = 0
    for key, where in remote_sims.items():
        here = local_sims.get(key)
        if (here is None or not isinstance(where, list) or len(where) != 2
                or (mine is not None and key == str(mine))):
            continue
        try:
            if ((here[0] - float(where[0])) ** 2 + (here[1] - float(where[1])) ** 2) ** 0.5 > DIGEST_FAR:
                far += 1
        except (TypeError, ValueError):
            continue
    if far:
        gaps.append('{} Sim(s) loin de leur place chez l\'hôte'.format(far))
    return gaps


def _handle_digest(session, data):
    gaps = compare_digest(session, data, bridge_digest())
    session.last_gaps = gaps
    session.endpoint.send(protocol.make_message(protocol.EVENT, {'kind': 'gaps', 'list': gaps[:10]}))
    if gaps:
        log('[client] ecarts : ' + ', '.join(gaps))
        bridge_notify('Écarts avec l\'hôte : {}. Menu Sims4MP → Resynchroniser maintenant.'.format(
            ', '.join(gaps)), alert=True, key='gaps')


def _handle_gaps(session, data):
    entries = data.get('list')
    if not isinstance(entries, list):
        return
    gaps = [_clean_text(g) for g in entries[:10] if _clean_text(g)]
    session.last_gaps = gaps
    if gaps:
        log('[host] ecarts chez l\'invite : ' + ', '.join(gaps))
        bridge_notify('Écarts chez l\'invité : {}. Menu Sims4MP → Resynchroniser maintenant.'.format(
            ', '.join(gaps)), alert=True, key='gaps')


# -- journal lisible --

def rotate_log(path=None, limit=None):
    """Au chargement : un journal trop gros devient sims4mp.old.log (l'ancien est remplace)."""
    path = path or LOG_PATH
    limit = LOG_MAX_SIZE if limit is None else limit
    try:
        if os.path.isfile(path) and os.path.getsize(path) > limit:
            os.replace(path, path[:-4] + '.old.log' if path.endswith('.log') else path + '.old')
            return True
    except OSError:
        pass
    return False


def write_report():
    """Rapport a envoyer : etat de la partie et fin du journal, a cote du journal."""
    path = os.path.join(os.path.dirname(LOG_PATH), REPORT_NAME)
    try:
        tail = []
        if os.path.isfile(LOG_PATH):
            with open(LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
                tail = f.readlines()[-REPORT_LOG_LINES:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('Rapport Sims4MP {} - {}\n\n'.format(MOD_VERSION, time.strftime('%Y-%m-%d %H:%M:%S')))
            f.write('\n'.join(menu_status_lines()) + '\n')
            f.write('Notifications masquees : {} , regroupees : {}\n'.format(_notify['hidden'], _notify['grouped']))
            if _menu['error'] or _pump['error']:
                f.write('Erreurs : menu {} , pompe {}\n'.format(_menu['error'], _pump['error']))
            f.write('\n--- Fin du journal ---\n')
            f.writelines(tail)
        log('rapport ecrit : ' + path)
        return path
    except Exception:
        log('ERREUR rapport :\n' + traceback.format_exc())
        return None


def _menu_diag(text):
    """Note une fois chaque situation de la roue pour l'entree Sims4MP (diagnostic)."""
    if text in _menu['seen'] or len(_menu['seen']) >= MENU_SEEN_MAX:
        return
    _menu['seen'].add(text)
    log('menu (roue) : ' + text)


def _install_menu_diag_hook():
    """Roue du jeu (server_commands.interaction_commands.generate_choices ->
    ChoiceMenu.add_potential_aops -> ChoiceMenu.add_aop, verifie dans simulation.zip) :
    note si l'entree Sims4MP est proposee et le resultat du test du jeu."""
    from interactions.choices import ChoiceMenu
    original_potential = ChoiceMenu.add_potential_aops
    original_add = ChoiceMenu.add_aop
    if getattr(original_add, '_sims4mp_hook', False):
        return

    @functools.wraps(original_potential)
    def add_potential_aops(self, target, context, potential_aops, *args, **kwargs):
        try:
            menu = _menu['affordance']
            if menu is not None and getattr(context, 'shift_held', False):
                present = any(getattr(aop, 'affordance', None) is menu for aop in potential_aops)
                _menu_diag('entree {} parmi les {} actions de {}'.format(
                    'presente' if present else 'ABSENTE', len(potential_aops), type(target).__name__))
        except Exception:
            _menu_diag('erreur diagnostic : ' + traceback.format_exc().strip().splitlines()[-1])
        return original_potential(self, target, context, potential_aops, *args, **kwargs)

    @functools.wraps(original_add)
    def add_aop(self, aop, *args, **kwargs):
        result = original_add(self, aop, *args, **kwargs)
        try:
            if _menu['affordance'] is not None and getattr(aop, 'affordance', None) is _menu['affordance']:
                _menu_diag('test du jeu : {} ({})'.format('OK' if result else 'REFUSE',
                                                          getattr(result, 'reason', None)))
        except Exception:
            _menu_diag('erreur diagnostic : ' + traceback.format_exc().strip().splitlines()[-1])
        return result

    add_aop._sims4mp_hook = True
    ChoiceMenu.add_potential_aops = add_potential_aops
    ChoiceMenu.add_aop = add_aop
    _install_rollback_diag_hook()
    _install_pie_message_diag_hook()


def _install_pie_message_diag_hook():
    """generate_choices appelle create_pie_menu_message (nom global du module
    server_commands.interaction_commands) : on note si le bouton Sims4MP est dans le
    message final envoye a l'affichage (champs items[].affordance_id / loc_string)."""
    import server_commands.interaction_commands as commands_module
    original = commands_module.create_pie_menu_message
    if getattr(original, '_sims4mp_hook', False):
        return

    @functools.wraps(original)
    def create_pie_menu_message(sim, choice_menu, *args, **kwargs):
        msg = original(sim, choice_menu, *args, **kwargs)
        try:
            menu = _menu['affordance']
            if menu is not None and choice_menu is not None:
                proposed = any(getattr(getattr(item, 'aop', None), 'affordance', None) is menu
                               for _, item in choice_menu)
                if proposed:
                    items = list(getattr(msg, 'items', ()))
                    mine = [item for item in items if getattr(item, 'affordance_id', None) == menu.guid64]
                    _menu_diag('message de la roue : {} bouton(s), Sims4MP {}{}'.format(
                        len(items), 'present' if mine else 'ABSENT',
                        ' (nom {!r}, priorite {!r})'.format(
                            str(getattr(mine[0], 'loc_string', ''))[:120],
                            getattr(mine[0], 'pie_menu_priority', None)) if mine else ''))
        except Exception:
            _menu_diag('erreur diagnostic message : ' + traceback.format_exc().strip().splitlines()[-1])
        return msg

    create_pie_menu_message._sims4mp_hook = True
    commands_module.create_pie_menu_message = create_pie_menu_message


def _install_rollback_diag_hook():
    """Chaque bouton de la roue est construit dans un ProtocolBufferRollback
    (interaction_commands.create_pie_menu_message) ; son __exit__ (distributor/rollback.pyc)
    retire le bouton et avale l'erreur. On note cette erreur quand elle vient de la roue."""
    from distributor.rollback import ProtocolBufferRollback
    original = ProtocolBufferRollback.__exit__
    if getattr(original, '_sims4mp_hook', False):
        return

    @functools.wraps(original)
    def __exit__(self, exc_type, value, tb):
        if exc_type is not None:
            try:
                lines = traceback.format_exception(exc_type, value, tb)
                if any('create_pie_menu_message' in line for line in lines):
                    _menu_diag('bouton retire par le jeu apres une erreur :\n' + ''.join(lines).strip())
            except Exception:
                pass
        return original(self, exc_type, value, tb)

    __exit__._sims4mp_hook = True
    ProtocolBufferRollback.__exit__ = __exit__


def _install_cancel_hook():
    """La croix du joueur (interaction_commands.cancel_common -> Interaction.cancel_user,
    verifie dans simulation.zip) : apres l'original, une annulation acceptee est transmise."""
    from interactions.base.interaction import Interaction
    original = Interaction.cancel_user
    if getattr(original, '_sims4mp_hook', False):
        return

    @functools.wraps(original)
    def cancel_user(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            if result:
                on_user_cancel(self)
        except Exception:
            _sync_error('suivi des annulations')
        return result

    cancel_user._sims4mp_hook = True
    Interaction.cancel_user = cancel_user
    log('synchro : annulations du joueur suivies (Interaction.cancel_user)')


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
            if queue_refuses(interaction) or autonomy_refused(self, interaction):
                refused = bridge_refused_action()
        except Exception:
            # En cas d'erreur du mod, le jeu garde son comportement normal.
            log('ERREUR file d\'attente :\n' + traceback.format_exc())
        if refused is not None:
            return refused
        result = original(self, interaction, *args, **kwargs)
        try:
            # Seulement une action que le jeu vient d'accepter (sinon l'autonomie, qui reessaie
            # aussitot, inonderait l'autre PC). Ordre du joueur de ce PC : « le dernier ordre
            # gagne » et envoi immediat (M5) ; action autonome d'un Sim dont ce PC fait foi (M6).
            if result and not _sync['pushing']:
                if _is_user_directed(interaction):
                    record_local_order(self.sim.sim_info.sim_id)
                    on_player_order(self, interaction)
                else:
                    on_autonomy_action(self, interaction)
        except Exception:
            _sync_error('suivi des ordres du joueur')
        return result

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
    'solo': False,           # mp.solo : plus de connexion automatique jusqu'a la fermeture du jeu
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
    if _auto['solo']:
        _auto['target'] = None
        log('auto : mode solo (mp.solo), reglage du lanceur ignore jusqu\'a la fermeture du jeu')
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
    install_menu()                                   # protege lui-meme ses erreurs
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
        for line in position_lines(session, time.monotonic()) + sync_lines(session):
            output(line)
    except Exception:
        log('ERREUR mp.positions :\n' + traceback.format_exc())
        output('Erreur dans mp.positions (voir le journal).')


@sims4.commands.Command('mp.traffic', command_type=sims4.commands.CommandType.Live)
def mp_traffic(action=None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        if not _traffic['installed']:
            output('Mesure indisponible (voir le journal).')
            return
        now = time.monotonic()
        if action == 'on':
            traffic_reset(now)
            _traffic['enabled'] = True
            log('trafic : mesure lancee')
            output('Mesure du trafic lancee. mp.traffic pour le resultat, mp.traffic off pour arreter.')
            return
        if action == 'off':
            _traffic['enabled'] = False
            log('trafic : mesure arretee\n  ' + '\n  '.join(traffic_lines(now)))
            output('Mesure arretee (resultat aussi dans le journal).')
        elif action is not None:
            output('Usage : mp.traffic [on|off]')
            return
        for line in traffic_lines(now):
            output(line)
    except Exception:
        log('ERREUR mp.traffic :\n' + traceback.format_exc())
        output('Erreur dans mp.traffic (voir le journal).')


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
        _release_clock_if_unused(None)
        output('Session fermee.' + (' Connexion automatique arretee.' if stopped_auto else ''))
    except Exception:
        log('ERREUR mp.disconnect :\n' + traceback.format_exc())
        output('Erreur dans mp.disconnect (voir le journal).')


@sims4.commands.Command('mp.menu', command_type=sims4.commands.CommandType.Live)
def mp_menu(_connection=None):
    """Ouvre la fenetre Sims4MP (memes choix que l'entree de la roue Maj + clic)."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        open_menu()
        log('mp.menu : fenetre Sims4MP ouverte')
    except Exception:
        log('ERREUR mp.menu :\n' + traceback.format_exc())
        output('Erreur dans mp.menu (voir le journal).')


@sims4.commands.Command('mp.solo', command_type=sims4.commands.CommandType.Live)
def mp_solo(_connection=None):
    """Jouer seul jusqu'a la fermeture du jeu : ferme la partie a deux, leve la pause et
    ignore le reglage du lanceur aux chargements suivants (voyage, autre lot, autre partie).
    mp.host / mp.join restent possibles a la main."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        _auto['solo'] = True
        _auto['target'] = None
        had_session = _session is not None
        if had_session:
            _close_session(send_bye=True)
        _gate_tick(time.monotonic())                 # leve la pause tout de suite
        _release_clock_if_unused(None)
        log('mp.solo : mode solo jusqu\'a la fermeture du jeu ({})'.format(
            'partie a deux arretee' if had_session else 'aucune session'))
        output('Mode solo jusqu\'a la fermeture du jeu : plus de connexion automatique, '
               'meme apres un voyage ou un chargement.' + (' Partie a deux arretee.' if had_session else ''))
    except Exception:
        log('ERREUR mp.solo :\n' + traceback.format_exc())
        output('Erreur dans mp.solo (voir le journal).')


# ---------------------------------------------------------------------------
# Au chargement du mod (demarrage du jeu)
# ---------------------------------------------------------------------------

try:
    rotated = rotate_log()                           # journal trop gros : sims4mp.old.log
    log('==== {} {} charge ===='.format(MOD_NAME, MOD_VERSION))
    if rotated:
        log('journal precedent renomme en sims4mp.old.log')
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
    _install_cancel_hook()
except Exception:
    log('ERREUR installation suivi des annulations :\n' + traceback.format_exc())

try:
    _install_menu_diag_hook()
except Exception:
    log('ERREUR installation diagnostic de la roue :\n' + traceback.format_exc())

try:
    _install_speed_hook()
except Exception:
    # Sans ce hook, seule la vitesse de l'hote compte (les boutons de l'invite restent sans effet).
    log('ERREUR installation suivi des boutons de vitesse :\n' + traceback.format_exc())

try:
    _install_traffic_hook()
except Exception:
    # Sans ce hook, seule la mesure du trafic (mp.traffic) est indisponible.
    log('ERREUR installation mesure du trafic :\n' + traceback.format_exc())

try:
    _install_queue_hook()
except Exception:
    # Sans ce hook, la pause reste imposee mais la file n'est pas bloquee.
    log('ERREUR installation blocage de la file :\n' + traceback.format_exc())
