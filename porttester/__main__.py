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

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from porttester.execute import execute
from porttester.jail import start_jail
from porttester.jail.populate import JailSpec, populate_jail
from porttester.mount.filesystems import mount_devfs, mount_nullfs, mount_tmpfs
from porttester.resources.enumerate import enumerate_resources
from porttester.workdir import Workdir
from porttester.zfs import ZFS

_JAIL_SPECS = {
    '12-i386': JailSpec(version='12.3-RELEASE', architecture='i386'),
    '12-amd64': JailSpec(version='12.3-RELEASE', architecture='amd64'),
    '13-i386': JailSpec(version='13.0-RELEASE', architecture='i386'),
    '13-amd64': JailSpec(version='13.0-RELEASE', architecture='amd64'),
}


_USE_JAILS = ['13-amd64']


def replace_in_file(path: Path, pattern: str, replacement: str) -> None:
    with open(path, 'r') as fd:
        data = fd.read().replace(pattern, replacement)

    with open(path, 'w') as fd:
        fd.write(data)


def unicalize(items: list[str]) -> list[str]:
    res = []
    seen = set()
    for item in items:
        if item not in seen:
            res.append(item)
            seen.add(item)
    return res


class PortTester:
    _workdir: Workdir
    _portsdir: Path
    _distfilesdir: Path

    def __init__(self, workdir: Workdir, portsdir: Path, distfilesdir: Path) -> None:
        self._workdir = workdir
        self._portsdir = portsdir
        self._distfilesdir = distfilesdir

    async def _get_prepared_jail(self, name: str) -> ZFS:
        jail = self._workdir.get_jail_master(name)
        spec = _JAIL_SPECS[name]

        if await jail.exists() and not (jail.get_path() / 'usr').exists():
            logging.debug(f'jail {name} is incomplete, destroying')
            await jail.destroy()

        if not await jail.exists():
            logging.debug(f'creating jail {name}')
            await jail.create(parents=True)

            logging.debug(f'populating jail {name}')
            await populate_jail(spec, jail.get_path())

            await jail.snapshot('clean')

        logging.debug(f'jail {name} is ready')

        return jail

    async def _cleanup_jail(self, path: Path) -> None:
        for resource in await enumerate_resources(path):
            logging.debug(f'cleaning up jail resource: {resource}')
            await resource.destroy()

    async def run(self, ports_to_test: list[str], ports_to_rebuild: list[str]) -> bool:
        all_ports = unicalize(ports_to_rebuild + ports_to_test)

        for jail_name in _USE_JAILS:
            master_zfs = await self._get_prepared_jail(jail_name)

            instance_name = f'{jail_name}-default'

            instance_zfs = self._workdir.get_jail_instance(instance_name)

            packages_zfs = self._workdir.get_jail_packages(jail_name)

            if not await packages_zfs.exists():
                await packages_zfs.create(parents=True)

            await self._cleanup_jail(instance_zfs.get_path())

            try:
                logging.debug('cloning instance')
                await instance_zfs.clone_from(master_zfs, 'clean', parents=True)

                logging.debug('creating directories')
                ports_path = instance_zfs.get_path() / 'usr' / 'ports'
                distfiles_path = instance_zfs.get_path() / 'distfiles'
                work_path = instance_zfs.get_path() / 'work'
                packages_path = instance_zfs.get_path() / 'packages'

                for path in [ports_path, distfiles_path, work_path, packages_path]:
                    path.mkdir(parents=True, exist_ok=True)

                logging.debug('installing resolv.conf')
                with open(instance_zfs.get_path() / 'etc' / 'resolv.conv', 'w') as fd:
                    fd.write('nameserver 8.8.8.8\n')

                logging.debug('fixing pkg config')
                replace_in_file(instance_zfs.get_path() / 'etc' / 'pkg' / 'FreeBSD.conf', 'quarterly', 'latest')

                logging.debug('mounting filesystems')
                await asyncio.gather(
                    mount_devfs(instance_zfs.get_path() / 'dev'),
                    mount_nullfs(self._portsdir, ports_path),
                    mount_nullfs(self._distfilesdir, distfiles_path, readonly=False),
                    mount_nullfs(packages_zfs.get_path(), packages_path, readonly=False),
                    mount_tmpfs(work_path),
                )

                logging.debug('starting jail')
                jail = await start_jail(instance_zfs.get_path(), networking=True, hostname='portester')

                logging.debug('bootstrapping pkg')

                await jail.execute('pkg', 'bootstrap', '-q', '-y')

                logging.debug('gathering depends')

                depend_origins = set()

                for port in all_ports:
                    depends_lines = await jail.execute(
                        'make', '-C', str(Path('/usr/ports') / port),
                        '-V', 'BUILD_DEPENDS',
                        '-V', 'RUN_DEPENDS',
                        '-V', 'LIB_DEPENDS',
                        *(('-V', 'TEST_DEPENDS') if port in ports_to_test else ())
                    )

                    for depend in ' '.join(depends_lines).split():
                        depend_origins.add(depend.split(':')[1])

                depends = set()

                for depend in depend_origins:
                    if '@' in depend:
                        origin, flavor = depend.split('@', 1)
                        flavor_args = ['FLAVOR=' + flavor]
                    else:
                        origin = depend
                        flavor_args = []

                    pkgname = (await jail.execute(
                        'env', *flavor_args, 'make', '-C', f'/usr/ports/{origin}', '-V', 'PKGNAME'
                    ))[0]

                    depends.add(pkgname.rsplit('-', 1)[0])

                if depends:
                    logging.debug(f'installing {len(depends)} dependencies from packages')

                    await jail.execute(
                        'env', 'PKG_CACHEDIR=/packages', 'pkg', 'install', '-q', '-y', *depends
                    )

                for port in all_ports:
                    logging.debug(f'fetching {port} for rebuild from port')

                    returncode = await jail.execute_by_line(
                        'env',
                        'BATCH=1',
                        'DISTDIR=/distfiles',
                        'WRKDIRPREFIX=/work',
                        'PKG_ADD=false',
                        'USE_PACKAGE_DEPENDS_ONLY=1',
                        'make', '-C', f'/usr/ports/{port}', 'checksum'
                    )

                    if returncode != 0:
                        print('failure')
                        return False

                logging.debug('restarting jail with disabled network')

                await jail.destroy()

                jail = await start_jail(instance_zfs.get_path(), networking=False, hostname='porttester_nonet')

                for port in all_ports:
                    logging.debug(f'rebuilding {port} from ports')

                    await jail.execute_by_line(
                        'env', 'PKG_CACHEDIR=/packages', 'pkg', 'delete', '-q', '-y', '-f', port
                    )

                    logging.debug('running make install')

                    returncode = await jail.execute_by_line(
                        'env',
                        'BATCH=1',
                        'DISTDIR=/distfiles',
                        'WRKDIRPREFIX=/work',
                        'PKG_ADD=false',
                        'USE_PACKAGE_DEPENDS_ONLY=1',
                        'make', '-C', f'/usr/ports/{port}', 'install'
                    )

                    if returncode != 0:
                        print('failed')
                        return False

                    if port in ports_to_test:
                        logging.debug('running make test')

                        returncode = await jail.execute_by_line(
                            'env',
                            'BATCH=1',
                            'DISTDIR=/nonexeistent',
                            'WRKDIRPREFIX=/work',
                            'PKG_ADD=false',
                            'USE_PACKAGE_DEPENDS_ONLY=1',
                            'make', '-C', f'/usr/ports/{port}', 'test'
                        )

                        if returncode != 0:
                            print('failure')
                            return False
            finally:
                await self._cleanup_jail(instance_zfs.get_path())

        return True


