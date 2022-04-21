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
import logging
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger('Execute')


@dataclass
class _ExecStatistics:
    total_duration: float = 0.0
    calls: int = 0

    @property
    def avg_duration(self) -> float:
        return self.total_duration / self.calls if self.calls else 0.0


_statistics: dict[str, _ExecStatistics] = defaultdict(_ExecStatistics)


def register_execute_time(duration: float) -> None:
    for frame in reversed(traceback.extract_stack()):
        if frame.name not in ['register_execute_time', 'execute', 'execute_by_line']:
            filename = frame.filename.rsplit('reprise/', 1)[-1]
            statistics = _statistics[f'{filename}:{frame.lineno}']
            statistics.total_duration += duration
            statistics.calls += 1
            return


def log_execute_time_statistics() -> None:
    logger = logging.getLogger('ExecuteTiming')

    logger.debug(' TOTAL CALLS    AVG CALLER')
    for pos, stats in sorted(_statistics.items(), key=lambda kv: kv[1].total_duration, reverse=True):
        logger.debug(f'{stats.total_duration:6.2f} {stats.calls:5} {stats.avg_duration:6.2f} {pos}')


async def execute(program: str, *args: str, allow_failure: bool = False, cwd: Path | None = None) -> list[str]:
    _logger.debug(' '.join([program] + list(args)))

    start = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        program, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL if allow_failure else asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    stdout, stderr = await proc.communicate()

    register_execute_time(time.monotonic() - start)

    if proc.returncode != 0:
        if allow_failure:
            return []
        else:
            raise RuntimeError(stdout.decode('utf-8') + stderr.decode('utf-8'))

    return stdout.decode('utf-8').split('\n')[:-1]
