# Sims 4 Multiplayer - test hors jeu des notifications plus claires et des alertes
# de desynchro (0.12.0). Compatible Python 3.7. A lancer avec :  py -3.7 test_notify.py
#
# Faux modules du jeu : notification (UiDialogNotification avec urgence), portrait
# (IconInfoData), Sims. Les sessions sont simulees (pas de reseau).

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
localization = module('sims4.localization',
                      LocalizationHelperTuning=types.SimpleNamespace(get_raw_text=lambda text: 'raw:' + text))
module('sims4', commands=commands, localization=localization)


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)
SHOWN = []


class FakeNotification(object):
    def __init__(self, owner, text, title, urgency=None):
        self.owner, self.text, self.title, self.urgency = owner, text(), title(), urgency

    def show_dialog(self, **kwargs):
        SHOWN.append((self, kwargs))


class UiDialogNotification(object):
    UiDialogNotificationUrgency = types.SimpleNamespace(DEFAULT=0, URGENT=1)

    @staticmethod
    def TunableFactory():
        return types.SimpleNamespace(default=lambda owner, **kw: FakeNotification(owner, **kw))


module('ui')
module('ui.ui_dialog_notification', UiDialogNotification=UiDialogNotification)
module('distributor')
module('distributor.shared_messages', IconInfoData=lambda obj_instance=None: ('icon', obj_instance))
module('objects', ALL_HIDDEN_REASONS='ALL')
SIM = types.SimpleNamespace(name='Constance')
SIM_INFO = types.SimpleNamespace(get_sim_instance=lambda allow_hidden_flags=None: SIM)
module('services', client_manager=lambda: types.SimpleNamespace(
    get_first_client=lambda: types.SimpleNamespace(active_sim='Elise')),
    sim_info_manager=lambda: types.SimpleNamespace(get={42: SIM_INFO}.get))

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402

results = []
TMP = tempfile.mkdtemp(prefix='sims4mp_notify_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


class Endpoint(object):
    def __init__(self):
        self.sent = []
        self.is_connected = True

    def send(self, message):
        self.sent.append(message)
        return True


# --- 1. Notification du jeu : portrait et urgence ---------------------------------------
mod.bridge_notify('L\'invité contrôle Constance.', sim_id=42)
dialog, kwargs = SHOWN[-1]
report('portrait du Sim concerne (icon_override) et titre Sims4MP',
       kwargs == {'icon_override': ('icon', SIM)} and dialog.title == 'raw:Sims4MP'
       and dialog.text == 'raw:L\'invité contrôle Constance.' and dialog.urgency is None)
mod.bridge_notify('Heure recalée.', alert=True)
dialog, kwargs = SHOWN[-1]
report('alerte : titre « Sims4MP · alerte », urgente, sans portrait',
       dialog.title == 'raw:Sims4MP · alerte' and dialog.urgency == 1 and kwargs == {})
mod.bridge_notify('Sim inconnu.', sim_id=999)
report('Sim introuvable : notification sans portrait', SHOWN[-1][1] == {})

# A partir d'ici, on compte simplement les notifications.
shown = []
mod.show_notification = lambda title, text, sim_id=None, urgent=False: shown.append((title, text, sim_id, urgent))

# --- 2. Regroupement --------------------------------------------------------------------
for _ in range(3):
    mod.bridge_notify('Connexion lente avec l\'hôte.', alert=True, key='slow')
report('meme alerte trois fois de suite : une seule affichee', len(shown) == 1 and mod._notify['grouped'] == 2)
mod._notify['last']['slow'] -= mod.ALERT_REPEAT + 1
mod.bridge_notify('Connexion lente avec l\'hôte.', alert=True, key='slow')
report('apres {:.0f} s : de nouveau affichee'.format(mod.ALERT_REPEAT), len(shown) == 2)
mod.bridge_notify('Sans cle.')
mod.bridge_notify('Sans cle.')
report('notifications sans cle jamais regroupees', len(shown) == 4)

# --- 3. Latence, ping automatique, resume ------------------------------------------------
client = mod.NetSession('client', Endpoint())
client.handshake_done = True
mod._auto_ping_tick(client, 100.0)
ping = client.endpoint.sent[-1]
report('invite : ping automatique silencieux', ping['type'] == protocol.PING and ping['data'].get('auto') is True
       and ping['data']['seq'] in client.auto_pings)
del shown[:]
client.pending_pings[ping['data']['seq']] = time.monotonic() - 0.05
mod._handle_pong(client, {'seq': ping['data']['seq'], 'sent_at': 0})
report('reponse au ping automatique : latence notee, aucune notification',
       client.rtt_ms is not None and 40 <= client.rtt_ms <= 500 and shown == [])
mod._auto_ping_tick(client, 105.0)
report('pas de nouveau ping avant {:.0f} s'.format(mod.AUTO_PING_INTERVAL), len(client.endpoint.sent) == 1)
mod._maybe_send_presence(client, 200.0)
report('la presence porte la latence (l\'hote la connait)', client.endpoint.sent[-1]['data'].get('rtt') is not None)
host = mod.NetSession('host', Endpoint())
host.handshake_done = True
mod._notify['last'].clear()                                  # la cle « slow » a servi plus haut
mod._note_rtt(host, 650.0)
report('latence elevee : alerte « connexion lente »', shown and shown[-1][0] == 'Sims4MP · alerte'
       and 'Connexion lente avec l\'invité : 650 ms' in shown[-1][1])
host.remote_position = {'sim_id': 42, 'name': 'Constance'}
report('resume de connexion', mod.summary_text(host) == 'Partie à deux : Vous êtes l\'hôte · mod {} · ping 650 ms · '
       'l\'invité contrôle Constance.'.format(mod.MOD_VERSION), mod.summary_text(host))
host.summary_due = 1.0
del shown[:]
mod._summary_tick(host, 2.0)
mod._summary_tick(host, 3.0)
report('resume affiche une seule fois, avec le portrait du Sim de l\'autre',
       len(shown) == 1 and shown[0][2] == 42 and shown[0][1].startswith('Partie à deux'))

# --- 4. Alertes de desynchro ----------------------------------------------------------------
del shown[:]
mod._alert_missing_sim(host, {'sim_id': 7, 'name': 'Voisin'}, 'Sim absent du lot ici')
mod._alert_missing_sim(host, {'sim_id': 7, 'name': 'Voisin'}, 'Sim absent du lot ici')
mod._alert_missing_sim(host, {'sim_id': 8, 'name': 'Livreur'}, 'en place')
report('Sim present d\'un seul cote : alerte une fois par Sim', len(shown) == 1
       and 'Voisin est sur le lot chez l\'invité, pas chez vous' in shown[0][1])
mod._notify['level'] = 'important'
mod._alert_missing_sim(host, {'sim_id': 9, 'name': 'Passant'}, 'Sim inconnu ici : ce n\'est pas la meme sauvegarde')
report('cette alerte est secondaire (masquee en mode « importantes »)', len(shown) == 1)
mod._notify['level'] = 'tout'

shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
