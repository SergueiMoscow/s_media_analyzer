CODE = api alembic/env.py common db repositories schemas services worker tests
TEST = pytest --verbosity=2 --strict-markers ${arg} -k "${k}" --cov-report term-missing --cov-fail-under=80
BLACK = black --line-length 100 --target-version py312 --skip-string-normalization


.PHONY: format
format:
	autoflake $(CODE)
	isort $(CODE)
	${BLACK} $(CODE)
	unify --in-place --recursive $(CODE)

.PHONY: lint
lint:
	flake8 --jobs 4 --statistics --show-source $(CODE)
	pylint --jobs 12 $(CODE)
	${BLACK} --check $(CODE)
	unify --in-place --recursive --check $(CODE)

.PHONY: check
check:
	@echo "\033[1;34m🚀 Check started: $$(date) 🤞\033[0m"
	@start_time=$$(date +%s); \
	make format lint test; \
	end_time=$$(date +%s); \
	elapsed_time=$$(($$end_time - $$start_time)); \
	echo "\033[1;34m✅ Check finished: $$(date)\n⏱️Elapsed Time: $$(($$elapsed_time / 60)) minutes \033[0m"

.PHONY: test
test:
	${TEST} --cov=.
