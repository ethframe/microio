from __future__ import print_function

import socket

from microio import *
from utils import *


def handler(csock):
    try:
        while True:
            yield csock, POLLREAD
            data = csock.recv(65536)
            if not data:
                raise IOError('Connection closed')
            while data:
                yield csock, POLLWRITE
                sent = csock.send(data)
                if not sent:
                    raise IOError('Connection closed')
                data = data[sent:]
    except IOError:
        yield csock, None


def server(address):
    sock = listen(address)
    try:
        while True:
            err = yield sock, POLLREAD | POLLERROR
            if err & POLLERROR:
                raise IOError()
            csock, addr = sock.accept()
            yield spawn(handler(csock))
    except IOError:
        yield sock, None


def main():
    try:
        loop(server(('127.0.0.1', 25000)))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
