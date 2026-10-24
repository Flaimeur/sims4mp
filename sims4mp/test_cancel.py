# Sims 4 Multiplayer - test hors jeu de l'annulation d'une action (0.14.0).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_cancel.py
#
# Faux modules du jeu : Interaction (cancel_user / cancel), FinishingType.
# Les sessions sont simulees (pas de reseau).

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
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)
FinishingType = types.SimpleNamespace(USER_CANCEL='USER_CANCEL', NATURAL='NATURAL')


class Interaction(object):
    def __init__(self, name):
        self.name = name
        self.canceled = None
        self.is_finishing = False

    def cancel_user(self, cancel_reason_msg=None, on_response=None):
        # Comme le jeu : refuse si deja en cours d'annulation, sinon annule (USER_CANCEL).
        if self.is_finishing:
            return False
        self.cancel(FinishingType.USER_CANCEL, cancel_reason_msg=cancel_reason_msg)
        return True

    def cancel(self, finishing_type, cancel_reason_msg=None, ignore_must_run=False):
        self.canceled = (finishing_type, cancel_reason_msg)
        self.is_finishing = True
        return True


module('interactions')
module('interactions.base')
module('interactions.base.interaction', Interaction=Interaction)
module('interactions.interaction_finisher', FinishingType=FinishingType)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
mod._mirror['wanted'] = False                        # ancienne synchro (option A) : mp.mirror off depuis 0.21.0

results = []
notes = []
mod.show_notification = lambda title, text, *args: notes.append(text)
TMP = tempfile.mkdtemp(prefix='sims4mp_cancel_')
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


def events(endpoint, kind):
    return [m['data'] for m in endpoint.sent if m['type'] == protocol.EVENT and m['data'].get('kind') == kind]


report('croix du joueur suivie (Interaction.cancel_user enveloppe)',
       getattr(Interaction.cancel_user, '_sims4mp_hook', False))

host = mod.NetSession('host', Endpoint())
host.handshake_done = True
mod._session = host
mod._gate['waiting'] = False

# --- 1. Ordre envoye puis annule par le joueur de ce PC ------------------------------------
sit = Interaction('seating_Sit')
order_id = mod.send_player_order({'sim_id': 1, 'affordance': 5, 'name': 'seating_Sit',
                                  'target': {'t': 'none'}, 'auto': False}, sit)
report('ordre envoye relie a l\'action locale', order_id == 'host-1' and mod.order_of(sit) == 'host-1')
sit.cancel_user()
cancels = events(host.endpoint, 'cancel')
report('croix sur cette action : annulation envoyee avec l\'identifiant de l\'ordre',
       cancels == [{'kind': 'cancel', 'order_id': 'host-1'}] and host.cancels_sent == 1)
other = Interaction('autonome_non_reliee')
other.cancel_user()
report('action non envoyee a l\'autre PC : rien n\'est transmis', len(events(host.endpoint, 'cancel')) == 1)
finishing = Interaction('deja_finie')
mod.send_player_order({'sim_id': 1, 'affordance': 6, 'name': 'x', 'target': {'t': 'none'}, 'auto': False}, finishing)
finishing.is_finishing = True
finishing.cancel_user()
report('annulation refusee par le jeu : rien n\'est transmis', len(events(host.endpoint, 'cancel')) == 1)

# --- 2. Annulation recue pour une action rejouee ici ---------------------------------------
replayed = Interaction('bed_sleep')
mod.link_order('client-7', replayed)
del notes[:]
mod._handle_cancel(host, {'kind': 'cancel', 'order_id': 'client-7'})
report('annulation recue : l\'action rejouee est annulee comme par la croix (USER_CANCEL)',
       replayed.canceled and replayed.canceled[0] == 'USER_CANCEL' and host.cancels_applied == 1
       and any('a annulé une action' in n for n in notes))
report('pas d\'annulation renvoyee en echo', len(events(host.endpoint, 'cancel')) == 1)
mod._handle_cancel(host, {'kind': 'cancel', 'order_id': 'client-7'})
mod._handle_cancel(host, {'kind': 'cancel', 'order_id': 'client-404'})
mod._handle_cancel(host, {'kind': 'cancel', 'order_id': 12})
report('deja annulee, inconnue ou mal formee : rien de plus', host.cancels_applied == 1)

# --- 3. Memoire bornee -------------------------------------------------------------------------
for n in range(mod.LINKS_MAX + 50):
    mod.link_order('x-{}'.format(n), Interaction('i{}'.format(n)))
report('liens gardes en nombre limite ({})'.format(mod.LINKS_MAX), len(mod._sync['links']) == mod.LINKS_MAX
       and 'x-0' not in mod._sync['links'])

del _CheatOutput.lines[:]
mod.mp_positions()
report('mp.positions : compteur d\'annulations', any('Annulations : 1 envoyee(s), 1 appliquee(s)' in line
                                                      for line in _CheatOutput.lines), str(_CheatOutput.lines[-3:]))

mod._session = None
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
