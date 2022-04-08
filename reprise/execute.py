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

_logger = logging.getLogger('Execute')


async def execute(program: str, *args: str, allow_failure: bool = False) -> list[str]:
    _logger.debug('executing ' + ' '.join([program] + list(args)))
    proc = await asyncio.create_subprocess_exec(
        program, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL if allow_failure else asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        if allow_failure:
            return []
        else:
            raise RuntimeError(stdout.decode('utf-8') + stderr.decode('utf-8'))

    return stdout.decode('utf-8').split('\n')[:-1]
