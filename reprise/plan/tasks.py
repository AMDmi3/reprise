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

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TextIO

from reprise.prison import Prison
from reprise.repository import PackageInfo, Repository
from reprise.types import Port


class Task(ABC):
    _logger = logging.getLogger('Task')

    @abstractmethod
    async def fetch(self, prison: Prison, log: TextIO) -> bool:
        pass

    @abstractmethod
    async def install(self, prison: Prison, log: TextIO) -> bool:
        pass

    @abstractmethod
    async def test(self, prison: Prison, log: TextIO) -> bool:
        pass


class PackageTask(Task):
    _repository: Repository
    _package_info: PackageInfo

    def __init__(self, repository: Repository, package_info: PackageInfo) -> None:
        self._repository = repository
        self._package_info = package_info

    def __repr__(self) -> str:
        return f'PackageTask({self._package_info.name})'

    async def fetch(self, prison: Prison, log: TextIO) -> bool:
        self._logger.debug(f'started fetching for package {self._package_info.name}')
        await self._repository.get_package(self._package_info)
        self._logger.debug(f'finished fetching for package {self._package_info.name}')
        return True

    async def install(self, prison: Prison, log: TextIO) -> bool:
        self._logger.debug(f'started installation for package {self._package_info.name}')
        returncode = await prison.execute_by_line('pkg', 'add', '-q', f'/packages/{self._package_info.filename}', log=log)
        self._logger.debug(f'finished installation for package {self._package_info.name} with code {returncode}')
        return returncode == 0

    async def test(self, prison: Prison, log: TextIO) -> bool:
        return True


class PortTask(Task):
    _port: Port
    _do_test: bool
    _build_as_nobody: bool

    def __init__(self, port: Port, do_test: bool, build_as_nobody: bool) -> None:
        self._port = port
        self._do_test = do_test
        self._build_as_nobody = build_as_nobody

    def __repr__(self) -> str:
        return f'PortTask({self._port}, test={self._do_test})'

    def _flavorenv(self) -> tuple[str] | tuple[()]:
        return ('FLAVOR=' + self._port.flavor,) if self._port.flavor is not None else ()

    async def fetch(self, prison: Prison, log: TextIO) -> bool:
        self._logger.debug(f'started fetching distfiles for port {self._port}')

        print('================================================================================', file=log)
        print('= Fetch phase ==================================================================', file=log)
        print('================================================================================', file=log, flush=True)

        returncode = await prison.execute_by_line(
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

    async def install(self, prison: Prison, log: TextIO) -> bool:
        self._logger.debug(f'started installation for port {self._port}')

        print('================================================================================', file=log)
        print('= Listing installed packages before build ======================================', file=log)
        print('================================================================================', file=log, flush=True)
        await prison.execute_by_line('pkg', 'info', '-q', log=log)

        print('================================================================================', file=log)
        print('= Build package phase ==========================================================', file=log)
        print('================================================================================', file=log, flush=True)
        returncode = await prison.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            'PKG_ADD=false',
            'USE_PACKAGE_DEPENDS_ONLY=1',
            '_LICENSE_STATUS=accepted',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'package',
            log=log,
            user='nobody' if self._build_as_nobody else None,
        )

        self._logger.debug(f'finished packaging for port {self._port} with code {returncode}')

        if returncode != 0:
            return False

        print('================================================================================', file=log)
        print('= Install package phase ========================================================', file=log)
        print('================================================================================', file=log, flush=True)

        returncode = await prison.execute_by_line(
            'env',
            'BATCH=1',
            'DISTDIR=/distfiles',
            'WRKDIRPREFIX=/work',
            # XXX: PKG_ADD is specifically allowed here for install-package to work
            # in fact, we should call it explicitly on WRKDIR_PKGFILE
            'USE_PACKAGE_DEPENDS_ONLY=1',
            '_LICENSE_STATUS=accepted',
            *self._flavorenv(),
            'make', '-C', f'/usr/ports/{self._port.origin}', 'install-package',
            log=log,
        )

        self._logger.debug(f'finished installation for port {self._port} with code {returncode}')

        return returncode == 0

    async def test(self, prison: Prison, log: TextIO) -> bool:
        if not self._do_test:
            return True

        self._logger.debug(f'started testing for port {self._port}')

        print('================================================================================', file=log)
        print('= Testing phase ================================================================', file=log)
        print('================================================================================', file=log, flush=True)

        returncode = await prison.execute_by_line(
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
            user='nobody' if self._build_as_nobody else None,
        )

        self._logger.debug(f'finished testing for port {self._port} with code {returncode}')

        return returncode == 0
