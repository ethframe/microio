"""
>>> from ._microio import *
>>> import time, socket


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

import doctest

doctest.testmod()
