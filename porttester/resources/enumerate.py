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
import json
from pathlib import Path

from porttester.commands import JLS_CMD, MOUNT_CMD
from porttester.execute import execute
from porttester.jail import Jail
from porttester.mount import Mountpoint
from porttester.resources import Resource
from porttester.zfs import ZFS


async def enumerate_mountpoints(prefix: Path) -> list[Resource]:
    res: list[Resource] = []

    for line in await execute(MOUNT_CMD, '-p'):
        src, dst, fstype, *_ = line.strip().split()

        if fstype == 'zfs':
            dataset = Path(src)
            mountpoint = Path(dst)
            if mountpoint.is_relative_to(prefix):
                res.append(ZFS(dataset, mountpoint))
        else:
            mountpoint = Path(dst)
            if mountpoint.is_relative_to(prefix):
                res.append(Mountpoint(mountpoint))

    return sorted(res, key=lambda res: res.get_path(), reverse=True)


async def enumerate_jails(prefix: Path) -> list[Resource]:
    jails_info = json.loads((await execute(JLS_CMD, '-n', '--libxo', 'json'))[0])

    res = []

    for jail_info in jails_info['jail-information']['jail']:
        jid = int(jail_info['jid'])
        path = Path(jail_info['path'])

        if path.is_relative_to(prefix):
            res.append(Jail(jid, path))

    return sorted(res, key=lambda res: res.get_path(), reverse=True)


async def enumerate_resources(prefix: Path) -> list[Resource]:
    mountpoints, jails = await asyncio.gather(
        enumerate_mountpoints(prefix),
        enumerate_jails(prefix),
    )

    return jails + mountpoints
