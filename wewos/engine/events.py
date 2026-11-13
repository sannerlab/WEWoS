# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The event stream a network sends to the page, and per-thread output capture.

Every change the page must reflect (node added, widget changed, node running,
scene updated, a line printed by a node...) is an event with a sequence
number. The page long-polls /api/events?since=N and applies what comes back;
when it has fallen further behind than the buffer holds it gets
{'reset': True} and reloads the whole network.
"""
import collections
import io
import sys
import threading
import time


class EventBus(object):
    def __init__(self, maxlen=20000):
        self.seq = 0
        self.events = collections.deque(maxlen=maxlen)
        self.cond = threading.Condition()

    def emit(self, kind, **data):
        with self.cond:
            self.seq += 1
            data['seq'] = self.seq
            data['kind'] = kind
            data['t'] = round(time.time(), 3)
            self.events.append(data)
            self.cond.notify_all()
            return self.seq

    def since(self, seq, timeout=0.0):
        """Events with a sequence number above seq; waits up to timeout
        seconds for one to arrive."""
        seq = int(seq or 0)
        deadline = time.time() + timeout
        with self.cond:
            if seq > self.seq:
                # the client has seen more than this bus ever sent: the network
                # was reopened (an isolated network restarted); start over
                return {'seq': self.seq, 'reset': True, 'events': []}
            while self.seq <= seq:
                left = deadline - time.time()
                if left <= 0:
                    break
                self.cond.wait(left)
            if self.events and seq < self.events[0]['seq'] - 1:
                return {'seq': self.seq, 'reset': True, 'events': []}
            evs = [e for e in self.events if e['seq'] > seq]
            return {'seq': self.seq, 'events': evs}


class _Sink(io.TextIOBase):
    """Collects text and forwards whole lines to a callback."""

    def __init__(self, fn):
        self.fn = fn
        self.buf = ''

    def write(self, s):
        self.buf += s
        if '\n' in self.buf:
            lines, self.buf = self.buf.rsplit('\n', 1)
            self.fn(lines + '\n')
        return len(s)

    def flush(self):
        if self.buf:
            self.fn(self.buf)
            self.buf = ''


class _ThreadRouter(io.TextIOBase):
    """Installed once as sys.stdout/sys.stderr: writes from a thread that has
    a sink go to that sink, everything else to the real stream."""

    def __init__(self, real):
        self.real = real
        self.local = threading.local()

    def write(self, s):
        sink = getattr(self.local, 'sink', None)
        if sink is not None:
            return sink.write(s)
        return self.real.write(s)

    def flush(self):
        sink = getattr(self.local, 'sink', None)
        if sink is not None:
            sink.flush()
        else:
            self.real.flush()

    def isatty(self):
        return False

    @property
    def encoding(self):
        return getattr(self.real, 'encoding', 'utf-8')


def _install():
    if not isinstance(sys.stdout, _ThreadRouter):
        sys.stdout = _ThreadRouter(sys.stdout)
    if not isinstance(sys.stderr, _ThreadRouter):
        sys.stderr = _ThreadRouter(sys.stderr)


class captured(object):
    """with captured(fn): output printed by this thread goes to fn(text)."""

    def __init__(self, fn):
        self.fn = fn

    def __enter__(self):
        _install()
        self.sink = _Sink(self.fn)
        self.prev = (getattr(sys.stdout.local, 'sink', None),
                     getattr(sys.stderr.local, 'sink', None))
        sys.stdout.local.sink = self.sink
        sys.stderr.local.sink = self.sink
        return self

    def __exit__(self, *a):
        self.sink.flush()
        sys.stdout.local.sink, sys.stderr.local.sink = self.prev
        return False
