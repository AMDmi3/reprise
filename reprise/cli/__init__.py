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

from reprise.jail import NetworkingMode, start_jail
from reprise.jail.populate import JailSpec, populate_jail
from reprise.jobs import JobSpec
from reprise.jobs.generate import generate_jobs
from reprise.lock import file_lock
from reprise.logging_ import setup_logging
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


def replace_in_file(path: Path, pattern: str, replacement: str) -> None:
    with open(path, 'r') as fd:
        data = fd.read().replace(pattern, replacement)

    with open(path, 'w') as fd:
        fd.write(data)


def int_or_zero(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def get_next_file_name(path: Path) -> Path:
    if not path.exists():
        return path / '0'

    max_log = max((int_or_zero(f.name) for f in path.iterdir() if f.is_file()), default=0)

    return path / str(max_log + 1)


class Worker:
    _logger = logging.getLogger('Job')
    _workdir: Workdir

    def __init__(self, workdir: Workdir) -> None:
        self._workdir = workdir

    async def _get_prepared_jail(self, name: str) -> ZFS:
        jail = self._workdir.get_jail_master(name)
        spec = _JAIL_SPECS[name]

        if await jail.exists() and not (jail.get_path() / 'usr').exists():
            self._logger.debug(f'jail {name} is incomplete, destroying')
            await jail.destroy()

        if not await jail.exists():
            self._logger.debug(f'creating jail {name}')
            await jail.create(parents=True)

            self._logger.debug(f'populating jail {name}')
            await populate_jail(spec, jail.get_path())

            await jail.snapshot('clean')

        self._logger.debug(f'jail {name} is ready')

        return jail

    async def _cleanup_jail(self, path: Path) -> None:
        for resource in await enumerate_resources(path):
            self._logger.debug(f'cleaning up jail resource: {resource}')
            await resource.destroy()

    async def run(self, jobspec: JobSpec) -> bool:
        self._logger.info(f'job started for {jobspec.origin}')

        with file_lock(self._workdir.root.get_path() / 'jails.lock'):
            master_zfs = await self._get_prepared_jail(jobspec.jailname)
            packages_zfs = self._workdir.get_jail_packages(jobspec.jailname)

            if not await packages_zfs.exists():
                await packages_zfs.create(parents=True)

        instance_name = f'{jobspec.jailname}-{os.getpid()}'

        instance_zfs = self._workdir.get_jail_instance(instance_name)

        await self._cleanup_jail(instance_zfs.get_path())

        try:
            self._logger.debug(f'cloning instance {instance_name}')
            await instance_zfs.clone_from(master_zfs, 'clean', parents=True)

            self._logger.debug('creating directories')
            ports_path = instance_zfs.get_path() / 'usr' / 'ports'
            distfiles_path = instance_zfs.get_path() / 'distfiles'
            work_path = instance_zfs.get_path() / 'work'
            packages_path = instance_zfs.get_path() / 'packages'

            for path in [ports_path, distfiles_path, work_path, packages_path]:
                path.mkdir(parents=True, exist_ok=True)

            self._logger.debug('installing resolv.conf')
            with open(instance_zfs.get_path() / 'etc' / 'resolv.conf', 'w') as fd:
                fd.write('nameserver 8.8.8.8\n')

            self._logger.debug('installing make.conf')
            with open(instance_zfs.get_path() / 'etc' / 'make.conf', 'w') as fd:
                fd.write('BUILD_ALL_PYTHON_FLAVORS=yes\n')

            self._logger.debug('fixing pkg config')
            replace_in_file(instance_zfs.get_path() / 'etc' / 'pkg' / 'FreeBSD.conf', 'quarterly', 'latest')

            self._logger.debug('mounting filesystems')
            await asyncio.gather(
                mount_devfs(instance_zfs.get_path() / 'dev'),
                mount_nullfs(jobspec.portsdir, ports_path),
                mount_nullfs(jobspec.distdir, distfiles_path, readonly=False),
                mount_nullfs(packages_zfs.get_path(), packages_path, readonly=False),
                mount_tmpfs(work_path),
            )

            self._logger.debug('starting jail')
            jail = await start_jail(instance_zfs.get_path(), networking=NetworkingMode.UNRESTRICTED, hostname='reprise')

            self._logger.debug('bootstrapping pkg')

            await jail.execute('pkg', 'bootstrap', '-q', '-y')

            await jail.execute('pkg', 'update', '-q')

            plan = await Planner(jail).prepare([jobspec.origin], list(jobspec.origins_to_rebuild))

            log_path = get_next_file_name(self._workdir.get_logs().get_path())

            with open(log_path, 'x') as log:
                self._logger.info(f'log file used: {log_path}')

                self._logger.info('fetching')

                with file_lock(self._workdir.root.get_path() / 'fetch.lock'):
                    if not await plan.fetch(jail, log=log, fail_fast=jobspec.fail_fast):
                        self._logger.error(f'fetching failed, see log {log_path}')
                        return False

                self._logger.debug('restarting the jail with disabled network')

                await jail.destroy()
                jail = await start_jail(instance_zfs.get_path(), networking=NetworkingMode.RESTRICTED, hostname='reprise_nonet')

                self._logger.info('installation')

                if not await plan.install(jail, log=log, fail_fast=jobspec.fail_fast):
                    self._logger.error(f'installation failed, log file: {log_path}')
                    return False

                self._logger.info('testing')

                if not await plan.test(jail, log=log, fail_fast=jobspec.fail_fast):
                    self._logger.error(f'testing failed, log file: {log_path}')
                    return False

            self._logger.info(f'job succeeded, log file: {log_path}')

            return True
        except RuntimeError:
            self._logger.exception('job failed due to internal error')
        finally:
            self._logger.info('cleaning up')
            await self._cleanup_jail(instance_zfs.get_path())

        return False


async def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    group = parser.add_argument_group('general')

    group.add_argument('-d', '--debug', action='store_true', help='enable debug logging')
    group.add_argument('--fail-fast', action='store_true', help='stop processing after the first failure')

    group = parser.add_argument_group('job specification')
    group.add_argument('-p', '--portsdir', metavar='PATH', type=str, help='ports tree directory to use in jails')
    group.add_argument('--distdir', metavar='PATH', type=str, help='distfiles directory tree to use in jails (default: autodetect)')

    group.add_argument('-r', '--rebuild', metavar='PORT', nargs='*', help='port origin(s) to rebuild from ports')
    group.add_argument('-f', '--file', type=str, help='path to file with port origin(s) to test (- to read from stdin)')
    group.add_argument('ports', metavar='PORT', nargs='*', help='port origin(s) to test')

    args = parser.parse_args()

    return args


async def amain() -> None:
    args = await parse_arguments()

    setup_logging(args.debug)

    jobspecs = await generate_jobs(args)

    if not jobspecs:
        print('FATAL: no ports specified')
        sys.exit(1)

    workdir = await Workdir.initialize()
    worker = Worker(workdir=workdir)

    success = True
    for jobspec in jobspecs:
        success = await worker.run(jobspec) and success

    sys.exit(0 if success else 1)


def main() -> None:
    asyncio.run(amain())


if __name__ == '__main__':
    main()
