from __future__ import print_function

from microio import *
from utils import *


def handler(stream, addr):
    print('Connection from {}'.format(addr))

    def _handler():
        try:
            while True:
                line = yield stream.read_until(b'\n')
                yield stream.write(b'Received: ' + line)
        except IOError:
            pass
        finally:
            stream.close()
            print('Connection closed')

    return _handler


def server():
    sock = listen(('127.0.0.1', 25000))
    yield serve(sock, handler)


def main():
    loop(server())


if __name__ == '__main__':
    main()
