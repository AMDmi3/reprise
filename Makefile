FLAKE8?=	flake8
MYPY?=		mypy
PYTEST?=	pytest

lint:: test flake8 mypy

test::
	${PYTEST} ${PYTEST_ARGS} -v -rs

flake8:
	${FLAKE8} porttester # tests

mypy:
	${MYPY} porttester # tests
