"""
`microio` - dumb event loop


>>> def foo():
...     yield
...     raise Return(1)

>>> loop(foo())
1


>>> def bar():
...     foo_val = yield foo()
...     raise Return(foo_val + 1)

>>> loop(bar())
2


>>> def delayed_print():
...     yield time.time() + 0.1  # Delay for 0.1 second
...     print("delayed_print")

>>> def main_task():
...     print("entering")
...     yield delayed_print
...     print("exiting")
...     raise Return(True)

>>> loop(main_task())
entering
exiting
delayed_print
True


>>> def main_task():
...     t1 = time.time()
...     yield time.time() + 0.5
...     t2 = time.time() - t1
...     raise Return(t2 >= 0.5)

>>> loop(main_task())
True



>>> def oneshot_server(sock):
...     def _server_task():
...         yield sock, POLLREAD
...         csock, addr = sock.accept()
...         print("Connection")
...         yield sock, None
...         sock.close()
...         yield csock, POLLREAD
...         data = csock.recv(1024)
...         print("Request: {}".format(data.decode("ascii")))
...         yield csock, POLLWRITE
...         csock.send(data)
...         yield csock, None
...         csock.close()
...
...     return _server_task

>>> def client(address):
...     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
...     sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
...     sock.setblocking(False)
...     sock.connect_ex(address)
...     yield sock, POLLWRITE | POLLERROR
...     sock.connect_ex(address)
...     yield sock, POLLWRITE | POLLERROR
...     sock.send(b"ping")
...     yield sock, POLLREAD
...     data = sock.recv(1024)
...     yield sock, None
...     print("Reply: {}".format(data.decode("ascii")))
...     sock.close()

>>> def main_task():
...     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
...     sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
...     sock.bind(('127.0.0.1', 0))
...     sock.setblocking(False)
...     sock.listen(1)
...     yield oneshot_server(sock)
...     yield client(sock.getsockname()[:2])

>>> loop(main_task())
Connection
Request: ping
Reply: ping


>>> def failing():
...     yield "unknown"

>>> loop(failing())  # doctest: +ELLIPSIS
Traceback (most recent call last):
...
RuntimeError: ...


>>> def failing():
...     yield (None,)

>>> loop(failing())  # doctest: +ELLIPSIS
Traceback (most recent call last):
...
RuntimeError: ...


>>> def failing():
...     yield None, POLLREAD

>>> loop(failing())  # doctest: +ELLIPSIS
Traceback (most recent call last):
...
RuntimeError: ...


>>> class Error(Exception):
...     pass

>>> def failing():
...     yield
...     raise Error()

>>> loop(failing())
Traceback (most recent call last):
...
Error

>>> def main_task():
...     try:
...         yield failing()
...     except Error:
...         print("Error in failing()")

>>> loop(main_task())
Error in failing()

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


exc_logger = logging.getLogger(__name__)
exc_logger.setLevel(logging.WARN)
ch = logging.StreamHandler()
ch.setLevel(logging.WARN)
formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
ch.setFormatter(formatter)
exc_logger.addHandler(ch)


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
    waiters = {}
    io_waiters = {}
    tasks = deque()
    tasks.append((task, None, None))
    root = task
    root_ret = None

    while any((tasks, timeouts, sockets)):
        if tasks:
            current, val, exc = tasks.popleft()
            try:
                if exc:  # There was an exception in subroutine
                    yielded = current.throw(*exc)
                else:
                    yielded = current.send(val)
                if inspect.isgenerator(yielded):  # Subroutine call
                    tasks.append((yielded, None, None))
                    waiters[yielded] = current
                elif inspect.isgeneratorfunction(yielded):  # New task
                    tasks.append((yielded(), None, None))
                    tasks.append((current, None, None))
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
                        tasks.append((current, None, None))
                    else:
                        _, old = sockets.get(fd, (None, None))
                        sockets[fd] = (sock, mask)
                        if old is None:
                            poll.register(fd, mask)
                        else:
                            poll.modify(fd, mask)
                        io_waiters[fd] = current
                # Request to wait for timeout
                elif isinstance(yielded, (float, int)):
                    heapq.heappush(timeouts, (yielded, id(current), current))
                elif yielded is None:  # Can be used for task rescheduling
                    tasks.append((current, None, None))
                else:
                    raise RuntimeError(current)
            except (StopIteration, Return) as e:
                # Value can be returned using `raise Return(value)` in py2
                # or with `return value` in py3
                waiter = waiters.pop(current, None)
                if waiter:
                    tasks.append((waiter, getattr(e, "value", None), None))
                elif current == root:
                    root_ret = getattr(e, "value", None)
            except Exception:  # Other exceptions are passed to callers
                waiter = waiters.pop(current, None)
                if waiter:
                    exc_type, exc_val, exc_tb = sys.exc_info()
                    if hide_loop_tb:
                        exc_tb = exc_tb.tb_next
                    tasks.append((waiter, None, (exc_type, exc_val, exc_tb)))
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
                tasks.append((waiter, mask, None))

        if timeouts:
            timeout, _, waiter = timeouts[0]  # Handle earliest timeout
            if time.time() >= timeout:
                heapq.heappop(timeouts)
                tasks.append((waiter, None, None))

    return root_ret


if __name__ == "__main__":
    import doctest
    doctest.testmod()
