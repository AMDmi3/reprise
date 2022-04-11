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

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from reprise.execute import execute
from reprise.jail import NetworkingMode, start_jail
from reprise.jail.populate import JailSpec, populate_jail
from reprise.lock import file_lock
from reprise.mount.filesystems import mount_devfs, mount_nullfs, mount_tmpfs
from reprise.plan.planner import Planner
from reprise.resources.enumerate import enumerate_resources
from reprise.workdir import Workdir
from reprise.zfs import ZFS

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


class Worker:
    _workdir: Workdir
    _portsdir: Path
    _distdir: Path

    def __init__(self, workdir: Workdir, portsdir: Path, distdir: Path) -> None:
        self._workdir = workdir
        self._portsdir = portsdir
        self._distdir = distdir

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

    async def _run_one_jail(self, jail_name: str, ports_to_test: list[str], ports_to_rebuild: list[str]) -> bool:
        with file_lock(self._workdir.root.get_path() / 'jails.lock'):
            master_zfs = await self._get_prepared_jail(jail_name)
            packages_zfs = self._workdir.get_jail_packages(jail_name)

            if not await packages_zfs.exists():
                await packages_zfs.create(parents=True)

        instance_name = f'{jail_name}-{os.getpid()}'

        instance_zfs = self._workdir.get_jail_instance(instance_name)

        await self._cleanup_jail(instance_zfs.get_path())

        try:
            logging.debug(f'cloning instance {instance_name}')
            await instance_zfs.clone_from(master_zfs, 'clean', parents=True)

            logging.debug('creating directories')
            ports_path = instance_zfs.get_path() / 'usr' / 'ports'
            distfiles_path = instance_zfs.get_path() / 'distfiles'
            work_path = instance_zfs.get_path() / 'work'
            packages_path = instance_zfs.get_path() / 'packages'

            for path in [ports_path, distfiles_path, work_path, packages_path]:
                path.mkdir(parents=True, exist_ok=True)

            logging.debug('installing resolv.conf')
            with open(instance_zfs.get_path() / 'etc' / 'resolv.conf', 'w') as fd:
                fd.write('nameserver 8.8.8.8\n')

            logging.debug('installing make.conf')
            with open(instance_zfs.get_path() / 'etc' / 'make.conf', 'w') as fd:
                fd.write('BUILD_ALL_PYTHON_FLAVORS=yes\n')

            logging.debug('fixing pkg config')
            replace_in_file(instance_zfs.get_path() / 'etc' / 'pkg' / 'FreeBSD.conf', 'quarterly', 'latest')

            logging.debug('mounting filesystems')
            await asyncio.gather(
                mount_devfs(instance_zfs.get_path() / 'dev'),
                mount_nullfs(self._portsdir, ports_path),
                mount_nullfs(self._distdir, distfiles_path, readonly=False),
                mount_nullfs(packages_zfs.get_path(), packages_path, readonly=False),
                mount_tmpfs(work_path),
            )

            logging.debug('starting jail')
            jail = await start_jail(instance_zfs.get_path(), networking=NetworkingMode.UNRESTRICTED, hostname='reprise')

            logging.debug('bootstrapping pkg')

            await jail.execute('pkg', 'bootstrap', '-q', '-y')

            await jail.execute('pkg', 'update', '-q')

            plan = await Planner(jail).prepare(ports_to_test, ports_to_rebuild)

            with file_lock(self._workdir.root.get_path() / 'fetch.lock'):
                await plan.fetch(jail)

            logging.debug('restarting the jail with disabled network')

            await jail.destroy()
            jail = await start_jail(instance_zfs.get_path(), networking=NetworkingMode.RESTRICTED, hostname='reprise_nonet')

            await plan.install(jail)

            await plan.test(jail)
        finally:
            await self._cleanup_jail(instance_zfs.get_path())

        return True

    async def run(self, ports_to_test: list[str], ports_to_rebuild: list[str]) -> bool:
        return all([
            await self._run_one_jail(jail_name, ports_to_test, ports_to_rebuild)
            for jail_name in _USE_JAILS
        ])


_FALLBACK_PORTSDIR = '/usr/ports'


async def discover_environment(args: argparse.Namespace) -> None:
    logger = logging.getLogger('Discover')

    if args.portsdir and args.distdir and args.ports:
        return

    logger.debug('some required args were not specified, need to discover')

    if not args.portsdir and os.path.exists('Makefile'):
        lines = await execute('make', '-V', 'PORTSDIR', '-V', 'PORTNAME', allow_failure=True)
        if len(lines) == 2 and all(lines):
            logger.debug('we seem to be in a port directory, using it')

            args.portsdir = lines[0]
            logger.debug(f'discovered PORTSDIR: {args.portsdir}')

            if not args.ports:
                origin = '/'.join(os.getcwd().rsplit('/', 2)[-2:])
                logger.debug(f'assumed port to build: {origin}')
                args.ports = [origin]

    if not args.portsdir:
        args.portsdir = _FALLBACK_PORTSDIR
        logger.debug(f'assumed PORTSDIR: {args.portsdir}')

    if not args.distdir:
        lines = await execute('make', '-C', args.portsdir, '-V', 'DISTDIR', allow_failure=True)
        if lines and lines[0]:
            args.distdir = lines[0]
            logger.debug(f'discovered DISTDIR: {args.distdir}')

    assert(args.portsdir)

    if not args.distdir:
        print('FATAL: no distdir specified', file=sys.stderr)
        sys.exit(1)

    if not args.ports:
        print('FATAL: no ports specified to build', file=sys.stderr)
        sys.exit(1)

    if args.rebuild is None:
        args.rebuild = []


async def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--portsdir', metavar='PATH', type=str, help='ports tree directory to use in jails')
    parser.add_argument('--distdir', metavar='PATH', type=str, help='distfiles directory tree to use in jails')

    parser.add_argument('-r', '--rebuild', metavar='PORT', nargs='*', help='port origin(s) to rebuild from ports')
    parser.add_argument('ports', metavar='PORT', nargs='*', help='port origin(s) to test')

    args = parser.parse_args()

    await discover_environment(args)

    return args


async def amain() -> None:
    logging.basicConfig(level=logging.DEBUG)

    args = await parse_arguments()

    workdir = await Workdir.initialize()

    worker = Worker(
        workdir=workdir,
        portsdir=args.portsdir,
        distdir=args.distdir
    )

    await worker.run(args.ports, args.rebuild)

    sys.exit(0)


def main() -> None:
    asyncio.run(amain())


if __name__ == '__main__':
    main()
