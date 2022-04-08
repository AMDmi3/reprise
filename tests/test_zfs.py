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
import os
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest

from reprise.zfs import ZFS

_ENVNAME = 'REPRISE_TEST_ZFS_POOL'


def _write(path: Path, data: str) -> None:
    with open(path, 'w') as fd:
        fd.write(data)


def _read(path: Path) -> str:
    with open(path, 'r') as fd:
        return fd.read()


# we have to redefine event_loop fixture with the module scope
@pytest.fixture(scope='module')
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope='module')
def zfs_pool() -> Path:
    pool = os.environ.get(_ENVNAME)
    if pool is None:
        pytest.skip('no test ZFS pool defined with REPRISE_TEST_ZFS_POOL environment variable')
    else:
        return Path(pool)


@pytest.fixture(scope='module')
async def zfs(zfs_pool) -> AsyncGenerator[Any, ZFS]:
    # provide a dedicated dataset at the root of the pool
    # for this module and clean it up after use
    zfs = ZFS(zfs_pool).get_child('reprise_test')

    if await zfs.exists():
        await zfs.destroy()

    await zfs.create()
    assert await zfs.exists()

    await zfs.resolve_mountpoint()

    yield zfs

    await zfs.destroy()
    assert not await zfs.exists()


async def test_create_destroy(zfs):
    zfs = zfs.get_child('create_destroy')

    assert not await zfs.exists()
    await zfs.create()
    assert await zfs.exists()
    await zfs.destroy()
    assert not await zfs.exists()


async def test_snapshot(zfs):
    zfs = zfs.get_child('snapshot')

    await zfs.create()

    path = zfs.get_path() / 'data'

    _write(path, 'before_snapshot')

    await zfs.snapshot('my_snapshot')

    assert _read(path) == 'before_snapshot'

    _write(path, 'after_snapshot')

    assert _read(path) == 'after_snapshot'

    await zfs.rollback('my_snapshot')

    assert _read(path) == 'before_snapshot'

    await zfs.destroy_snapshot('my_snapshot')
