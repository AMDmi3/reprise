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

import asyncio
import logging

from porttester.jail import Jail
from porttester.plan.tasks import Task


class Plan:
    _logger = logging.getLogger('Plan')

    _tasks: list[Task]

    def __init__(self) -> None:
        self._tasks = []

    def add_task(self, task: Task) -> None:
        self._tasks.append(task)

    async def fetch(self, jail: Jail, jobs: int = 1) -> None:
        self._logger.debug('fetch started')
        sem = asyncio.Semaphore(jobs)

        async def wrapper(task: Task) -> None:
            async with sem:
                await task.fetch(jail)

        await asyncio.gather(
            *map(wrapper, self._tasks)
        )

        self._logger.debug('fetch finished')

    async def run(self, jail: Jail, jobs: int = 1) -> None:
        self._logger.debug('main run started')
        sem = asyncio.Semaphore(jobs)

        async def wrapper(task: Task) -> None:
            async with sem:
                await task.run(jail)

        await asyncio.gather(
            *map(wrapper, self._tasks)
        )

        self._logger.debug('main run finished')
