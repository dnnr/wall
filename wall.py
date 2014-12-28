#!/usr/bin/env python2

# Wall

# Python forward compatibility
from __future__ import (division, absolute_import, print_function,
    unicode_literals)

import sys
import wall
from wall import WallApp

if __name__ == '__main__':
    # TODO: use option instead
    config_path = sys.argv[1] if len(sys.argv) >= 2 else None
    print('Wall #{}'.format(wall.release))
    WallApp(config_path=config_path).run()
