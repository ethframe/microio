from __future__ import print_function

from microio import *
from utils import *


def handler(stream, addr):
    try:
        while True:
            line = yield stream.read_until(b'\n')
            yield stream.write(line)
    except IOError:
        pass
    finally:
        stream.close()


def server(address):
    sock = listen(address)
    yield serve(sock, handler)


def main():
    try:
        loop(server(('127.0.0.1', 25000)))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
