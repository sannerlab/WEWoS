# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Calls between the server and an isolated network's worker process
(wewos/isolation.py, wewos/worker.py), over a socket pair.

Each message is a JSON object preceded by its length (8 bytes, big endian).
A call is {id, call, args}; its answer {id, ok} or {id, error, kind, trace}.
Either side can call the other; every incoming call is answered on its own
thread, so a long call (the page's 25 s wait for events, or a run thread
waiting for a viewer snapshot) does not hold up the others.
"""
import itertools
import json
import socket
import struct
import threading
import traceback

MAX_MESSAGE = 1 << 31          # 2 GB: a large scene, never more


class ChannelClosed(Exception):
    """The other side has gone (its process ended)."""


class RemoteError(Exception):
    """The other side raised an exception while answering a call."""

    def __init__(self, message, kind='other', trace=None):
        Exception.__init__(self, message)
        self.message, self.kind, self.trace = message, kind, trace


def error_kind(e):
    """How an error crosses the channel: refused and value errors are the
    caller's mistakes (HTTP 400), the others are failures (HTTP 500)."""
    if type(e).__name__ == 'Refused' or (isinstance(e, RemoteError) and e.kind == 'refused'):
        return 'refused'
    if isinstance(e, ValueError) or (isinstance(e, RemoteError) and e.kind == 'value'):
        return 'value'
    return 'other'


class Channel(object):

    def __init__(self, sock, handler, on_close=None):
        """handler(name, args) answers the other side's calls (a JSON-able
        result, or an exception); on_close(reason) runs once when the
        connection ends."""
        self.sock = sock
        self.handler = handler
        self.on_close = on_close
        self.closed = None
        self._wlock = threading.Lock()
        self._plock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending = {}
        self._reader = threading.Thread(target=self._read, name='ipc-reader', daemon=True)
        self._reader.start()

    # ---- sending ------------------------------------------------------------------
    def _send(self, obj):
        data = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        with self._wlock:
            self.sock.sendall(struct.pack('>Q', len(data)) + data)

    def call(self, name, args=None, timeout=None):
        if self.closed is not None:
            raise ChannelClosed(self.closed)
        slot = {'event': threading.Event()}
        with self._plock:
            i = next(self._ids)
            self._pending[i] = slot
        try:
            self._send({'id': i, 'call': name, 'args': args or {}})
        except OSError as e:
            with self._plock:
                self._pending.pop(i, None)
            raise ChannelClosed(str(e))
        if not slot['event'].wait(timeout):
            with self._plock:
                self._pending.pop(i, None)
            raise TimeoutError('no answer to %s within %s s' % (name, timeout))
        reply = slot.get('reply')
        if reply is None:
            raise ChannelClosed(self.closed or 'closed')
        if 'error' in reply:
            raise RemoteError(reply['error'], reply.get('kind') or 'other', reply.get('trace'))
        return reply.get('ok')

    # ---- receiving ----------------------------------------------------------------
    def _exactly(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            if not chunk:
                raise ChannelClosed('the other side closed the connection')
            buf += chunk
        return bytes(buf)

    def _read(self):
        reason = 'closed'
        try:
            while True:
                n = struct.unpack('>Q', self._exactly(8))[0]
                if n > MAX_MESSAGE:
                    raise ChannelClosed('a message of %d bytes is too large' % n)
                msg = json.loads(self._exactly(n).decode('utf-8'))
                if 'call' in msg:
                    threading.Thread(target=self._answer, args=(msg,), daemon=True,
                                     name='ipc-call-%s' % msg.get('call')).start()
                else:
                    with self._plock:
                        slot = self._pending.pop(msg.get('id'), None)
                    if slot is not None:
                        slot['reply'] = msg
                        slot['event'].set()
        except (ChannelClosed, OSError, ValueError, struct.error) as e:
            reason = str(e) or type(e).__name__
        finally:
            self.closed = reason
            with self._plock:
                pending, self._pending = list(self._pending.values()), {}
            for slot in pending:
                slot['event'].set()
            try:
                self.sock.close()
            except OSError:
                pass
            if self.on_close is not None:
                try:
                    self.on_close(reason)
                except Exception:
                    pass

    def _answer(self, msg):
        try:
            out = {'id': msg['id'], 'ok': self.handler(msg['call'], msg.get('args') or {})}
        except BaseException as e:                       # noqa: B902 - everything goes back
            kind = error_kind(e)
            out = {'id': msg['id'], 'error': getattr(e, 'message', None) or str(e) or type(e).__name__,
                   'kind': kind}
            if kind == 'other':
                out['error'] = '%s: %s' % (type(e).__name__, out['error'])
                out['trace'] = getattr(e, 'trace', None) or traceback.format_exc()
        try:
            self._send(out)
        except (OSError, TypeError, ValueError) as e:
            # an answer that cannot be sent (not JSON): say so instead
            try:
                self._send({'id': msg['id'], 'error': 'the answer could not be sent: %s' % e,
                            'kind': 'other'})
            except OSError:
                pass

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