def sig_handler() -> None:
    print('Interrupted')


async def parse_arguments() -> argparse.Namespace:
    AUTODETECT = 'autodect'

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--portstree', default='/usr/ports', metavar='PATH', help='ports tree directory to use in jails')
    parser.add_argument('--distfiles', default=AUTODETECT, metavar='PATH', help='distfiles directory tree to use in jails')

    parser.add_argument('-r', '--rebuild', metavar='PORT', nargs='*', help='port origin(s) to rebuild from ports')
    parser.add_argument('ports', metavar='PORT', nargs='+', help='port origin(s) to test')

    args = parser.parse_args()

    if args.distfiles == AUTODETECT:
        distdir = await execute('make', '-C', args.portstree, '-V', 'DISTDIR')

        if distdir and distdir[0] and os.path.exists(distdir[0]):
            args.distfiles = distdir[0]
        else:
            raise RuntimeError('cannot autodetect distfiles location')

    if args.rebuild is None:
        args.rebuild = []

    return args


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    args = await parse_arguments()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, sig_handler)

    workdir = await Workdir.initialize()

    porttester = PortTester(
        workdir=workdir,
        portsdir=args.portstree,
        distfilesdir=args.distfiles
    )

    res = await porttester.run(args.ports, args.rebuild)

    sys.exit(0 if res else 1)


asyncio.run(main())
