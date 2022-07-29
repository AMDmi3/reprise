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

from typing import Iterable

from reprise.jail import JailSpec
from reprise.jail.manager import JailManager


def _get_names(specs: Iterable[JailSpec]) -> list[str]:
    return [spec.name for spec in specs]


async def test_tags():
    jail_manager = JailManager()

    jail_manager.register_jail('13-amd64', '13.0', 'amd64', ['13', 'amd64', 'default', 'main'])
    jail_manager.register_jail('13-i386', '13.0', 'i386', ['13', 'i386', 'default'])
    jail_manager.register_jail('12-amd64', '12.0', 'amd64', ['12', 'amd64', 'default'])
    jail_manager.register_jail('12-i386', '12.0', 'i386', ['12', 'i386', 'default'])
    jail_manager.register_jail('nondefault', '13.0', 'amd64', [])

    jail_manager.finalize_tags()

    assert _get_names(
        jail_manager.get_specs(['all'])
    ) == ['13-amd64', '13-i386', '12-amd64', '12-i386', 'nondefault']

    assert _get_names(
        jail_manager.get_specs(['default'])
    ) == ['13-amd64', '13-i386', '12-amd64', '12-i386']

    assert _get_names(
        jail_manager.get_specs(['main'])
    ) == ['13-amd64']

    assert _get_names(
        jail_manager.get_specs(['13'])
    ) == ['13-amd64', '13-i386']

    assert _get_names(
        jail_manager.get_specs(['12'])
    ) == ['12-amd64', '12-i386']

    assert _get_names(
        jail_manager.get_specs(['amd64'])
    ) == ['13-amd64', '12-amd64']

    assert _get_names(
        jail_manager.get_specs(['i386'])
    ) == ['13-i386', '12-i386']

    # by individual jail name
    assert _get_names(
        jail_manager.get_specs(['13-amd64'])
    ) == ['13-amd64']

    assert _get_names(
        jail_manager.get_specs(['nondefault'])
    ) == ['nondefault']

    # nonexisting
    assert _get_names(
        jail_manager.get_specs(['nonexisting'])
    ) == []

    # no duplication allowed
    assert _get_names(
        jail_manager.get_specs(['all', '13-amd64', '13', '12', 'amd64', 'i386'])
    ) == ['13-amd64', '13-i386', '12-amd64', '12-i386', 'nondefault']


async def test_tags_default():
    jail_manager = JailManager()

    jail_manager.register_jail('13-amd64', '13.0', 'amd64', ['13', 'amd64' 'main'])
    jail_manager.register_jail('13-i386', '13.0', 'i386', ['13', 'i386'])
    jail_manager.register_jail('12-amd64', '12.0', 'amd64', ['12', 'amd64'])
    jail_manager.register_jail('12-i386', '12.0', 'i386', ['12', 'i386'])

    jail_manager.finalize_tags()

    # when no jail explicitly defines default tag, it's implicitly
    # added to all jails
    assert _get_names(
        jail_manager.get_specs(['default'])
    ) == ['13-amd64', '13-i386', '12-amd64', '12-i386']
