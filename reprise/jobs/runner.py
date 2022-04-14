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
import functools
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from reprise.jail.prepare import get_prepared_jail
from reprise.jobs import JobSpec
from reprise.lock import file_lock
from reprise.mount.filesystems import mount_devfs, mount_nullfs, mount_tmpfs
from reprise.plan.planner import Planner
from reprise.prison import NetworkingIsolationMode, start_prison
from reprise.resources.enumerate import enumerate_resources
from reprise.workdir import Workdir


def _replace_in_file(path: Path, pattern: str, replacement: str) -> None:
    with open(path, 'r') as fd:
        data = fd.read().replace(pattern, replacement)

    with open(path, 'w') as fd:
        fd.write(data)


def _int_or_zero(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _get_next_file_name(path: Path) -> Path:
    if not path.exists():
        return path / '0'

    max_log = max((_int_or_zero(f.name) for f in path.iterdir() if f.is_file()), default=0)

    return path / str(max_log + 1)


JobStatus = Enum('JobStatus', 'SUCCESS FETCH_FAILED BUILD_FAILED TEST_FAILED CRASHED')


@dataclass
class JobResult:
    spec: JobSpec
    status: JobStatus
    log_path: Path | None = None


class JobRunner:
    _logger = logging.getLogger('Job')
    _workdir: Workdir

    def __init__(self, workdir: Workdir) -> None:
        self._workdir = workdir

    async def _cleanup_jail(self, path: Path) -> None:
        for resource in await enumerate_resources(path):
            self._logger.debug(f'cleaning up jail resource: {resource}')
            await resource.destroy()

    async def run(self, jobspec: JobSpec) -> JobResult:
        result = functools.partial(JobResult, spec=jobspec)

        self._logger.info(f'job started for {jobspec}')

        jail = await get_prepared_jail(self._workdir, jobspec.jailspec)

        instance_name = f'{jobspec.jailspec.name}-{os.getpid()}'

        instance_zfs = self._workdir.get_jail_instance(instance_name)

        await self._cleanup_jail(instance_zfs.get_path())

        try:
            self._logger.debug(f'cloning instance {instance_name}')
            await instance_zfs.clone_from(jail.jail_zfs, 'clean', parents=True)

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
                for k, v in jobspec.all_variables.items():
                    fd.write(f'{k}={v}\n')

            self._logger.debug('fixing pkg config')
            _replace_in_file(instance_zfs.get_path() / 'etc' / 'pkg' / 'FreeBSD.conf', 'quarterly', 'latest')

            self._logger.debug('mounting filesystems')
            await asyncio.gather(
                mount_devfs(instance_zfs.get_path() / 'dev'),
                mount_nullfs(jobspec.portsdir, ports_path),
                mount_nullfs(jobspec.distdir, distfiles_path, readonly=False),
                mount_nullfs(jail.packages_zfs.get_path(), packages_path, readonly=False),
                mount_tmpfs(work_path),
            )

            self._logger.debug('starting prison')
            prison = await start_prison(instance_zfs.get_path(), networking=NetworkingIsolationMode.UNRESTRICTED, hostname='reprise')

            self._logger.debug('bootstrapping pkg')

            await prison.execute('pkg', 'bootstrap', '-q', '-y')

            await prison.execute('pkg', 'update', '-q')

            plan = await Planner(prison).prepare(jobspec.origin, jobspec.origins_to_rebuild)

            log_path = _get_next_file_name(self._workdir.get_logs().get_path())

            result = functools.partial(result, log_path=log_path)

            with open(log_path, 'x') as log:
                self._logger.info(f'log file used: {log_path}')

                self._logger.info('fetching')

                with file_lock(self._workdir.root.get_path() / 'fetch.lock'):
                    if not await plan.fetch(prison, log=log, fail_fast=jobspec.fail_fast):
                        self._logger.error(f'fetching failed, see log {log_path}')
                        return result(status=JobStatus.FETCH_FAILED)

                self._logger.debug('setting up the prison for building')

                await prison.destroy()  # XXX: implement and use modification of running prison
                prison = await start_prison(instance_zfs.get_path(), networking=jobspec.networking_isolation_build, hostname='reprise_nonet')

                self._logger.info('installation')

                if not await plan.install(prison, log=log, fail_fast=jobspec.fail_fast):
                    self._logger.error(f'installation failed, log file: {log_path}')
                    return result(status=JobStatus.BUILD_FAILED)

                self._logger.debug('setting up the prison for testing')

                await prison.destroy()  # XXX: implement and use modification of running prison
                prison = await start_prison(instance_zfs.get_path(), networking=jobspec.networking_isolation_test, hostname='reprise_nonet')

                self._logger.info('testing')

                if not await plan.test(prison, log=log, fail_fast=jobspec.fail_fast):
                    self._logger.error(f'testing failed, log file: {log_path}')
                    return result(status=JobStatus.TEST_FAILED)

            self._logger.info(f'job succeeded, log file: {log_path}')

            return result(status=JobStatus.SUCCESS)
        except RuntimeError:
            self._logger.exception('job failed due to internal error')
        finally:
            self._logger.info('cleaning up')
            await self._cleanup_jail(instance_zfs.get_path())

        return result(status=JobStatus.CRASHED)
