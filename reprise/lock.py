# Copyright (C) 2022 Dmitry Marakasov <amdmi3@amdmi3.ru>
#
# This file is part of reprise
#
# reprise is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# reprise is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with reprise.  If not, see <http://www.gnu.org/licenses/>.

import fcntl
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    with open(path, 'w+') as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger = logging.getLogger('Locking')
            logger.debug(f'waiting on lock {path}')
            fcntl.flock(fd, fcntl.LOCK_EX)
            logger.debug(f'done waiting on lock {path}')

        yield
