# Sims 4 Multiplayer - transport TCP non bloquant.
# Compatible Python 3.7. Aucune dependance au jeu (pas d'import sims4).
#
# - Aucun thread : l'appelant appelle poll() regulierement (depuis la pompe du
#   jeu plus tard). poll() utilise select(timeout=0) et ne bloque jamais.
# - Trame : 4 octets de longueur (big-endian, non signe) + contenu JSON UTF-8.
# - Le serveur n'accepte qu'un seul client ; les suivants recoivent REJECT.
#
# poll() renvoie une liste d'evenements (tuples) :
#   ('connected', adresse)
#   ('message', dict)
#   ('disconnected', raison)

import errno
import select
import socket
import struct

import protocol

HEADER = struct.Struct('>I')
RECV_SIZE = 65536

_CONNECT_PENDING = (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
                    getattr(errno, 'WSAEWOULDBLOCK', errno.EWOULDBLOCK))


def frame(payload):
    return HEADER.pack(len(payload)) + payload


class FrameDecoder(object):
    """Reassemble les trames a partir d'un flux d'octets decoupe arbitrairement."""

    def __init__(self, max_size=protocol.MAX_MESSAGE_SIZE):
        self._buffer = bytearray()
        self._max_size = max_size

    def feed(self, data):
        """Ajoute des octets, renvoie la liste des contenus complets (bytes)."""
        self._buffer.extend(data)
        payloads = []
        while len(self._buffer) >= HEADER.size:
            (length,) = HEADER.unpack_from(self._buffer, 0)
            if length > self._max_size:
                raise protocol.ProtocolError('trame trop grosse : {} octets'.format(length))
            end = HEADER.size + length
            if len(self._buffer) < end:
                break
            payloads.append(bytes(self._buffer[HEADER.size:end]))
            del self._buffer[:end]
        return payloads


class Connection(object):
    """Une socket connectee, avec tampons d'entree et de sortie."""

    def __init__(self, sock, address):
        sock.setblocking(False)
        self.sock = sock
        self.address = address
        self.closed = False
        self._decoder = FrameDecoder()
        self._outbuf = bytearray()

    def send(self, message):
        self._outbuf.extend(frame(protocol.encode_message(message)))

    def wants_write(self):
        return bool(self._outbuf)

    def handle_read(self):
        """Lit tout ce qui est disponible. Renvoie (messages, raison_fermeture)."""
        messages = []
        while True:
            try:
                data = self.sock.recv(RECV_SIZE)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as e:
                return messages, 'erreur de lecture : {}'.format(e)
            if not data:
                return messages, 'connexion fermee par le pair'
            try:
                for payload in self._decoder.feed(data):
                    messages.append(protocol.decode_message(payload))
            except protocol.ProtocolError as e:
                return messages, 'erreur de protocole : {}'.format(e)
        return messages, None

    def handle_write(self):
        """Envoie le plus possible. Renvoie une raison de fermeture ou None."""
        while self._outbuf:
            try:
                sent = self.sock.send(self._outbuf)
            except (BlockingIOError, InterruptedError):
                return None
            except OSError as e:
                return 'erreur d\'ecriture : {}'.format(e)
            if sent == 0:
                return None
            del self._outbuf[:sent]
        return None

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


def _pump_connection(conn, readable, events):
    """Traite lecture/ecriture d'une connexion. Renvoie True si elle est fermee.

    L'ecriture est tentee des qu'il y a des donnees en attente : la socket est
    non bloquante, un envoi impossible est simplement reporte au poll suivant.
    """
    if conn.sock in readable:
        messages, reason = conn.handle_read()
        for message in messages:
            events.append(('message', message))
        if reason is not None:
            conn.close()
            events.append(('disconnected', reason))
            return True
    if conn.wants_write():
        reason = conn.handle_write()
        if reason is not None:
            conn.close()
            events.append(('disconnected', reason))
            return True
    return False


# ---------------------------------------------------------------------------
# Serveur (host)
# ---------------------------------------------------------------------------

