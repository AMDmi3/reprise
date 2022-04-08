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
        if dataset is None:
            pools = await get_zfs_pools()

            if not pools:
                raise AutocreateFailure('no ZFS pools detected')
            elif len(pools) > 1:
                raise AutocreateFailure('multiple ZFS pools detected, please specify manually')

            dataset = Path(pools[0]) / _REPRISE_HOME

        root = ZFS(dataset)

        if not await root.exists():
            try:
                logging.debug(f'creating main dataset at {dataset}')
                await root.create()
            except RuntimeError as e:
                raise AutocreateFailure('cannot create root dataset') from e

        try:
            await root.resolve_mountpoint()
        except RuntimeError as e:
            raise AutocreateFailure('cannot get root dataset mountpoint') from e

        return Workdir(root)

    def __init__(self, root: ZFS) -> None:
        self.root = root

    def get_jail_master(self, name: str) -> ZFS:
        return self.root.get_child(Path('jails') / name)

    def get_jail_instance(self, name: str) -> ZFS:
        return self.root.get_child(Path('instances') / name)

    def get_jail_packages(self, name: str) -> ZFS:
        return self.root.get_child(Path('packages') / name)
