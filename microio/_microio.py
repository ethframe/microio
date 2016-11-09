"""
`microio` - dumb event loop
"""

from collections import deque, defaultdict
import heapq
import inspect
import logging
import select
import socket
import sys
import time
import traceback

__all__ = ("loop", "Return", "POLLREAD", "POLLWRITE", "POLLERROR")


exc_logger = logging.getLogger("microio.exc")


class Return(BaseException):

    def __init__(self, value):
        self.value = value


if hasattr(select, "epoll"):
    POLLREAD = select.EPOLLIN
    POLLWRITE = select.EPOLLOUT
    POLLERROR = select.EPOLLERR | select.EPOLLHUP
    Poll = select.epoll
elif hasattr(select, "poll"):
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


def loop(task, hide_loop_tb=False, quiet_exc=False):
    poll = Poll()
    sockets = {}
    timeouts = []
    io_waiters = {}
    tasks = deque()
    tasks.append((task, [], None, None))
    root = task
    root_ret = None

    while any((tasks, timeouts, sockets)):
        if tasks:
            current, stack, val, exc = tasks.popleft()
            try:
                if exc:  # There was an exception in subroutine
                    yielded = current.throw(*exc)
                else:
                    yielded = current.send(val)
                if inspect.isgenerator(yielded):  # Subroutine call
                    stack.append(current)
                    tasks.append((yielded, stack, None, None))
                elif inspect.isgeneratorfunction(yielded):  # New task
                    tasks.append((yielded(), [], None, None))
                    tasks.append((current, stack, None, None))
                elif isinstance(yielded, tuple):  # Requst to wait for IO event
                    try:
                        sock, mask = yielded
                    except ValueError:
                        raise RuntimeError(current)
                    if not hasattr(sock, 'fileno'):
                        raise RuntimeError(current)
                    fd = sock.fileno()
                    if mask is None:
                        old = sockets.pop(fd, None)
                        if old is not None:
                            poll.unregister(fd)
                        tasks.append((current, stack, None, None))
                    else:
                        old = sockets.get(fd, None)
                        sockets[fd] = mask
                        if old is None:
                            poll.register(fd, mask)
                        else:
                            poll.modify(fd, mask)
                        io_waiters[fd] = (current, stack)
                # Request to wait for timeout
                elif isinstance(yielded, (float, int)):
                    heapq.heappush(timeouts, (yielded, id(current),
                                              current, stack))
                elif yielded is None:  # Can be used for task rescheduling
                    tasks.append((current, stack, None, None))
                else:
                    raise RuntimeError(current)
            except (StopIteration, Return) as e:
                # Value can be returned using `raise Return(value)` in py2
                # or with `return value` in py3
                if stack:
                    tasks.append((stack.pop(), stack,
                                  getattr(e, "value", None), None))
                elif current == root:
                    root_ret = getattr(e, "value", None)
            except Exception:  # Other exceptions are passed to callers
                if stack:
                    exc_type, exc_val, exc_tb = sys.exc_info()
                    if hide_loop_tb:
                        exc_tb = exc_tb.tb_next
                    tasks.append((stack.pop(), stack,
                                  None, (exc_type, exc_val, exc_tb)))
                elif not quiet_exc:  # Reraise if current task is on top level
                    raise
                else:
                    exc_logger.warn("Exception in {}:\n{}"
                                    .format(current.__name__,
                                            traceback.format_exc()))

        timeout = -1
        if tasks or not sockets:
            # If there is active tasks or no sockets, do quick check on events
            timeout = 0.0
        elif timeouts:
            # If there is pending timeout, wait for events up to it
            timeout = max(0.0, timeouts[0][0] - time.time())
        for fd, mask in poll.poll(timeout):
            waiter = io_waiters.pop(fd, None)
            if waiter:
                tasks.append((waiter[0], waiter[1], mask, None))

        if timeouts:
            timeout, _, waiter, stack = timeouts[0]  # Handle earliest timeout
            if time.time() >= timeout:
                heapq.heappop(timeouts)
                tasks.append((waiter, stack, None, None))

    return root_ret
