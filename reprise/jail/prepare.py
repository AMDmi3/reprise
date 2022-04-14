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
from pathlib import Path

from reprise.execute import execute
from reprise.jail import JailSpec
from reprise.lock import file_lock
from reprise.workdir import Workdir
from reprise.zfs import ZFS

# Bump this after modifying jail creation code to push changes to users;
# When this number is changes, all jails are recreated
_JAIL_EPOCH = 2

_JAIL_TARBALLS = ['base.txz']

_FREEBSD_RELEASES_URL = 'https://download.freebsd.org/ftp/releases'


@dataclass
class PreparedJail:
    jail_zfs: ZFS
    packages_zfs: ZFS


async def _check_jail_compilance(jail_zfs: ZFS, spec: JailSpec) -> bool:
    if await jail_zfs.get_property_maybe('reprise:jail_ready_epoch') != str(_JAIL_EPOCH):
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_version') != spec.version:
        return False

    if await jail_zfs.get_property_maybe('reprise:jail_arch') != spec.arch:
        return False

    return True


async def _install_tarball(path: Path, url: str) -> None:
    command = f'fetch -o- {url} | tar -C {path} -x -f- -z'

    proc = await asyncio.create_subprocess_shell(command, stderr=asyncio.subprocess.PIPE)

    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError('failed to populate jail ' + stderr.decode('utf-8'))


def _get_osversion(jail_path: Path) -> str:
    with open(jail_path / 'usr/include/sys/param.h') as f:
        for line in f:
            if line.startswith('#define __FreeBSD_version '):
                return line.split()[2]

    raise RuntimeError('cannot determine jail OSVERSION')


async def _update_login_conf(jail_path: Path, spec: JailSpec) -> None:
    login_conf_path = jail_path / 'etc/login.conf'

    login_env = {
        'UNAME_r': spec.version,
        'UNAME_v': f'FreeBSD {spec.version}',
        'UNAME_m': spec.arch,
        'UNAME_p': spec.arch,
        'OSVERSION': _get_osversion(jail_path),
    }

    login_env_str = ','.join(f'{k}={v}' for k, v in login_env.items())

    tmp_path = login_conf_path.with_suffix('.new')

    done = False
    with open(login_conf_path) as old:
        with open(tmp_path, 'x') as new:
            for line in old:
                if ':setenv=' in line and not done:
                    line = line.replace(':\\', f',{login_env_str}:\\')
                    done = True

                new.write(line)

    tmp_path.replace(login_conf_path)

    if not done:
        raise RuntimeError('failed to modify jail login.conf')

    await execute('cap_mkdb', str(login_conf_path))


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

            for tarball in _JAIL_TARBALLS:
                logger.debug(f'fetching and installing {tarball}')
                url = f'{_FREEBSD_RELEASES_URL}/{spec.arch}/{spec.version}/{tarball}'
                await _install_tarball(jail_zfs.get_path(), url)

            logger.debug('updating login.conf')
            await _update_login_conf(jail_zfs.get_path(), spec)

            await jail_zfs.snapshot('clean')

            await jail_zfs.set_property('reprise:jail_version', spec.version)
            await jail_zfs.set_property('reprise:jail_arch', spec.arch)
            await jail_zfs.set_property('reprise:jail_ready_epoch', str(_JAIL_EPOCH))

            logger.info(f'successfully created jail {spec.name}')

    return PreparedJail(jail_zfs, packages_zfs)
