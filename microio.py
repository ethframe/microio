"""
`microio` - dumb event loop based on `select.select`
"""

from collections import deque, defaultdict
import heapq
import inspect
import select
import socket
import time

__all__ = ('loop', 'Return', 'POLLREAD', 'POLLWRITE', 'POLLERROR')


class Return(BaseException):

    def __init__(self, value):
        self.value = value


if hasattr(select, 'epoll'):
    POLLREAD = select.EPOLLIN
    POLLWRITE = select.EPOLLOUT
    POLLERROR = select.EPOLLERR | select.EPOLLHUP
    Poll = select.epoll
elif hasattr(select, 'poll'):
    POLLREAD = select.POLLIN
    POLLWRITE = select.POLLOUT
    POLLERROR = select.POLLERR | select.POLLHUP
    Poll = select.poll
else:
    POLLREAD = 0x01
    POLLWRITE = 0x02
    POLLERROR = 0x04

    class Poll:

        def __init__(self):
            self.readers = set()
            self.writers = set()
            self.errors = set()

        def register(self, fd, mask):
            if mask & POLLREAD:
                self.readers.add(fd)
            if mask & POLLWRITE:
                self.writers.add(fd)
            if mask & POLLERROR:
                self.errors.add(fd)

        def modify(self, fd, mask):
            self.unregister(fd)
            self.register(fd, mask)

        def unregister(self, fd):
            self.readers.discard(fd)
            self.writers.discard(fd)
            self.errors.discard(fd)

        def poll(self, timeout=-1):
            if not any((self.readers, self.writers, self.errors)):
                time.sleep(max(0.0, timeout))
                return []
            if timeout < 0.0:
                timeout = None
            r, w, x = select.select(self.readers, self.writers,
                                    self.errors, timeout)
            events = defaultdict(lambda: 0)
            for fd in r:
                events[fd] |= POLLREAD
            for fd in w:
                events[fd] |= POLLWRITE
            for fd in x:
                events[fd] |= POLLERROR
            return list(events.items())


def loop(task):
    poll = Poll()
    sockets = {}
    timeouts = []
    waiters = {}
    exceptions = {}
    tasks = deque()
    tasks.append((task, None))
    root = task
    root_ret = None

    while any((tasks, timeouts, sockets)):
        if tasks:
            current, val = tasks.popleft()
            try:
                e = exceptions.pop(current, None)
                if e:  # There was an exception in subroutine
                    yielded = current.throw(e)
                else:
                    yielded = current.send(val)
                if inspect.isgenerator(yielded):  # Subroutine call
                    tasks.append((yielded, None))
                    waiters[yielded] = current
                elif inspect.isgeneratorfunction(yielded):  # New task
                    tasks.append((yielded(), None))
                    tasks.append((current, None))
                elif isinstance(yielded, tuple):  # Requst to wait for IO event
                    try:
                        sock, mask = yielded
                    except ValueError:
                        raise RuntimeError(current)
                    if not isinstance(sock, socket.socket):
                        raise RuntimeError(current)
                    fd = sock.fileno()
                    if mask is None:
                        old = sockets.pop(fd, None)
                        if old is not None:
                            poll.unregister(fd)
                        tasks.append((current, None))
                    else:
                        _, old = sockets.get(fd, (None, None))
                        sockets[fd] = (sock, mask)
                        if old is None:
                            poll.register(fd, mask)
                        else:
                            poll.modify(fd, mask)
                        waiters[fd] = current
                # Request to wait for timeout
                elif isinstance(yielded, (float, int)):
                    heapq.heappush(timeouts, (yielded, id(current), current))
                elif yielded is None:  # Can be used for task rescheduling
                    tasks.append((current, None))
                else:
                    raise RuntimeError(current)
            except (StopIteration, Return) as e:
                # Value can be returned using `raise Return(value)` in py2
                # or with `return value` in py3
                waiter = waiters.pop(current, None)
                if waiter:
                    tasks.append((waiter, getattr(e, 'value', None)))
                elif current == root:
                    root_ret = getattr(e, 'value', None)
            except Exception as e:  # Other exceptions are passed to callers
                waiter = waiters.pop(current, None)
                if waiter:
                    exceptions[waiter] = e
                    tasks.append((waiter, None))
                else:  # Reraise if current task is on top level
                    raise

        timeout = -1
        if tasks:  # If there is active tasks, do quick check on events
            timeout = 0.0
        elif timeouts:
            # If there is pending timeout, wait for events up to it
            timeout = max(0.0, timeouts[0][0] - time.time())
        for fd, mask in poll.poll(timeout):
            waiter = waiters.pop(fd, None)
            if waiter:
                tasks.append((waiter, mask))

        if timeouts:
            timeout, _, waiter = timeouts[0]  # Handle earliest timeout
            if time.time() >= timeout:
                heapq.heappop(timeouts)
                tasks.append((waiter, None))

    return root_ret
