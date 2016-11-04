from __future__ import print_function


import sys
import traceback

from microio import *


def leaf():
    yield
    raise ValueError()


def intermediate(n=5):
    if n == 0:
        yield leaf()
    else:
        yield intermediate(n - 1)


def toplevel():
    yield intermediate()


if __name__ == '__main__':
    loop(toplevel(), True, True)
