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
import time


def _format_seconds(secs: float) -> str:
    seconds = int(secs) % 60
    minutes = int(secs) // 60 % 60
    hour = int(secs) // 3600
    return f'{hour:02}:{minutes:02}:{seconds:02}'


class ElapsedFormatter(logging.Formatter):
    _start_time: float

    def __init__(self) -> None:
        self._start_time = time.time()

    def format(self, record: logging.LogRecord) -> str:  # noqa
        elapsed = _format_seconds(record.created - self._start_time)
        return f'[{elapsed}] {record.getMessage()}'


class DebugElapsedFormatter(ElapsedFormatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa
        elapsed = _format_seconds(record.created - self._start_time)
        return f'[{elapsed}] {record.name:8} {record.getMessage()}'


def setup_logging(debug: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(DebugElapsedFormatter() if debug else ElapsedFormatter())
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)
