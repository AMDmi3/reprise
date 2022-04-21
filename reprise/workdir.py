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

import logging
from pathlib import Path

from reprise.zfs import ZFS, get_zfs_pools

_REPRISE_HOME = 'reprise'


class AutocreateFailure(RuntimeError):
    pass


class Workdir:
    root: ZFS

    @staticmethod
    async def initialize(dataset: Path | None = None) -> 'Workdir':
        logger = logging.getLogger('Workdir')

        if dataset is None:
            pools = await get_zfs_pools()

            if not pools:
                raise AutocreateFailure('no ZFS pools detected')
            elif len(pools) > 1:
                raise AutocreateFailure('multiple ZFS pools detected, please specify manually')

            dataset = Path(pools[0]) / _REPRISE_HOME

        logger.debug(f'using root dataset {dataset}')

        root = ZFS(dataset)

        if not await root.exists():
            try:
                logger.debug('creating root dataset')
                await root.create()
            except RuntimeError as e:
                raise AutocreateFailure('cannot create root dataset') from e

        try:
            await root.resolve_mountpoint()
        except RuntimeError as e:
            raise AutocreateFailure('cannot get root dataset mountpoint') from e

        workdir = Workdir(root)

        required_filesystems = [
            workdir.get_logs(),
            workdir.get_packages(),
            workdir.get_ccache(),
        ]

        for filesystem in required_filesystems:
            if not await filesystem.exists():
                logger.debug(f'creating missing child dataset {filesystem}')
                await filesystem.create()

        return workdir

    def __init__(self, root: ZFS) -> None:
        self.root = root

    def get_jail_master(self, name: str) -> ZFS:
        return self.root.get_child(Path('jails') / name)

    def get_jail_instance(self, name: str) -> ZFS:
        return self.root.get_child(Path('instances') / name)

    def get_packages(self) -> ZFS:
        return self.root.get_child(Path('packages'))

    def get_ccache(self) -> ZFS:
        return self.root.get_child(Path('ccache'))

    def get_logs(self) -> ZFS:
        return self.root.get_child(Path('logs'))
