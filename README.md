# porttester

porttester is a tool primarily designed to test package production
on FreeBSD.

Its goals are to use modern facilities present in FreeBSD (such as
ZFS, jails), to be easy to use and to depend only on base.

Unlike [poudriere](https://github.com/freebsd/poudriere), it's
focused on port testing only, without support for repository
production, and has important features still lacking in poudriere,
such as `make test` support, and more eager use of prebuilt packages.
As a result, with porttester you test your ports, not rebuild llvm
and other heavy dependencies over and over again.

The tool is currently in the proof-of-concept state and is not
yet suitable for general use.

## Author

  - [Dmitry Marakasov](https://github.com/AMDmi3) <amdmi3@amdmi3.ru>

## License

GPLv3 or later, see [COPYING](COPYING).
