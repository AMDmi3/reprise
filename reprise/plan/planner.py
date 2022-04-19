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

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from reprise.plan import Plan
from reprise.plan.tasks import PackageTask, PortTask, Task
from reprise.prison import Prison
from reprise.repository import Repository
from reprise.types import Port


@dataclass
class _TaskItem:
    task: Task
    consumers: list[Optional['_TaskItem']]
    visited: bool = False  # for topological sorting


@dataclass
class _QueueItem:
    port: Port | None = None
    pkgname: str | None = None
    consumer: _TaskItem | None = None


@dataclass
class _PortDepends:
    depends: set[Port]
    test_depends: set[Port]


class Planner:
    _logger = logging.getLogger('Planner')

    _jail: Prison
    _repository: Repository

    def __init__(self, jail: Prison, repository: Repository) -> None:
        self._jail = jail
        self._repository = repository

    async def _get_port_depends(self, port: Port) -> _PortDepends:
        flavor_args = ('env', 'FLAVOR=' + port.flavor) if port.flavor is not None else ()

        lines = await self._jail.execute(
            *flavor_args,
            'make', '-C', str(Path('/usr/ports') / port.origin),
            '-V', 'PKG_DEPENDS',
            '-V', 'EXTRACT_DEPENDS',
            '-V', 'BUILD_DEPENDS',
            '-V', 'RUN_DEPENDS',
            '-V', 'LIB_DEPENDS',
            '-V', 'TEST_DEPENDS'
        )

        def depend2port(depend: str) -> Port:
            origin, *flavor = depend.split(':')[1].split('@', 1)
            return Port(origin, flavor[0] if flavor else None)

        return _PortDepends(
            depends=set(map(depend2port, ' '.join(lines[0:-1]).split())),
            test_depends=set(map(depend2port, lines[-1].split())),
        )

    async def _get_port_package_name(self, port: Port) -> str:
        flavor_args = ('env', 'FLAVOR=' + port.flavor) if port.flavor is not None else ()

        return (await self._jail.execute(
            *flavor_args, 'make', '-C', f'/usr/ports/{port.origin}', '-V', 'PKGNAME'
        ))[0].rsplit('-', 1)[0]

    async def _get_port_default_flavor(self, origin: str) -> str | None:
        lines = await self._jail.execute('make', '-C', f'/usr/ports/{origin}', '-V', 'FLAVOR')

        return lines[0] if lines and lines[0] else None

    async def prepare(self, origin: str, origins_to_rebuild: set[str], build_as_nobody: bool) -> Plan:
        tasks: dict[str, _TaskItem] = {}
        queue = [
            # the primary port to test
            _QueueItem(port=Port(origin, await self._get_port_default_flavor(origin)))
        ]

        queue_pos = 0
        while queue_pos < len(queue):
            item = queue[queue_pos]
            queue_pos += 1

            # either of item.pkgname or item.port may be undefined, but we need both
            if item.pkgname is None:
                assert item.port is not None
                item.pkgname = await self._get_port_package_name(item.port)

            # early exit if this dependecy was already processed
            # we just need to register it in the graph
            if item.pkgname in tasks:
                tasks[item.pkgname].consumers.append(item.consumer)
                continue

            # either of item.pkgname or item.port may be undefined, but we need both
            manifest = None
            if item.port is None:
                assert item.pkgname is not None
                manifest = self._repository.get_package_info_by_name(item.pkgname)
                if manifest is None:
                    raise RuntimeError('unexpected package repository inconsistency: no manifest for {item.pkgname}')
                item.port = Port(manifest.origin, manifest.flavor)

            want_testing = item.port.origin == origin
            prefer_package = not want_testing and item.port.origin not in origins_to_rebuild

            self._logger.debug(f'processing {item.port} aka {item.pkgname}, testing={want_testing}, prefer_package={prefer_package}')

            if prefer_package:
                # manifest may be None here if it hasn't been loaded yet
                if manifest is None:
                    manifest = self._repository.get_package_info_by_name(item.pkgname)

                # manifest may be None if the package does not exist in the repository,
                # in which case we'll fallback to the port building
                if manifest is not None:
                    pkgdepends = manifest.deps if manifest.deps is not None else {}
                    task_item = _TaskItem(
                        PackageTask(self._repository, manifest),
                        [item.consumer]
                    )
                    tasks[item.pkgname] = task_item
                    queue.extend(_QueueItem(pkgname=pkgname, consumer=task_item) for pkgname in pkgdepends)
                    self._logger.debug(f'planned {item.pkgname} as package, enqueued {len(pkgdepends)} depend(s): {" ".join(map(str, pkgdepends))}')
                    continue

                self._logger.debug(f'no package {item.pkgname} available, falling back to building from port')

            portdepends = await self._get_port_depends(item.port)
            task_item = _TaskItem(
                PortTask(item.port, do_test=want_testing, build_as_nobody=build_as_nobody),
                [item.consumer]
            )
            tasks[item.pkgname] = task_item
            queue.extend(_QueueItem(port=port, consumer=task_item) for port in portdepends.depends)
            if want_testing:
                # test depends do not intoduce edges for topological sorting
                # in order not to create dependency loops
                queue.extend(_QueueItem(port=port, consumer=None) for port in portdepends.test_depends)
                self._logger.debug(f'planned {item.port} as port, enqueued {len(portdepends.depends)} normal depend(s): {" ".join(map(str, portdepends.depends))} and {len(portdepends.test_depends)} test depend(s): {" ".join(map(str, portdepends.test_depends))}')
            else:
                self._logger.debug(f'planned {item.port} as port, enqueued {len(portdepends.depends)} depend(s): {" ".join(map(str, portdepends.depends))}')

        # topological sort
        topological_sorted: list[_TaskItem] = []

        def toposort(task: _TaskItem, stack: list[_TaskItem]) -> None:
            task.visited = True

            for consumer in task.consumers:
                if consumer is not None and not consumer.visited:
                    toposort(consumer, stack)

            stack.append(task)

        for task in tasks.values():
            if not task.visited:
                toposort(task, topological_sorted)

        plan = Plan()
        for task in reversed(topological_sorted):
            plan.add_task(task.task)
        return plan
