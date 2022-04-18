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

import argparse
import asyncio
import sys
from typing import Any, Collection

import termcolor

from reprise.jail.manager import JailManager
from reprise.jobs import JobSpec
from reprise.jobs.generate import generate_jobs
from reprise.jobs.runner import JobResult, JobRunner, JobStatus
from reprise.logging_ import setup_logging
from reprise.prison import NetworkingIsolationMode
from reprise.workdir import Workdir


async def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    group = parser.add_argument_group('general')

    group.add_argument('-d', '--debug', action='store_true', help='enable debug logging')
    group.add_argument('-n', '--dry-run', action='store_true', help="don't actually build anything")
    group.add_argument('-q', '--quiet', action='store_true', help="don't print summaries")
    group.add_argument('--fail-fast', action='store_true', help='stop processing after the first failure')

    networking_isolation_choices = list(NetworkingIsolationMode.__members__)
    networking_isolation_metavar = '|'.join(NetworkingIsolationMode.__members__)
    group.add_argument(
        '--networking-isolation-build',
        type=str,
        default='DISABLED',
        choices=networking_isolation_choices,
        metavar=networking_isolation_metavar,
        help='network isolation mode for port building'
    )
    group.add_argument(
        '--networking-isolation-test',
        type=str,
        # XXX: should probably change to UNRESTRICTED when we support build-as-user,
        # as a lot of tests involve arbitrary networking operations
        default='RESTRICTED',
        choices=networking_isolation_choices,
        metavar=networking_isolation_metavar,
        help='network isolation mode for port testing'
    )

    group = parser.add_argument_group('job specification')
    group.add_argument('-p', '--portsdir', metavar='PATH', type=str, help='ports tree directory to use in jails')
    group.add_argument('--distdir', metavar='PATH', type=str, help='distfiles directory tree to use in jails (default: autodetect)')

    group.add_argument('-r', '--rebuild', metavar='PORT', nargs='*', default=[], help='port origin(s) to rebuild from ports')
    group.add_argument('-f', '--file', type=str, help='path to file with port origin(s) to test (- to read from stdin)')
    group.add_argument('-V', '--vars', metavar='KEY=VALUE', nargs='+', default=[], type=str, help='port variables to set for the build')
    group.add_argument('-O', '--options', action='store_true', help='test port options combinations')
    group.add_argument('--include-options', type=str, nargs='+', help='options to only use with -O')
    group.add_argument('--exclude-options', type=str, nargs='+', help='options to exclude from -O')
    group.add_argument('--exclude-default-options', action='store_true', help="don't build default options with -O")
    group.add_argument('-j', '--jails', type=str, nargs='*', help='jails to test the port in')
    group.add_argument('-T', '--no-test', action='store_true', help='skip testing')
    group.add_argument('--build-as-root', action='store_true', help='do not drop privileges for building and testing')
    group.add_argument('ports', metavar='PORT', nargs='*', default=[], help='port origin(s) to test')

    args = parser.parse_args()

    return args


def not_colored(message: str, *args: Any, **kwargs: Any) -> str:
    return message


def print_summary(specs: Collection[JobSpec]) -> None:
    print('Job summary:', file=sys.stderr)
    for spec in specs:
        print(f' * {spec}', file=sys.stderr)
    print(f'{len(specs)} job(s) total', file=sys.stderr)


def print_results(results: Collection[JobResult]) -> None:
    colored = termcolor.colored if sys.stdout.isatty() else not_colored

    num_successes = 0

    print('Job results:')
    for result in results:
        # here and below, a bunch of bogus `Cannot call function of unknown type` errors
        if result.status == JobStatus.SUCCESS:
            status = colored('     SUCCESS', 'green')  # type: ignore
            num_successes += 1
        elif result.status == JobStatus.FETCH_FAILED:
            status = colored('FETCH FAILED', 'red')  # type: ignore
        elif result.status == JobStatus.BUILD_FAILED:
            status = colored('BUILD FAILED', 'red')  # type: ignore
        elif result.status == JobStatus.TEST_FAILED:
            status = colored(' TEST FAILED', 'yellow')  # type: ignore
        elif result.status == JobStatus.CRASHED:
            status = colored('     CRASHED', 'magenta')  # type: ignore
        else:
            status = colored('     UNKNOWN', 'magenta')  # type: ignore

        log_message = ', log: ' + colored(str(result.log_path), 'cyan') if result.log_path else ''  # type: ignore
        print(f'{status} {result.spec}{log_message}')

    success = num_successes == len(results)

    print(colored(f'{num_successes}/{len(results)}', 'green' if success else 'red'), 'successful jobs')  # type: ignore


async def amain() -> None:
    args = await parse_arguments()

    setup_logging(args.debug)

    jail_manager = JailManager()

    jobspecs = [job async for job in generate_jobs(args, jail_manager)]

    if not jobspecs:
        print('nothing to do')
        sys.exit(1)

    if not args.quiet:
        print_summary(jobspecs)

    if args.dry_run:
        sys.exit(0)

    workdir = await Workdir.initialize()
    runner = JobRunner(workdir=workdir)

    results = [await runner.run(spec) for spec in jobspecs]

    if not args.quiet:
        print_results(results)

    success = all(result.status == JobStatus.SUCCESS for result in results)

    sys.exit(0 if success else 1)


def main() -> None:
    asyncio.run(amain())


if __name__ == '__main__':
    main()
