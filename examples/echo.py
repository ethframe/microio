from __future__ import print_function

from microio import *
from utils import *


def handler(stream, addr):
    try:
        while True:
            data = yield stream.read_bytes(1024, partial=True)
            yield stream.write(data)
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
