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

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from reprise.commands import JAIL_CMD, JEXEC_CMD, JLS_CMD
from reprise.execute import execute
from reprise.resources import Resource

_logger = logging.getLogger('Prison')


class Prison(Resource):
    _jid: int
    _path: Path

    def __init__(self, jid: int, path: Path) -> None:
        self._jid = jid
        self._path = path

    async def execute(self, program: str, *args: Any, **kwargs: Any) -> list[str]:
        return await execute(
            JEXEC_CMD, '-l', str(self._jid),
            '/usr/bin/env', '-L0',  # XXX: may be changed to -L- when 12.x is gone
            program, *args, **kwargs
        )

    async def execute_by_line(self, program: str, *args: Any, log: TextIO | None) -> int:
        logging.getLogger('Execute').debug('executing ' + ' '.join([program] + list(args)))
        proc = await asyncio.create_subprocess_exec(
            JEXEC_CMD, '-l', str(self._jid),
            '/usr/bin/env', '-L0',  # XXX: may be changed to -L- when 12.x is gone
            program, *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )

        await proc.communicate()

        assert proc.returncode is not None
        return proc.returncode

    async def destroy(self) -> None:
        _logger.debug(f'destroying prison {self._jid}')
        await execute(JAIL_CMD, '-r', str(self._jid))
        while await self.is_running():
            logging.debug('waiting for prison {self._jid} to die')
            await asyncio.sleep(1)

    async def is_running(self) -> bool:
        proc = await asyncio.create_subprocess_exec(
            JLS_CMD, '-j', str(self._jid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )

        await proc.communicate()

        return proc.returncode == 0

    def get_path(self) -> Path:
        return self._path

    def __repr__(self) -> str:
        return f'prison {self._jid}'


NetworkingIsolationMode = Enum('NetworkingIsolationMode', 'DISABLED RESTRICTED UNRESTRICTED')


async def start_prison(path: Path, networking: NetworkingIsolationMode = NetworkingIsolationMode.DISABLED, hostname: str = '') -> Prison:
    # XXX: poudriere checks kern.features.inet and kern.features.inet6
    # to see if these are available at all, we should probably do the same
    if networking == NetworkingIsolationMode.UNRESTRICTED:
        networking_args = ('ip4=inherit', 'ip6=inherit')
    elif networking == NetworkingIsolationMode.RESTRICTED:
        networking_args = ('ip4.addr=127.0.0.1', 'ip6.addr=::1')
    else:
        networking_args = ('ip4=disable', 'ip6=disable')

    res = await execute(
        JAIL_CMD,
        '-c',
        '-i',
        'persist',
        f'path={path}',
        f'host.hostname={hostname}',
        *networking_args,
    )
    jid = int(res[0])
    _logger.debug(f'started prison {jid}')
    return Prison(jid, path)