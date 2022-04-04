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
    res = []

    for line in await execute(MOUNT_CMD,  '-p'):
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
