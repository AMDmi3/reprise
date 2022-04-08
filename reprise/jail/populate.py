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
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JailSpec:
    version: str
    architecture: str


async def populate_jail(spec: JailSpec, target_path: Path) -> None:
    if spec.version not in ['12.3-RELEASE', '13.0-RELEASE']:
        raise RuntimeError('unsupported version')

    if spec.architecture not in ['amd64', 'i386']:
        raise RuntimeError('unsupported architecture')

    url_prefix = f'https://download.freebsd.org/ftp/releases/{spec.architecture}/{spec.version}/'

    for tarball in ['base.txz']:
        command = f'fetch -o- {url_prefix}/{tarball} | tar -C {target_path} -x -f- -z'

        proc = await asyncio.create_subprocess_shell(command, stderr=asyncio.subprocess.PIPE)

        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError('failed to populate jail ' + stderr.decode('utf-8'))
