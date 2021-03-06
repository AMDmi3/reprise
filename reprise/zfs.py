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
from pathlib import Path

from reprise.commands import ZFS_CMD, ZPOOL_CMD
from reprise.execute import execute
from reprise.resources import Resource


def _properties_to_args(properties: dict[str, str] | None) -> list[str]:
    if properties is None:
        return []
    return list(sum((['-o', f'{k}={v}'] for k, v in properties.items()), []))


def _optional_args(*args: tuple[str, bool]) -> list[str]:
    return [arg for arg, enabled in args if enabled]


async def get_zfs_pools() -> list[str]:
    return await execute(ZPOOL_CMD, 'list', '-H', '-o', 'name', allow_failure=True)


class ZFS(Resource):
    _dataset: Path
    _mountpoint: Path | None

    def __init__(self, dataset: Path, mountpoint: Path | None = None) -> None:
        self._dataset = dataset
        self._mountpoint = mountpoint

    def __repr__(self) -> str:
        return f'ZFS(dataset={self._dataset}, mountpoint={self._mountpoint})'

    def get_child(self, subpath: str | Path) -> 'ZFS':
        return ZFS(self._dataset / subpath, self._mountpoint / subpath if self._mountpoint is not None else None)

    def get_path(self) -> Path:
        if self._mountpoint is None:
            raise RuntimeError('attempt to query unknown mountpoint')
        return self._mountpoint

    async def get_property(self, propname: str) -> str:
        result = await execute(ZFS_CMD, 'get', '-H', '-p', '-o', 'value', propname, f'{self._dataset}')
        return result[0]

    async def get_property_maybe(self, propname: str) -> str | None:
        result = await execute(ZFS_CMD, 'get', '-H', '-p', '-o', 'value', propname, f'{self._dataset}', allow_failure=True)
        return result[0] if result else None

    async def set_property(self, propname: str, propvalue: str) -> None:
        await execute(ZFS_CMD, 'set', propname + '=' + propvalue, f'{self._dataset}')

    async def resolve_mountpoint(self) -> None:
        mountpoint, mounted = await asyncio.gather(
            self.get_property_maybe('mountpoint'),
            self.get_property_maybe('mounted')
        )
        if mountpoint is not None and mountpoint.startswith('/') and mounted == 'yes':
            self._mountpoint = Path(mountpoint)

    async def exists(self) -> bool:
        return await self.get_property_maybe('name') is not None

    async def create(self, parents: bool = False, properties: dict[str, str] | None = None) -> None:
        await execute(ZFS_CMD, 'create', *_optional_args(('-p', parents)), *_properties_to_args(properties), f'{self._dataset}')

    async def destroy(self) -> None:
        while True:
            try:
                await execute(ZFS_CMD, 'destroy', '-R', '-f', f'{self._dataset}')
                return
            except RuntimeError as e:
                logging.error(e)
                await asyncio.sleep(1)

    async def snapshot(self, snapshot: str, recursive: bool = False) -> None:
        await execute(ZFS_CMD, 'snapshot', *_optional_args(('-r', recursive)), f'{self._dataset}@{snapshot}')

    async def rollback(self, snapshot: str) -> None:
        await execute(ZFS_CMD, 'rollback', '-R', '-f', f'{self._dataset}@{snapshot}')

    async def clone_from(self, source: 'ZFS', snapshot: str, parents: bool = False) -> None:
        await execute(ZFS_CMD, 'clone', *_optional_args(('-p', parents)), f'{source._dataset}@{snapshot}', f'{self._dataset}')

    async def destroy_snapshot(self, snapshot: str) -> None:
        await execute(ZFS_CMD, 'destroy', f'{self._dataset}@{snapshot}')

    async def get_children(self, recursive: bool = False) -> list[str]:
        lines = await execute(ZFS_CMD, 'list', '-H', '-p', '-r', '-o', 'name', f'{self._dataset}', allow_failure=True)

        return [line for line in lines if (depth := line.count('/')) >= 1 and (recursive or depth <= 1)]

    async def get_children_properties(self, recursive: bool = False, properties: list[str] | None = None) -> list[list[str]]:
        properties_arg = ','.join(['name'] + (properties if properties is not None else []))

        lines = await execute(ZFS_CMD, 'list', '-H', '-p', '-r', '-o', properties_arg, f'{self._dataset}', allow_failure=True)
        result = []

        for line in lines:
            name, *values = line.split('\t')
            depth = name.count('/')
            if depth >= 1 and (recursive or depth <= 1):
                result.append(values)

        return result
