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
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from reprise.execute import execute
from reprise.jail.prepare import get_prepared_jail
from reprise.jobs import JobSpec
from reprise.lock import file_lock
from reprise.mount.filesystems import mount_devfs, mount_nullfs, mount_tmpfs
from reprise.plan.planner import Planner
from reprise.prison import NetworkingMode, start_prison
from reprise.repository import RepositoryManager
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


JobStatus = Enum('JobStatus', 'SUCCESS FETCH_FAILED BUILD_FAILED TEST_FAILED CRASHED SKIPPED')


@dataclass
class JobResult:
    spec: JobSpec
    status: JobStatus
    log_path: Path | None = None
    details: str | None = None


class JobRunner:
    _logger = logging.getLogger('Job')

    _workdir: Workdir
    _repository_manager: RepositoryManager

    def __init__(self, workdir: Workdir, repository_manager: RepositoryManager) -> None:
        self._workdir = workdir
        self._repository_manager = repository_manager

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

            self._logger.debug('obtaining repository')
            repository = await self._repository_manager.get_repository(
                release=jobspec.jailspec.release,
                arch=jobspec.jailspec.arch
            )

            self._logger.debug('creating host directories')
            host_packages_path = repository.get_path()
            host_ccache_path = self._workdir.get_ccache().get_path() / ('nobody' if jobspec.build_as_nobody else 'root')

            host_packages_path.mkdir(parents=True, exist_ok=True)

            if jobspec.use_ccache:
                host_ccache_path.mkdir(parents=True, exist_ok=True)
                if jobspec.build_as_nobody:
                    shutil.chown(host_ccache_path, 'nobody', 'nobody')

            self._logger.debug('creating jail directories')
            jail_ports_path = instance_zfs.get_path() / 'usr' / 'ports'
            jail_distfiles_path = instance_zfs.get_path() / 'distfiles'
            jail_work_path = instance_zfs.get_path() / 'work'
            jail_packages_path = instance_zfs.get_path() / 'packages'
            jail_ccache_path = instance_zfs.get_path() / 'ccache'
            jail_localbase_path = instance_zfs.get_path() / 'usr' / 'local'

            for path in [jail_ports_path, jail_distfiles_path, jail_work_path, jail_packages_path, jail_localbase_path]:
                path.mkdir(parents=True, exist_ok=True)

            if jobspec.use_ccache:
                jail_ccache_path.mkdir(parents=True, exist_ok=True)

            self._logger.debug('installing resolv.conf')
            with open(instance_zfs.get_path() / 'etc' / 'resolv.conf', 'w') as fd:
                fd.write('nameserver 8.8.8.8\n')

            self._logger.debug('installing make.conf')
            with open(instance_zfs.get_path() / 'etc' / 'make.conf', 'w') as fd:
                for k, v in jobspec.all_variables.items():
                    fd.write(f'{k}={v}\n')

            self._logger.debug('mounting filesystems')

            mounts = [
                mount_devfs(instance_zfs.get_path() / 'dev'),
                mount_nullfs(jobspec.portsdir, jail_ports_path, readonly=True),
                mount_nullfs(jobspec.distdir, jail_distfiles_path, readonly=False),
                mount_nullfs(host_packages_path, jail_packages_path, readonly=False),
            ]

            if jobspec.use_ccache:
                mounts.append(mount_nullfs(host_ccache_path, jail_ccache_path, readonly=False))

            if jobspec.use_tmpfs_work:
                mounts.append(mount_tmpfs(jail_work_path, limit_bytes=jobspec.tmpfs_limit_bytes))

            if jobspec.use_tmpfs_localbase:
                mounts.append(mount_tmpfs(jail_localbase_path, limit_bytes=jobspec.tmpfs_limit_bytes))

            await asyncio.gather(*mounts)

            if jobspec.build_as_nobody:
                shutil.chown(jail_work_path, 'nobody', 'nobody')

            self._logger.debug('starting prison')
            prison = await start_prison(instance_zfs.get_path(), networking=NetworkingMode.UNRESTRICTED, hostname='reprise-fetcher')

            self._logger.debug('bootstrapping pkg')

            # pkg bootstrap
            # XXX: this is a hack: it overrides dependency mechanisms and allows
            # default pkg dependency checks (looking on ${LOCALBASE}/sbin/pkg to
            # pass, but it does not really install pkg package and breaks ports
            # which need libpkg.so, or depend on `pkg` package.
            # We need to
            # 1) Switch to dependency discovery based on Repository data only
            # 2) Rework Tasks to allow more flexible dependency handling, e.g.
            #    support FETCH_DEPENDS and PKG_DEPENDS properly
            # then we could rely on ports' mechanisms for pkg installation, and
            # either preinstall the package unconditionally for our own needs,
            # or use pkg-static binary located in some internal location and
            # call it by that path
            pkg_info = repository.get_package_info_by_name('pkg')
            if pkg_info is None:
                raise RuntimeError('no package for pkg')
            pkg_package = await repository.get_package(pkg_info)
            await execute('tar', '-x', '-f', str(pkg_package.path), '-C', str(instance_zfs.get_path()), '--strip-components=1', '/usr/local/sbin/pkg-static')

            jail_pkg_path = instance_zfs.get_path() / 'usr/local/sbin/pkg'
            jail_pkg_static_path = instance_zfs.get_path() / 'usr/local/sbin/pkg-static'
            jail_pkg_static_path.link_to(jail_pkg_path)
            # /pkg bootstrap

            lines = await prison.execute(
                'env',
                '_LICENSE_STATUS=accepted',
                'make', '-C', f'/usr/ports/{jobspec.origin}', '-V', 'IGNORE',
            )

            if lines and lines[0]:
                return result(status=JobStatus.SKIPPED, details=f'{lines[0]}')

            plan = await Planner(prison, repository).prepare(
                jobspec.origin,
                jobspec.origins_to_rebuild,
                jobspec.build_as_nobody,
            )

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
                prison = await start_prison(instance_zfs.get_path(), networking=jobspec.networking_build, hostname='reprise-builder')

                self._logger.info('installation')

                if not await plan.install(prison, log=log, fail_fast=jobspec.fail_fast):
                    self._logger.error(f'installation failed, log file: {log_path}')
                    return result(status=JobStatus.BUILD_FAILED)

                self._logger.debug('setting up the prison for testing')

                if jobspec.do_test:
                    await prison.destroy()  # XXX: implement and use modification of running prison
                    prison = await start_prison(instance_zfs.get_path(), networking=jobspec.networking_test, hostname='reprise-tester')

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
