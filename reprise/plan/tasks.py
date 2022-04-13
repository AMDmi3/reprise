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

import logging
from abc import ABC, abstractmethod
from typing import TextIO

from reprise.jail import Jail
from reprise.types import Port


class Task(ABC):
    _logger = logging.getLogger('Task')

    @abstractmethod
    async def fetch(self, jail: Jail, log: TextIO) -> bool:
        pass

    @abstractmethod
    async def install(self, jail: Jail, log: TextIO) -> bool:
        pass

    @abstractmethod
    async def test(self, jail: Jail, log: TextIO) -> bool:
        pass


class PackageTask(Task):
    _pkgname: str

    def __init__(self, pkgname: str) -> None:
        self._pkgname = pkgname

    def __repr__(self) -> str:
        return f'PackageTask({self._pkgname})'

    async def fetch(self, jail: Jail, log: TextIO) -> bool:
        self._logger.debug(f'started fetching for package {self._pkgname}')
        returncode = await jail.execute_by_line('env', 'PKG_CACHEDIR=/packages', 'pkg', 'fetch', '-U', '-q', '-y', self._pkgname, log=log)
        self._logger.debug(f'finished fetching for package {self._pkgname} with code {returncode}')
        return returncode == 0

    async def install(self, jail: Jail, log: TextIO) -> bool:
        self._logger.debug(f'started installation for package {self._pkgname}')
        returncode = await jail.execute_by_line('env', 'PKG_CACHEDIR=/packages', 'pkg', 'install', '-U', '-q', '-y', self._pkgname, log=log)
        self._logger.debug(f'finished installation for package {self._pkgname} with code {returncode}')
        return returncode == 0

    async def test(self, jail: Jail, log: TextIO) -> bool:
        return True


class PortTask(Task):
    _port: Port
    _do_test: bool

    def __init__(self, port: Port, do_test: bool = False) -> None:
        self._port = port
        self._do_test = do_test

    def __repr__(self) -> str:
        return f'PortTask({self._port}, test={self._do_test})'

    def _flavorenv(self) -> tuple[str] | tuple[()]:
        return ('FLAVOR=' + self._port.flavor,) if self._port.flavor is not None else ()

    async def fetch(self, jail: Jail, log: TextIO) -> bool:
        self._logger.debug(f'started fetching distfiles for port {self._port}')

        returncode = await jail.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            'NO_IGNORE=1',
            '_LICENSE_STATUS=accepted',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'checksum',
            log=log,
        )

        self._logger.debug(f'finished fetching distfiles for port {self._port} with code {returncode}')

        return returncode == 0

    async def install(self, jail: Jail, log: TextIO) -> bool:
        self._logger.debug(f'started installation for port {self._port}')

        returncode = await jail.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            '_LICENSE_STATUS=accepted',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'install',  # XXX: clean if not do_test?
            log=log,
        )

        self._logger.debug(f'finished installation for port {self._port} with code {returncode}')

        return returncode == 0

    async def test(self, jail: Jail, log: TextIO) -> bool:
        if not self._do_test:
            return True

        self._logger.debug(f'started testing for port {self._port}')

        returncode = await jail.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            '_LICENSE_STATUS=accepted',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'test',
            log=log,
        )

        self._logger.debug(f'finished testing for port {self._port} with code {returncode}')

        return returncode == 0
