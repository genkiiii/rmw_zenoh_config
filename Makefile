SHELL := /bin/bash
ROLE ?=
RUN_USER ?= $(shell id -un)
SERVER ?= 192.168.1.70
DOMAIN_ID ?= 35

.PHONY: install update uninstall purge status logs check
install:
	sudo bash scripts/manage.sh install "$(ROLE)" "$(RUN_USER)" "$(SERVER)" "$(DOMAIN_ID)"
update:
	sudo bash scripts/manage.sh update
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
