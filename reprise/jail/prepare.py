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
from dataclasses import dataclass

from reprise.jail import JailSpec
from reprise.lock import file_lock
from reprise.workdir import Workdir
from reprise.zfs import ZFS

# Bump this after modifying jail creation code to push changes to users;
# When this number is changes, all jails are recreated
_JAIL_EPOCH = 1


async def _check_jail_compilance(jail_zfs: ZFS, spec: JailSpec) -> bool:
    if await jail_zfs.get_property_maybe('reprise:jail_ready_epoch') != str(_JAIL_EPOCH):
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_version') != spec.version:
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_arch') != spec.arch:
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
            logger.info(f'creating jail {spec.name}')
            await jail_zfs.create(parents=True)

            url_prefix = f'https://download.freebsd.org/ftp/releases/{spec.arch}/{spec.version}/'
            for tarball in ['base.txz']:
                command = f'fetch -o- {url_prefix}/{tarball} | tar -C {jail_path} -x -f- -z'

                proc = await asyncio.create_subprocess_shell(command, stderr=asyncio.subprocess.PIPE)

                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    await jail_zfs.destroy()
                    raise RuntimeError('failed to populate jail ' + stderr.decode('utf-8'))

            await jail_zfs.snapshot('clean')

            await jail_zfs.set_property('reprise:jail_version', spec.version)
            await jail_zfs.set_property('reprise:jail_arch', spec.arch)
            await jail_zfs.set_property('reprise:jail_ready_epoch', str(_JAIL_EPOCH))

            logger.info(f'successfully created jail {spec.name}')

    return PreparedJail(jail_zfs, packages_zfs)
