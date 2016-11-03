from __future__ import print_function

import errno
import socket
import time
import random

from microio import *


def connect(address):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)
    ret = sock.connect_ex(address)
    if ret in (errno.EWOULDBLOCK, errno.EINPROGRESS, errno.EAGAIN):
        yield SocketOp.WRITE, sock
        ret = sock.connect_ex(address)
    if ret != errno.EISCONN:
        raise IOError()
    if ret == errno.ECONNREFUSED:
        raise IOError()
    raise Return(sock)


def server_handler(sock):
    def handler():
        while True:
            yield SocketOp.READ, sock
            data = sock.recv(1024)
            if not data:
                break
            yield SocketOp.WRITE, sock
            sock.send(data)
        sock.close()
    return handler


def server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', 25000))
    sock.setblocking(False)
    sock.listen(1)
    print('Listening')
    for _ in range(5):
        yield SocketOp.READ, sock
        csock, addr = sock.accept()
        print('Connection from {}'.format(addr))
        yield server_handler(csock)


def client():
    print('Connecting')
    sock = yield connect(('127.0.0.1', 25000))
    yield time.time() + random.random() + 0.5
    msg = b'ping' * random.randint(1, 5)
    sock.send(msg)
    recvd = b''
    while True:
        yield SocketOp.READ, sock
        data = sock.recv(1024)
        if not data:
            break
        recvd += data
        if recvd == msg:
            break
    sock.close()
    print(recvd)


def spawn_clients():
    for _ in range(5):
        yield client

def exception():
    yield
    raise ValueError()


def subtask():
    for _ in range(4):
        print('.')
        yield time.time() + 0.5


def task():
    try:
        yield exception()
    except ValueError:
        print('ValueError')
    print('Alive')
    yield subtask
    yield server
    yield time.time() + 0.5
    yield spawn_clients
    yield time.time() + 2.0
    print('Alive')
    raise Return(True)


def main():
    print(loop(task()))


if __name__ == '__main__':
    main()
