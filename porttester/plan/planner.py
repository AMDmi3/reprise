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

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonslicer import JsonSlicer

from porttester.jail import Jail
from porttester.plan import Plan
from porttester.plan.tasks import PackageTask, PortTask, Task
from porttester.types import Port


@dataclass
class _QueueItem:
    port: Port | None = None
    pkgname: str | None = None


class Planner:
    _logger = logging.getLogger('Planner')

    _jail: Jail

    def __init__(self, jail: Jail) -> None:
        self._jail = jail

    async def _get_port_depends(self, port: Port, want_test_depends: bool = False) -> set[Port]:
        flavor_args = ('env', 'FLAVOR=' + port.flavor) if port.flavor is not None else ()

        depends_lines = await self._jail.execute(
            *flavor_args,
            'make', '-C', str(Path('/usr/ports') / port.origin),
            '-V', 'BUILD_DEPENDS',
            '-V', 'RUN_DEPENDS',
            '-V', 'LIB_DEPENDS',
            *(('-V', 'TEST_DEPENDS') if want_test_depends else ())
        )

        depends = set()

        for item in ' '.join(depends_lines).split():
            depend = item.split(':')[1]

            if '@' in depend:
                depends.add(Port(*depend.split('@', 1)))
            else:
                depends.add(Port(depend, None))

        return depends

    async def _get_port_package_name(self, port: Port) -> str:
        flavor_args = ('env', 'FLAVOR=' + port.flavor) if port.flavor is not None else ()

        return (await self._jail.execute(
            *flavor_args, 'make', '-C', f'/usr/ports/{port.origin}', '-V', 'PKGNAME'
        ))[0].rsplit('-', 1)[0]

    async def _get_port_default_flavor(self, origin: str) -> str | None:
        lines = await self._jail.execute('make', '-C', f'/usr/ports/{origin}', '-V', 'FLAVOR')

        return lines[0] if lines and lines[0] else None

    async def _get_package_manifest(self, pkgname: str) -> dict[str, Any] | None:
        manifests_lines = await self._jail.execute('pkg', 'search', '-R', '--raw-format', 'json', '-e', '-S', 'name', pkgname, allow_failure=True)

        if not manifests_lines:
            return None

        manifests = list(JsonSlicer(io.StringIO('\n'.join(manifests_lines)), (), yajl_allow_multiple_values=True))

        if len(manifests) != 1:
            raise RuntimeError(f'unexpected number of manifests for {pkgname}: {len(manifests)}')

        return cast(dict[str, Any], manifests[0])

    async def prepare(self, origins_to_test: list[str], origins_to_rebuild: list[str]) -> Plan:
        queue = []
        tasks: list[Task] = []
        seen_packages = set()

        for origin in origins_to_test:
            queue.append(_QueueItem(port=Port(origin, await self._get_port_default_flavor(origin))))

        queue_pos = 0

        while queue_pos < len(queue):
            item = queue[queue_pos]
            queue_pos += 1

            # either of item.pkgname or item.port may be undefined
            if item.pkgname is None:
                assert item.port is not None
                item.pkgname = await self._get_port_package_name(item.port)

            if item.pkgname in seen_packages:
                continue
            else:
                seen_packages.add(item.pkgname)

            manifest = None
            if item.port is None:
                assert item.pkgname is not None
                manifest = await self._get_package_manifest(item.pkgname)
                if manifest is None:
                    raise RuntimeError('unexpected package repository inconsistency: no manifest for {item.pkgname}')
                item.port = Port(manifest['origin'], manifest['annotations'].get('flavor'))

            want_testing = item.port.origin in origins_to_test
            prefer_package = not want_testing and item.port.origin not in origins_to_rebuild

            self._logger.debug(f'processing {item.port} aka {item.pkgname}, testing={want_testing}, prefer_package={prefer_package}')

            if prefer_package:
                # manifest may be None here if it hasn't been loaded yet
                if manifest is None:
                    manifest = await self._get_package_manifest(item.pkgname)

                # manifest may be None if the package does not exist in the repository,
                # in which case we'll fallback to the port building
                if manifest is not None:
                    tasks.append(PackageTask(item.pkgname))
                    pkgdepends = list(manifest.get('deps', {}).keys())
                    queue.extend(_QueueItem(pkgname=pkgname) for pkgname in pkgdepends)
                    self._logger.debug(f'planned {item.pkgname} as package, enqueued {len(pkgdepends)} depend(s): {" ".join(map(str, pkgdepends))}')
                    continue

                self._logger.debug(f'no package {item.pkgname} available, falling back to building from port')

            tasks.append(PortTask(item.port, do_test=want_testing))
            portdepends = await self._get_port_depends(item.port, want_test_depends=want_testing)
            queue.extend(_QueueItem(port=port) for port in portdepends)
            self._logger.debug(f'planned {item.port} as port, enqueued {len(portdepends)} depend(s): {" ".join(map(str, portdepends))}')

        plan = Plan()
        for task in reversed(tasks):
            plan.add_task(task)
        return plan
