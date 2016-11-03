import errno
import socket
import time

from microio import *


__all__ = ('Stream', 'connect', 'listen', 'serve')


class Stream:

    def __init__(self, sock, read_size=65536):
        sock.setblocking(False)
        self.sock = sock
        self.buffer = b''
        self.read_size = read_size

    def close(self):
        self.sock.close()

    def read_bytes(self, n):
        while len(self.buffer) < n:
            yield SocketOp.READ, self.sock
            data = self.sock.recv(self.read_size)
            if not data:
                raise IOError('Connection closed')
            self.buffer += data
        buffer = self.buffer[:n]
        self.buffer = self.buffer[n:]
        raise Return(buffer)

    def read_until(self, pat, n=65536):
        while pat not in self.buffer and len(self.buffer) < n:
            yield SocketOp.READ, self.sock
            data = self.sock.recv(self.read_size)
            if not data:
                raise IOError('Connection closed')
            self.buffer += data
        if pat not in self.buffer:
            raise IOError('Buffer limit exceeded')
        n = self.buffer.find(pat) + len(pat)
        buffer = self.buffer[:n]
        self.buffer = self.buffer[n:]
        raise Return(buffer)

    def write(self, data):
        while data:
            yield SocketOp.WRITE, self.sock
            sent = self.sock.send(data)
            if not sent:
                raise IOError('Connection closed')
            data = data[sent:]


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


def listen(address):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    sock.setblocking(False)
    sock.listen(128)
    return sock


def serve(sock, handler):
    while True:
        yield SocketOp.READ, sock
        csock, addr = sock.accept()
        stream = Stream(csock)
        yield handler(stream, addr)
