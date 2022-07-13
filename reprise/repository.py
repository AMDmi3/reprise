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

import asyncio
import datetime
import logging
import os
import pickle
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import aiohttp
from jsonslicer import JsonSlicer

from reprise.compat import dataclass_slots_arg
from reprise.execute import execute
from reprise.lock import file_lock
from reprise.types import Port
from reprise.workdir import Workdir

_CHUNK_SIZE = 1024 * 64


@dataclass(frozen=True, **dataclass_slots_arg)
class PackageInfo:
    name: str
    version: str
    origin: str
    size: int
    flavor: str | None
    deps: list[str] | None

    @property
    def namever(self) -> str:
        return f'{self.name}-{self.version}'

    @property
    def port(self) -> Port:
        return Port(self.origin, self.flavor)

    @property
    def filename(self) -> str:
        return f'{self.namever}.pkg'

    def __repr__(self) -> str:
        return f'{self.port} aka {self.namever}'


@dataclass(frozen=True, **dataclass_slots_arg)
class Package(PackageInfo):
    path: Path


_REPOSITORY_METADATA_VERSION = 1


_REPOSITORY_METADATA_TAG = f'{_REPOSITORY_METADATA_VERSION}/py{sys.version_info.major}.{sys.version_info.minor}'


class BadRepositoryMetadataVersion(RuntimeError):
    pass


class _RepositoryMetadata:
    etag: str
    last_update: datetime.datetime
    packages: list[PackageInfo]

    # XXX: we may optimize by not pickling these: implement __getstate__/__setstate__
    by_name: dict[str, PackageInfo]
    by_namever: dict[str, PackageInfo]
    by_port: dict[Port, PackageInfo]

    def __init__(self, etag: str, last_update: datetime.datetime, packages: list[PackageInfo]) -> None:
        self.etag = etag
        self.last_update = last_update
        self.packages = packages

        self._update_dicts()

    def __getstate__(self) -> tuple[str, str, datetime.datetime, list[PackageInfo]]:
        return (_REPOSITORY_METADATA_TAG, self.etag, self.last_update, self.packages)

    def __setstate__(self, state: tuple[str, str, datetime.datetime, list[PackageInfo]]) -> None:
        tag, *rest = state
        if tag != _REPOSITORY_METADATA_TAG:
            raise BadRepositoryMetadataVersion(f'repository metadata tag mismatch: {tag} != {_REPOSITORY_METADATA_TAG}')
        self.etag, self.last_update, self.packages = rest  # type: ignore  # mypy cannot guess the type of `rest`
        self._update_dicts()

    def _update_dicts(self) -> None:
        self.by_name = {package.name: package for package in self.packages}
        self.by_namever = {package.namever: package for package in self.packages}
        self.by_port = {package.port: package for package in self.packages}


