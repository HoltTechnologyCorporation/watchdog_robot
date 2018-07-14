.PHONY: build build_dev venv venv_dev clean

build: venv init

build_dev: venv_dev init

venv:
	pipenv --three lock
	pipenv --three sync

venv_dev:
	pipenv --three lock
	pipenv --three sync
	pipenv --three --dev install
	
clean:
	find -name '*.pyc' -delete
	find -name '*.swp' -delete
	find -name '__pycache__' -delete

init:
	if [ ! -e var/run ]; then mkdir -p var/run; fi
	if [ ! -e var/log ]; then mkdir -p var/log; fi
