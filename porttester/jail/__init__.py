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

import asyncio
import logging
from pathlib import Path
from typing import Any

from porttester.commands import JAIL_CMD, JEXEC_CMD, JLS_CMD
from porttester.execute import execute
from porttester.resources import Resource

_logger = logging.getLogger('Jail')


class Jail(Resource):
    _jid: int
    _path: Path

    def __init__(self, jid: int, path: Path) -> None:
        self._jid = jid
        self._path = path

    async def execute(self, program: str, *args: Any, **kwargs: Any) -> list[str]:
        return await execute(JEXEC_CMD, '-l', str(self._jid), program, *args, **kwargs)

    async def execute_by_line(self, program: str, *args: Any, **kwargs: Any) -> int:
        proc = await asyncio.create_subprocess_exec(
            JEXEC_CMD, '-l', str(self._jid),
            program, *args, **kwargs,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=None,
            stderr=None,
        )

        await proc.communicate()

        assert proc.returncode is not None
        return proc.returncode

    async def destroy(self) -> None:
        _logger.debug(f'destroying jail {self._jid}')
        await execute(JAIL_CMD, '-r', str(self._jid))
        while await self.is_running():
            logging.debug('waiting for jail to die')
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
        return f'jail {self._jid}'


async def start_jail(path: Path, networking: bool = False, hostname: str = '') -> Jail:
    networking_arg = 'inherit' if networking else 'disable'

    res = await execute(
        JAIL_CMD,
        '-c',
        '-i',
        'persist',
        f'path={path}',
        f'ip4={networking_arg}',
        f'ip6={networking_arg}',
        f'host.hostname={hostname}'
    )
    jid = int(res[0])
    _logger.debug(f'started jail {jid}')
    return Jail(jid, path)
