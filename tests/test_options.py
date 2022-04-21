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

import shutil

import pytest

from reprise.commands import MAKE_CMD
from reprise.jobs.generate.options import (generate_options_combinations,
                                           get_port_options_vars)


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
async def test_get_port_options_vars(tmp_path):
    with open(tmp_path / 'Makefile', 'w') as fd:
        fd.write("""
            OPTIONS_DEFINE=O1 O2
            OPTIONS_DEFINE+=O3

            OPTIONS_DEFAULT=O2

            OPTIONS_GROUP=G1 G2
            OPTIONS_GROUP_G1=G11 G12
            OPTIONS_GROUP_G2+=G21 G22

            OPTIONS_SINGLE=S1 S2
            OPTIONS_SINGLE_S1=S11 S12
            OPTIONS_SINGLE_S2+=S21 S22

            OPTIONS_RADIO=R1 R2
            OPTIONS_RADIO_R1=R11 R12
            OPTIONS_RADIO_R2+=R21 R22

            OPTIONS_MULTI=M1 M2
            OPTIONS_MULTI_M1=M11 M12
            OPTIONS_MULTI_M2+=M21 M22
        """)

    assert await get_port_options_vars(tmp_path) == {
        'OPTIONS_DEFINE': {'O1', 'O2', 'O3'},

        'OPTIONS_DEFAULT': {'O2'},

        'OPTIONS_GROUP': {'G1', 'G2'},
        'OPTIONS_GROUP_G1': {'G11', 'G12'},
        'OPTIONS_GROUP_G2': {'G21', 'G22'},

        'OPTIONS_SINGLE': {'S1', 'S2'},
        'OPTIONS_SINGLE_S1': {'S11', 'S12'},
        'OPTIONS_SINGLE_S2': {'S21', 'S22'},

        'OPTIONS_RADIO': {'R1', 'R2'},
        'OPTIONS_RADIO_R1': {'R11', 'R12'},
        'OPTIONS_RADIO_R2': {'R21', 'R22'},

        'OPTIONS_MULTI': {'M1', 'M2'},
        'OPTIONS_MULTI_M1': {'M11', 'M12'},
        'OPTIONS_MULTI_M2': {'M21', 'M22'},
    }


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
async def test_options_combinations_simple(tmp_path):
    with open(tmp_path / 'Makefile', 'w') as fd:
        fd.write("""
            OPTIONS_DEFINE=O1 O2 O3 O4
            OPTIONS_DEFAULT=O2 O4
        """)

    assert list(
        generate_options_combinations(
            await get_port_options_vars(tmp_path),
            include_options=None,
            exclude_options=set(),
        )
    ) == [
        {'O1': True},
        {'O2': False},
        {'O3': True},
        {'O4': False},
    ]
