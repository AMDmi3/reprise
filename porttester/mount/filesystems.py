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

from pathlib import Path

from porttester.execute import execute
from porttester.mount import Mountpoint

_MOUNT_CMD = 'mount'


async def mount_nullfs(source: Path, destination: Path, readonly: bool = True) -> Mountpoint:
    readonly_arg = ['-o', 'ro'] if readonly else []
    await execute(_MOUNT_CMD, '-t', 'nullfs', *readonly_arg, str(source), str(destination))
    return Mountpoint(destination)


async def mount_devfs(destination: Path) -> Mountpoint:
    await execute(_MOUNT_CMD, '-t', 'devfs', 'dev', str(destination))
    return Mountpoint(destination)


async def mount_tmpfs(destination: Path) -> Mountpoint:
    await execute(_MOUNT_CMD, '-t', 'tmpfs', 'tmp', str(destination))
    return Mountpoint(destination)
