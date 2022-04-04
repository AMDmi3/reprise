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


@staticmethod
async def execute(program: str, *args: list[str], allow_failure: bool = False) -> list[str]:
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
            raise RuntimeError(stderr.decode('utf-8'))

    return stdout.decode('utf-8').split('\n')[:-1]
