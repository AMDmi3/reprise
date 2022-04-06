# Copyright (C) 2022 Dmitry Marakasov <amdmi3@amdmi3.ru>
#
# This file is part of portester
#
# portester is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# portester is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with portester.  If not, see <http://www.gnu.org/licenses/>.

import logging
from abc import ABC, abstractmethod

from porttester.jail import Jail
from porttester.types import Port


class Task(ABC):
    _logger = logging.getLogger('Task')

    @abstractmethod
    async def fetch(self, jail: Jail) -> None:
        pass

    @abstractmethod
    async def install(self, jail: Jail) -> None:
        pass

    @abstractmethod
    async def test(self, jail: Jail) -> None:
        pass


class PackageTask(Task):
    _pkgname: str

    def __init__(self, pkgname: str) -> None:
        self._pkgname = pkgname

    def __repr__(self) -> str:
        return f'PackageTask({self._pkgname})'

    async def fetch(self, jail: Jail) -> None:
        self._logger.debug(f'started fetching for {self._pkgname}')
        await jail.execute('env', 'PKG_CACHEDIR=/packages', 'pkg', 'fetch', '-U', '-q', '-y', self._pkgname)
        self._logger.debug(f'finished fetching for {self._pkgname}')

    async def install(self, jail: Jail) -> None:
        self._logger.debug(f'started installation for {self._pkgname}')
        await jail.execute('env', 'PKG_CACHEDIR=/packages', 'pkg', 'install', '-U', '-q', '-y', self._pkgname)
        self._logger.debug(f'finished installation for {self._pkgname}')

    async def test(self, jail: Jail) -> None:
        pass


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

    async def fetch(self, jail: Jail) -> None:
        self._logger.debug(f'started fetching distfiles for port {self._port.origin}')

        await jail.execute(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'checksum'
        )

        self._logger.debug(f'finished fetching distfiles for port {self._port.origin}')

    async def install(self, jail: Jail) -> None:
        self._logger.debug(f'started building for port {self._port.origin}')

        returncode = await jail.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'install'  # XXX: clean if not do_test?
        )

        if returncode != 0:
            self._logger.debug(f'failed building for port {self._port.origin}')
            raise RuntimeError('build failed')

        self._logger.debug(f'finished building for port {self._port.origin}')

    async def test(self, jail: Jail) -> None:
        if not self._do_test:
            return

        self._logger.debug(f'started testing for port {self._port.origin}')

        returncode = await jail.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'test',
        )

        if returncode != 0:
            self._logger.debug(f'failed testing for port {self._port.origin}')
            raise RuntimeError('testing failed')

        self._logger.debug(f'finished testing for port {self._port.origin}')
