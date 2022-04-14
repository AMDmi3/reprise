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
import logging
from typing import TextIO

from reprise.plan.tasks import Task
from reprise.prison import Prison


class Plan:
    _logger = logging.getLogger('Plan')

    _tasks: list[Task]

    def __init__(self) -> None:
        self._tasks = []

    def add_task(self, task: Task) -> None:
        self._tasks.append(task)

    async def fetch(self, jail: Prison, log: TextIO, jobs: int = 1, fail_fast: bool = False) -> bool:
        self._logger.debug('fetch started')
        sem = asyncio.Semaphore(jobs)
        success = True

        async def wrapper(task: Task) -> None:
            nonlocal success, sem, fail_fast
            if not fail_fast or success:
                async with sem:
                    success = await task.fetch(jail, log) and success

        await asyncio.gather(*map(wrapper, self._tasks))

        self._logger.debug(f'fetch {"succeeded" if success else "failed"}')

        return success

    async def install(self, jail: Prison, log: TextIO, fail_fast: bool = False) -> bool:
        self._logger.debug('install started')

        # no parallelization(
        success = True
        for task in self._tasks:
            if not fail_fast or success:
                success = await task.install(jail, log) and success

        self._logger.debug(f'install {"succeeded" if success else "failed"}')

        return success

    async def test(self, jail: Prison, log: TextIO, jobs: int = 1, fail_fast: bool = False) -> bool:
        self._logger.debug('testing started')
        sem = asyncio.Semaphore(jobs)
        success = True

        async def wrapper(task: Task) -> None:
            nonlocal success, sem, fail_fast
            if not fail_fast or success:
                async with sem:
                    success = await task.test(jail, log) and success

        await asyncio.gather(*map(wrapper, self._tasks))

        self._logger.debug(f'testing {"succeeded" if success else "failed"}')

        return success
