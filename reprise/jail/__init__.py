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
import logging
import platform
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from reprise.lock import file_lock
from reprise.workdir import Workdir
from reprise.zfs import ZFS


@dataclass(unsafe_hash=True)
class JailSpec:
    name: str
    version: str
    architecture: str


class JailManager:
    _logger = logging.getLogger('JailMgr')
    _instance = None

    _jails: list[JailSpec]
    _sets: dict[str, list[JailSpec]]

    def __new__(cls) -> 'JailManager':
        if cls._instance is None:
            cls._instance = super(JailManager, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        self._jails = []
        self._sets = defaultdict(list)

        # in order preferred for default
        versions = ['13.0-RELEASE', '12.3-RELEASE']

        archs = []

        if platform.machine() != 'i386':
            archs.append('amd64')

        archs.append('i386')

        for version in versions:
            for arch in archs:
                branch = version.split('.')[0]
                name = f'{branch}-{arch}'

                spec = JailSpec(name, version, arch)

                self._jails.append(spec)
                self._logger.debug(f'registered jail spec {spec}')

                self._sets[branch].append(spec)
                self._sets[arch].append(spec)
                self._sets['all'].append(spec)
                self._sets[name] = [spec]

                if not self._sets['default']:
                    self._sets['default'] = [spec]

    def get_specs(self, names: Iterable[str]) -> list[JailSpec]:
        res = []
        seen = set()

        for name in names:
            for spec in self._sets.get(name, []):
                if spec not in seen:
                    seen.add(spec)
                    res.append(spec)

        return res


async def _check_jail_compilance(jail_zfs: ZFS, spec: JailSpec) -> bool:
    if await jail_zfs.get_property_maybe('reprise:jail_ready') != 'yes':
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_version') != spec.version:
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_arch') != spec.architecture:
        return False

    return True


@dataclass
class PreparedJail:
    jail_zfs: ZFS
    packages_zfs: ZFS


async def get_prepared_jail(workdir: Workdir, spec: JailSpec) -> PreparedJail:
    logger = logging.getLogger('Jail')

    jail_zfs = workdir.get_jail_master(spec.name)
    jail_path = jail_zfs.get_path()

    packages_zfs = workdir.get_jail_packages(spec.name)

    with file_lock(jail_path.with_suffix('.lock')):
        if not await packages_zfs.exists():
            await packages_zfs.create(parents=True)

        do_recreate = False

        if not await jail_zfs.exists():
            do_recreate = True
        elif not await _check_jail_compilance(jail_zfs, spec):
            logger.info(f'jail {spec.name} is incomplete or outdated, destroying to recreate')
            await jail_zfs.destroy()
            do_recreate = True

        if do_recreate:
            logger.debug(f'creating jail {spec.name}')
            await jail_zfs.create(parents=True)

            logger.debug(f'populating jail {spec.name}')

            url_prefix = f'https://download.freebsd.org/ftp/releases/{spec.architecture}/{spec.version}/'
            for tarball in ['base.txz']:
                command = f'fetch -o- {url_prefix}/{tarball} | tar -C {jail_path} -x -f- -z'

                proc = await asyncio.create_subprocess_shell(command, stderr=asyncio.subprocess.PIPE)

                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    await jail_zfs.destroy()
                    raise RuntimeError('failed to populate jail ' + stderr.decode('utf-8'))

            await jail_zfs.snapshot('clean')

            await jail_zfs.set_property('reprise:jail_version', spec.version)
            await jail_zfs.set_property('reprise:jail_arch', spec.architecture)
            await jail_zfs.set_property('reprise:jail_ready', 'yes')

            logger.debug(f'successfully created jail {spec.name}')

    return PreparedJail(jail_zfs, packages_zfs)
