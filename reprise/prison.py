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

import asyncio
import logging
import os
import pwd
import time
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from reprise.commands import JAIL_CMD, JEXEC_CMD, JLS_CMD
from reprise.execute import execute, register_execute_time
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
            '/usr/bin/env',
            # XXX: may be changed to -L- when 12.x is gone
            '-L0',
            program, *args, **kwargs
        )

    async def execute_by_line(self, program: str, *args: Any, log: TextIO | None, user: str | None = None) -> int:
        user_args = ('-u', user) if user is not None else ()

        full_args = [
            # jexec
            JEXEC_CMD,
            *user_args,
            str(self._jid),

            # env
            '/usr/bin/env',
            # the following argument clears all environment, leaving only stuff provided by the login class
            # so we need to explicitly define common vars like HOME below;
            '-i',
            # XXX: should be changed to -L- when 12.x is gone
            '-L', str(pwd.getpwnam(user).pw_uid if user is not None else 0),
            'HOME=/nonexistent',
            'SHELL=/bin/sh',
            *((f'TERM={term}',) if (term := os.environ.get('term')) else ()),
            f'USER={user if user else "root"}',

            # program
            program, *args,
        ]

        logging.getLogger('Execute').debug('executing ' + ' '.join(full_args))

        start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )

        await proc.communicate()

        register_execute_time(time.monotonic() - start)

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


NetworkingMode = Enum('NetworkingMode', 'DISABLED RESTRICTED UNRESTRICTED')


async def start_prison(path: Path, networking: NetworkingMode = NetworkingMode.DISABLED, hostname: str = '') -> Prison:
    # XXX: poudriere checks kern.features.inet and kern.features.inet6
    # to see if these are available at all, we should probably do the same
    if networking == NetworkingMode.UNRESTRICTED:
        networking_args = ('ip4=inherit', 'ip6=inherit')
    elif networking == NetworkingMode.RESTRICTED:
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
