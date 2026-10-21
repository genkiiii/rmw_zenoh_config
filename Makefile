SHELL := /bin/bash
ROLE ?=
RUN_USER ?= $(shell id -un)
SERVER ?= 192.168.1.70
DOMAIN_ID ?= 35
DEVICE ?=

.PHONY: install update uninstall purge status logs check apply-profile
install:
	sudo bash scripts/manage.sh install "$(ROLE)" "$(RUN_USER)" "$(SERVER)" "$(DOMAIN_ID)" "$(DEVICE)"
update:
	sudo bash scripts/manage.sh update
apply-profile:
	sudo bash scripts/manage.sh apply-profile "$(DEVICE)"
uninstall:
	sudo bash scripts/manage.sh uninstall
purge:
	sudo bash scripts/manage.sh purge
status:
	systemctl status rmw-zenoh-router.service
logs:
	journalctl -u rmw-zenoh-router.service -f
check:
	bash -n scripts/manage.sh scripts/start-rmw-zenoh-router scripts/ros-env.sh
	python3 -m unittest discover -s tests -v
