from porttester.execute import execute
from porttester.mount import Mountpoint
from pathlib import Path


_MOUNT_CMD = 'mount'


async def mount_nullfs(source: Path, destination: Path, readonly: bool = True) -> Mountpoint:
    readonly_arg = ['-o', 'ro'] if readonly else []
    await execute(_MOUNT_CMD, '-t', 'nullfs', *readonly_arg, source, destination)
    return Mountpoint(destination)


async def mount_devfs(destination: Path) -> Mountpoint:
    await execute(_MOUNT_CMD, '-t', 'devfs', 'dev', destination)
    return Mountpoint(destination)


async def mount_tmpfs(destination: Path) -> Mountpoint:
    await execute(_MOUNT_CMD, '-t', 'tmpfs', 'tmp', destination)
    return Mountpoint(destination)
