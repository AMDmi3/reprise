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
import datetime
import sys
from typing import Any, Collection

import termcolor

from reprise.config import load_config
from reprise.execute import log_execute_time_statistics
from reprise.jail.manager import JailManager
from reprise.jobs import JobSpec, PackageCompressionMode
from reprise.jobs.generate import generate_jobs
from reprise.jobs.runner import JobResult, JobRunner, JobStatus
from reprise.logging_ import setup_logging
from reprise.prison import NetworkingMode
from reprise.repository import RepositoryManager, RepositoryUpdateMode
from reprise.workdir import Workdir


async def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=78),
        description='Build and test FreeBSD ports in a clean environment.',
        add_help=False
    )

    group = parser.add_argument_group('General')
    group.add_argument('-d', '--debug', action='store_true', help='Enable debug logging')
    group.add_argument('-n', '--dry-run', action='store_true', help="Don't actually build anything")
    group.add_argument('-q', '--quiet', action='store_true', help="Don't print summaries")
    group.add_argument('-h', '--help', action='help', help='Show this help message and exit')
    group.add_argument('-c', '--config', type=str, help='Specify config file to use')
    group.add_argument('--fail-fast', action='store_true', help='Stop processing on the first failure')

    group = parser.add_argument_group(
        'Specifying ports to build',
        """
        Running %(prog)s in a port directory without any ports
        explicitly specified will build the port from that directory.
        """
    )
    group.add_argument('-p', '--portsdir', metavar='PATH', type=str, help='Ports tree to use (default: /usr/ports)')
    group.add_argument('--distdir', metavar='PATH', type=str, help='Distfiles directory to use (default: autodetected)')

    group.add_argument('-r', '--rebuild', metavar='PORT', nargs='*', default=[], help='Port origin(s) to rebuild from ports')
    group.add_argument('-f', '--file', type=str, help='Path to file with port origin(s) to test (- to read from stdin)')
    group.add_argument('ports', metavar='PORT', nargs='*', default=[], help='Ports (in category/port format) to test')

    group = parser.add_argument_group('Controlling the port behavior')
    group.add_argument('-V', '--vars', metavar='KEY=VALUE', nargs='+', default=[], type=str, help='Variables to set for the build via make.conf')

    group = parser.add_argument_group(
        'Build jobs generation',
        """
        By default, a single build job is ran in a `default` jail
        and with the default options. You may enable builds in
        multiple jails and with different options combinations.
        """
    )
    group.add_argument('-O', '--options', action='store_true', help='Generate multiple port options combinations')
    group.add_argument('--include-options', type=str, nargs='+', metavar='OPTION', help='Options to only use when generating combinations')
    group.add_argument('--exclude-options', type=str, nargs='+', metavar='OPTION', help='Options to exclude from generating combinations')
    group.add_argument('--exclude-default-options', action='store_true', help="Don't include default options combination")
    group.add_argument('-j', '--jails', type=str, nargs='*', metavar='JAIL', help='Jails to test the port in')

    group = parser.add_argument_group('Build environment tuning')

    networking_choices = list(NetworkingMode.__members__)
    group.add_argument(
        '--networking-build',
        type=str, default='DISABLED', choices=networking_choices,
        help='Network isolation mode for port building'
    )
    # XXX: should probably change to UNRESTRICTED when we support build-as-user,
    # as a lot of tests involve arbitrary networking operations
    group.add_argument(
        '--networking-test',
        type=str, default='RESTRICTED', choices=networking_choices,
        help='Network isolation mode for port testing'
    )

    group.add_argument('--build-as-root', action='store_true', help='Do not drop privileges for building and testing')
    group.add_argument('--no-ccache', action='store_true', help='Do not use ccache')
    group.add_argument('--no-test', action='store_true', help='Skip testing')
    group.add_argument(
        '--package-compression',
        type=str, default='NONE', choices=list(PackageCompressionMode.__members__),
        help='Package compression mode (note that DEFAULT setting refers to pkg default, not reprise default) (default: NONE)',
    )
    group.add_argument('--tmpfs-work', action='store_true', help='Use tmpfs for WRKDIR directory')
    group.add_argument('--tmpfs-localbase', action='store_true', help='Use tmpfs for LOCALBASE directory')
    group.add_argument('--tmpfs-limit-mb', type=int, metavar='MiB', default=0, help='Max allowed tmpfs size (for each enabled tmpfs) in mebibytes (default: no limit)')
    group.add_argument('--timeout-fetch', type=int, metavar='SECONDS', default=0, help='Timeout for fetching, 0 for no timeout (default: 3600)')
    group.add_argument('--timeout-build', type=int, metavar='SECONDS', default=0, help='Timeout for building, 0 for no timeout (default: 7200)')
    group.add_argument('--timeout-test', type=int, metavar='SECONDS', default=0, help='Timeout for testing, 0 for no timeout (default: 7200)')
    group.add_argument('-i', '--interactive', action='store_true', help='Pause before cleaning up the build directory to allow manual interaction with it')

    group = parser.add_argument_group(
        'Remote repository handling',
        """
        Updating remote repository is mandatory on the first run
        of any jail. After that, %(prog)s checks for repository update
        on each build, and updates the repository only if it has
        changed. You may chose to disable or force the update.
        """
    )
    group.add_argument('-U', '--no-repo-update', action='store_true', help='Do not update repository metadata')
    group.add_argument('-u', '--force-repo-update', action='store_true', help='Force repository metadata update')

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

    num_attempts = 0
    num_successes = 0

    print('Job results:')
    for result in results:
        num_attempts += 1
        # here and below, a bunch of bogus `Cannot call function of unknown type` errors
        if result.status == JobStatus.SUCCESS:
            status = colored('SUCCESS', 'green')  # type: ignore
            num_successes += 1
        elif result.status == JobStatus.FETCH_FAILED:
            status = colored('FETFAIL', 'red')  # type: ignore
        elif result.status == JobStatus.BUILD_FAILED:
            status = colored('BLDFAIL', 'red')  # type: ignore
        elif result.status == JobStatus.TEST_FAILED:
            status = colored('TSTFAIL', 'red')  # type: ignore
        elif result.status == JobStatus.FETCH_TIMEOUT:
            status = colored('TIMEOUT', 'blue')  # type: ignore
        elif result.status == JobStatus.BUILD_TIMEOUT:
            status = colored('TIMEOUT', 'blue')  # type: ignore
        elif result.status == JobStatus.TEST_TIMEOUT:
            status = colored('TIMEOUT', 'blue')  # type: ignore
        elif result.status == JobStatus.CRASHED:
            status = colored('CRASHED', 'red')  # type: ignore
        elif result.status == JobStatus.SKIPPED:
            num_attempts -= 1
            status = colored('SKIPPED', 'magenta')  # type: ignore
        else:
            raise RuntimeError(f'unexpected job status {result.status}')

        log_message = ', log: ' + colored(str(result.log_path), 'cyan') if result.log_path else ''  # type: ignore
        print(f'{status} {result.spec}{log_message}')

        if result.details:
            print('        * ' + colored(result.details, 'cyan'))  # type: ignore

    success = num_successes == num_attempts

    print(colored(f'{num_successes}/{num_attempts}', 'green' if success else 'red'), 'successful jobs')  # type: ignore


