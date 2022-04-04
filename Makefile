FLAKE8?=	flake8
MYPY?=		mypy
PYTEST?=	pytest
ISORT?=		isort

lint:: test flake8 mypy isort-check

test::
	${PYTEST} ${PYTEST_ARGS} -v -rs

flake8:
	${FLAKE8} porttester # tests

mypy:
	${MYPY} porttester # tests

isort-check::
	${ISORT} ${ISORT_ARGS} --check $$(find . -name "*.py")

isort::
	${ISORT} ${ISORT_ARGS} $$(find . -name "*.py")
