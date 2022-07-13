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
from typing import TextIO

from reprise.plan.tasks import Task, TaskStatus
from reprise.prison import Prison


class Plan:
    _logger = logging.getLogger('Plan')

    _tasks: list[Task]

    def __init__(self) -> None:
        self._tasks = []

    def add_task(self, task: Task) -> None:
        self._tasks.append(task)

    async def fetch(self, jail: Prison, log: TextIO) -> TaskStatus:
        self._logger.debug('fetch started')

        status = TaskStatus.SUCCESS

        for task in self._tasks:
            if status == TaskStatus.SUCCESS:
                status = await task.fetch(jail, log)

        self._logger.debug(f'fetch finished: {status.name}')

        return status

    async def install(self, jail: Prison, log: TextIO) -> TaskStatus:
        self._logger.debug('install started')

        status = TaskStatus.SUCCESS

        for task in self._tasks:
            if status == TaskStatus.SUCCESS:
                status = await task.install(jail, log)

        self._logger.debug(f'install finished: {status.name}')

        return status

    async def test(self, jail: Prison, log: TextIO, jobs: int = 1) -> TaskStatus:
        self._logger.debug('testing started')

        status = TaskStatus.SUCCESS

        for task in self._tasks:
            if status == TaskStatus.SUCCESS:
                status = await task.test(jail, log)

        self._logger.debug(f'testing finished: {status.name}')

        return status