class Server(object):

    def __init__(self, host='0.0.0.0', port=0):
        self.host = host
        self.port = port
        self._listener = None
        self.conn = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setblocking(False)
            listener.bind((self.host, self.port))
            listener.listen(1)
        except OSError:
            listener.close()
            raise
        self._listener = listener
        self.port = listener.getsockname()[1]

    @property
    def is_connected(self):
        return self.conn is not None and not self.conn.closed

    def send(self, message):
        if not self.is_connected:
            return False
        self.conn.send(message)
        return True

    def poll(self):
        events = []
        if self._listener is None:
            return events

        sockets = [self._listener]
        if self.is_connected:
            sockets.append(self.conn.sock)

        try:
            readable, _, _ = select.select(sockets, [], [], 0)
        except (OSError, ValueError) as e:
            events.append(('disconnected', 'erreur select : {}'.format(e)))
            self._drop_client()
            return events

        if self._listener in readable:
            self._accept(events)

        if self.is_connected:
            if _pump_connection(self.conn, readable, events):
                self.conn = None
        return events

    def _accept(self, events):
        while True:
            try:
                sock, address = self._listener.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            if self.is_connected:
                self._refuse(sock, 'serveur deja occupe')
            else:
                self.conn = Connection(sock, address)
                events.append(('connected', address))

    def _refuse(self, sock, reason):
        # Tentative unique et non bloquante : le REJECT peut etre perdu,
        # le client verra alors simplement la fermeture.
        try:
            sock.setblocking(False)
            sock.send(frame(protocol.encode_message(protocol.reject(reason))))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _drop_client(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def disconnect_client(self):
        self._drop_client()

    def close(self):
        self._drop_client()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Client(object):

    IDLE = 'idle'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    CLOSED = 'closed'

    def __init__(self, host, port, local_port=0):
        self.host = host
        self.port = port
        self.local_port = local_port
        self.state = Client.IDLE
        self.conn = None
        self._pending = []

    def connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setblocking(False)
            if self.local_port:
                sock.bind(('', self.local_port))
            code = sock.connect_ex((self.host, self.port))
        except OSError:
            sock.close()
            raise
        if code != 0 and code not in _CONNECT_PENDING:
            sock.close()
            raise OSError(code, 'connexion impossible')
        self.local_port = sock.getsockname()[1]
        self.conn = Connection(sock, (self.host, self.port))
        self.state = Client.CONNECTING

    @property
    def is_connected(self):
        return self.state == Client.CONNECTED

    def send(self, message):
        """Met le message en file. Autorise pendant la connexion (envoye ensuite)."""
        if self.state == Client.CONNECTED:
            self.conn.send(message)
            return True
        if self.state == Client.CONNECTING:
            self._pending.append(message)
            return True
        return False

    def poll(self):
        events = []
        if self.state not in (Client.CONNECTING, Client.CONNECTED):
            return events

        sock = self.conn.sock
        if self.state == Client.CONNECTING:
            # Sous Windows, un echec de connexion est signale dans la liste
            # "exceptionnelle" de select, pas dans "writable".
            try:
                _, writable, errored = select.select([], [sock], [sock], 0)
            except (OSError, ValueError) as e:
                self._fail(events, 'erreur select : {}'.format(e))
                return events
            if sock in errored or sock in writable:
                err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err != 0 or sock in errored:
                    self._fail(events, 'connexion echouee (code {})'.format(err))
                    return events
                self.state = Client.CONNECTED
                events.append(('connected', self.conn.address))
                for message in self._pending:
                    self.conn.send(message)
                self._pending = []
            else:
                return events

        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except (OSError, ValueError) as e:
            self._fail(events, 'erreur select : {}'.format(e))
            return events
        if _pump_connection(self.conn, readable, events):
            self.state = Client.CLOSED
        return events

    def _fail(self, events, reason):
        self.close()
        events.append(('disconnected', reason))

    def close(self):
        if self.conn is not None:
            self.conn.close()
        self.state = Client.CLOSED
        self._pending = []