async def amain() -> None:
    args = await parse_arguments()

    setup_logging(args.debug)

    config = load_config(args.config)

    jail_manager = JailManager()

    if config.jails:
        for jail_name, jail_spec in config.jails.items():
            jail_manager.register_jail(name=jail_name, **jail_spec.dict())
    else:
        jail_manager.register_host_jail()

    jail_manager.finalize_tags()

    jobspecs = [job async for job in generate_jobs(args, jail_manager)]

    if not jobspecs:
        print('nothing to do')
        sys.exit(1)

    if not args.quiet:
        print_summary(jobspecs)

    if args.dry_run:
        sys.exit(0)

    workdir = await Workdir.initialize()

    repository_manager = RepositoryManager(
        workdir,
        update_mode=RepositoryUpdateMode.DISABLE if args.no_repo_update else RepositoryUpdateMode.FORCE if args.force_repo_update else RepositoryUpdateMode.AUTO,
        update_period=datetime.timedelta(hours=6),  # XXX: optionize
    )

    runner = JobRunner(workdir=workdir, repository_manager=repository_manager)

    results = []

    for spec in jobspecs:
        result = await runner.run(spec)
        results.append(result)
        if args.fail_fast and not result.is_ok():
            break

    if not args.quiet:
        print_results(results)

    log_execute_time_statistics()

    success = all(result.status == JobStatus.SUCCESS for result in results)

    sys.exit(0 if success else 1)


def main() -> None:
    asyncio.run(amain())


if __name__ == '__main__':
    main()