class Repository:
    _logger: logging.Logger

    _url: str
    _abi: str
    _branch: str
    _path: Path

    _metadata: _RepositoryMetadata | None

    _inflight_fetches: set[str]
    _fetch_event: asyncio.Event

    def __init__(self, release: int, arch: str, path: Path, url: str, system: str, branch: str) -> None:
        abi = f'{system}:{release}:{arch}'

        self._logger = logging.getLogger(f'Repository {abi}/{branch}')

        self._logger.debug('initializing')

        self._url = url
        self._abi = abi
        self._branch = branch
        self._path = path

        path.mkdir(parents=True, exist_ok=True)

        self._inflight_fetches = set()
        self._fetch_event = asyncio.Event()

        self._metadata = None

        try:
            self._logger.debug('loading metadata')
            with open(self._path / 'packagesite.pickle', 'rb') as fd:
                self._metadata = pickle.load(fd)
        except (FileNotFoundError, pickle.UnpicklingError, BadRepositoryMetadataVersion) as e:
            self._logger.error(f'loading metadata failed ({e}), forced update required')

    def _get_base_url(self) -> str:
        return f'{self._url}/{self._abi}/{self._branch}'

    def is_initialized(self) -> bool:
        return self._metadata is not None

    def get_path(self) -> Path:
        return self._path

    def get_update_age(self) -> datetime.timedelta | None:
        if self._metadata is None:
            return None
        return datetime.datetime.now() - self._metadata.last_update

    async def update(self, force: bool = False) -> None:
        packagesite_url = self._get_base_url() + '/packagesite.pkg'

        packagesite_pkg_path = self._path / 'packagesite.pkg'
        packagesite_yaml_path = self._path / 'packagesite.yaml'
        packagesite_pickle_path = self._path / 'packagesite.pickle'

        self._logger.debug('updating metadata')

        async with aiohttp.ClientSession(raise_for_status=True) as session:
            if self._metadata and not force:
                self._logger.debug('checking if update is needed')
                async with session.head(packagesite_url) as response:
                    if self._metadata.etag == response.headers.get('etag'):
                        self._logger.debug('repository metadata has not changed')
                        return

            async with session.get(packagesite_url) as response:
                self._logger.debug('fetching repository metadata')
                with open(packagesite_pkg_path, 'wb') as fd:
                    async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                        fd.write(chunk)

                etag = response.headers.get('etag', '')

        self._logger.debug('extracting metadata')
        await execute('tar', '-x', '-f', 'packagesite.pkg', 'packagesite.yaml', cwd=self._path)

        packagesite_pkg_path.unlink()

        self._logger.debug('parsing metadata')
        with open(packagesite_yaml_path) as fd:
            packages = []
            for item in JsonSlicer(fd, (), yajl_allow_multiple_values=True):
                packages.append(PackageInfo(
                    name=item['name'],
                    version=item['version'],
                    origin=item['origin'],
                    size=item['pkgsize'],
                    flavor=item.get('annotations', {}).get('flavor'),
                    deps=list(item.get('deps', {}).keys()) or None,
                ))

            self._metadata = _RepositoryMetadata(
                etag=etag,
                last_update=datetime.datetime.now(),
                packages=packages
            )

        packagesite_yaml_path.unlink()

        self._logger.debug('saving metadata')
        with open(packagesite_pickle_path.with_suffix('.new'), 'wb') as fd:
            pickle.dump(self._metadata, fd)
            fd.flush()
            os.fsync(fd.fileno())

        packagesite_pickle_path.with_suffix('.new').replace(packagesite_pickle_path)

    def get_package_info_by_port(self, port: Port) -> PackageInfo | None:
        if self._metadata is None:
            raise RuntimeError('attempt to access uninitialized repository')
        return self._metadata.by_port.get(port)

    def get_package_info_by_name(self, name: str) -> PackageInfo | None:
        if self._metadata is None:
            raise RuntimeError('attempt to access uninitialized repository')
        return self._metadata.by_name.get(name)

    def get_package_info_by_namever(self, namever: str) -> PackageInfo | None:
        if self._metadata is None:
            raise RuntimeError('attempt to access uninitialized repository')
        return self._metadata.by_namever.get(namever)

    async def get_package(self, package_info: PackageInfo) -> Package:
        package_path = self._path / package_info.filename

        res = Package(**asdict(package_info), path=package_path)

        if package_path.exists():
            self._logger.debug(f'package {package_info.filename} already fetched')
            return res

        if package_info.filename in self._inflight_fetches:
            # wait till some other task fetches it for us
            while package_info.filename in self._inflight_fetches:
                self._logger.debug(f'waiting for another task to fetch package {package_info.filename}')
                await self._fetch_event.wait()
            if package_path.exists():
                self._logger.debug(f'package {package_info.filename} fetched by another task successfully')
                return res
            else:
                self._logger.error(f'failed to fetch {package_info.filename} via another task')
                raise RuntimeError(f'failed to fetch {package_info.filename} via another task')

        self._inflight_fetches.add(package_info.filename)

        try:
            package_url = self._get_base_url() + '/All/' + package_info.filename

            async with aiohttp.ClientSession(raise_for_status=True) as session:
                with open(package_path.with_suffix('.tmp'), 'wb') as fd:
                    async with session.get(package_url) as response:
                        async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                            fd.write(chunk)
                    fd.flush()
                    os.fsync(fd.fileno())
                package_path.with_suffix('.tmp').replace(package_path)

            self._logger.debug(f'package {package_info.filename} fetched successfully')
            return res

        except RuntimeError as e:
            self._logger.error(f'failed to fetch {package_info.filename}: {e}')
            raise
        finally:
            self._inflight_fetches.remove(package_info.filename)
            self._fetch_event.set()


RepositoryUpdateMode = Enum('RepositoryUpdateMode', 'FORCE AUTO DISABLE')


class RepositoryManager:
    _logger = logging.getLogger('RepositoryManager')

    _workdir: Workdir
    _repositories: dict[str, Repository]
    _update_mode: RepositoryUpdateMode
    _update_period: datetime.timedelta | None

    def __init__(self, workdir: Workdir, update_mode: RepositoryUpdateMode, update_period: datetime.timedelta | None = None) -> None:
        self._workdir = workdir
        self._repositories = {}
        self._update_mode = update_mode
        self._update_period = update_period

    async def get_repository(self, release: int, arch: str) -> Repository:
        branch = 'latest'
        system = 'FreeBSD'
        url = 'https://pkg.freebsd.org/'

        key = f'{system}:{release}:{arch}:{branch}'

        path = self._workdir.get_packages().get_path() / key

        if key not in self._repositories:
            self._logger.debug(f'initializing {key}')

            with file_lock(path / 'lock'):
                repository = Repository(
                    url=url,
                    release=release,
                    arch=arch,
                    path=path,
                    system=system,
                    branch=branch,
                )

                if self._update_mode == RepositoryUpdateMode.FORCE:
                    self._logger.debug(f'forcing update of repository {key}')
                    await repository.update(force=True)
                elif self._update_mode == RepositoryUpdateMode.AUTO:
                    age = repository.get_update_age()
                    if self._update_period is not None and age is not None and age < self._update_period:
                        self._logger.debug(f'skipping update of repository {key} based on age')
                    else:
                        self._logger.debug(f'running update of repository {key}')
                        await repository.update()
                else:
                    self._logger.debug(f'update of repository {key} is disabled')

                if not repository.is_initialized():
                    self._logger.error(f'repository {key} is not initialized, cannot continue')
                    raise RuntimeError(f'repository {key} is not initialized, cannot continue')

                self._repositories[key] = repository

        return self._repositories[key]
