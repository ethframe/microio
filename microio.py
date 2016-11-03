"""
`microio` - dumb event loop based on `select.select`
"""

from collections import deque
import heapq
import inspect
import select
import socket
import time

__all__ = ('loop', 'Return', 'SocketOp')


class Return(BaseException):

    def __init__(self, value):
        self.value = value


class SocketOp:
    READ = 0
    WRITE = 1


def loop(task):
    readers = set()
    writers = set()
    timeouts = []
    waiters = {}
    exceptions = {}
    tasks = deque()
    tasks.append((task, None))
    root = task
    root_ret = None

    while any((tasks, timeouts, readers, writers)):
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
                        op, sock = yielded
                    except ValueError:
                        raise RuntimeError(current)
                    if not isinstance(sock, socket.socket):
                        raise RuntimeError(current)
                    if op == SocketOp.READ:
                        readers.add(sock)
                    elif op == SocketOp.WRITE:
                        writers.add(sock)
                    else:
                        raise RuntimeError(current)
                    waiters[sock] = current
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

        if readers or writers:
            timeout = None
            if tasks:  # If there is active tasks, do quick check on events
                timeout = 0.0
            elif timeouts:
                # If there is pending timeout, wait for events up to it
                timeout = max(0.0, timeouts[0][0] - time.time())
            r, w, _ = select.select(readers, writers, [], timeout)
            readers.difference_update(r)
            writers.difference_update(w)
            for sock in set(r + w):  # Reschedule tasks
                waiter = waiters.pop(sock, None)
                if waiter:
                    tasks.append((waiter, None))

        if timeouts:
            timeout, _, waiter = timeouts[0]  # Handle earliest timeout
            if not (tasks or readers or writers):
                # If there is no other tasks, loop can sleep until next timeout
                time.sleep(max(0.0, timeout - time.time()))
            if time.time() >= timeout:
                heapq.heappop(timeouts)
                tasks.append((waiter, None))

    return root_ret
