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

import logging
import os
from pathlib import Path
from typing import Iterator

import yaml
from pydantic import BaseModel, Field

_logger = logging.getLogger('Config')


class JailSpecification(BaseModel):
    version: str
    arch: str
    tags: list[str] = Field(default_factory=list)


class Config(BaseModel):
    jails: dict[str, JailSpecification] = Field(default_factory=dict)


def _generate_config_paths() -> Iterator[Path]:
    reprise_conf = Path('reprise/reprise.conf')

    if (xdg_config_home := os.getenv('XDG_CONFIG_HOME')) is not None:
        yield Path(xdg_config_home) / reprise_conf

    if (home := os.getenv('HOME')) is not None:
        yield Path(home) / '.config' / reprise_conf

    etcdir = '%%ETCDIR%%'  # optionally replaced by the port
    if not etcdir.startswith('%'):
        yield Path(etcdir) / reprise_conf


def _find_config() -> Path | None:
    return next(filter(Path.exists, _generate_config_paths()), None)  # type: ignore  # https://github.com/python/mypy/issues/12682


def load_config(path: Path | None) -> Config:
    if path is None:
        for candidate in _generate_config_paths():
            _logger.debug(f'looking for config in {candidate}')
            if candidate.exists():
                path = candidate
                break

    if path is None:
        return Config()

    with open(path) as f:
        _logger.debug(f'loading config from {path}')
        yaml_config = yaml.safe_load(f)
        if yaml_config is None:
            return Config()
        elif not isinstance(yaml_config, dict):
            raise ValueError('config must be a dictionary')
        return Config(**yaml_config)
