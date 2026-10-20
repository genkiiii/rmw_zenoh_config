#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo 'Run through make (sudo required).'; exit 1; }
config=/etc/zenoh/rmw_zenoh_config
service=rmw-zenoh-router.service
case "${1:-}" in
install)
  role=${2:-}; user=${3:-}; server=${4:-}; domain=${5:-}
  [[ "$role" =~ ^(central|vehicle|control)$ ]] || { echo 'ROLE=central|vehicle|control is required'; exit 1; }
  [[ "$user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] && id "$user" >/dev/null
  [[ "$server" =~ ^[a-zA-Z0-9.-]+$ ]] && [[ "$domain" =~ ^[0-9]+$ ]]
  [[ "$user" != root ]] || { echo 'Specify non-root RUN_USER'; exit 1; }
  [[ ! -f "$config/deployment.env" ]] || { echo 'Already installed: use make update; edit deployment.env to change deployment.'; exit 1; }
  [[ -f /opt/ros/humble/setup.bash ]]
  # Resolve shipped configuration from the installed ROS package.
  default=$(bash -c 'source /opt/ros/humble/setup.bash; ros2 pkg prefix --share rmw_zenoh_cpp')/config/DEFAULT_RMW_ZENOH_ROUTER_CONFIG.json5
  [[ -f "$default" ]]
  install -d -m 0755 "$config"
  install -m 0644 "$default" "$config/router.json5"
  printf 'ROLE=%q\nRUN_USER=%q\nSERVER=%q\nDOMAIN_ID=%q\n' "$role" "$user" "$server" "$domain" > "$config/deployment.env"
  ;;
update)
  [[ -f "$config/deployment.env" ]] || { echo 'Not installed'; exit 1; }
  # Local configuration and ACL are deliberately preserved on update.
  ;;
uninstall|purge)
  systemctl disable --now "$service" 2>/dev/null || true
  rm -f /etc/systemd/system/"$service" /usr/local/bin/start-rmw-zenoh-router
  systemctl daemon-reload
  if [[ "$1" == purge ]]; then rm -rf "$config"; fi
  echo 'Service removed. Remove the source line from your .bashrc if no longer needed.'
  exit 0
  ;;
*) echo 'Usage: manage.sh install|update|uninstall|purge'; exit 1 ;;
esac
source "$config/deployment.env"
getent passwd "$RUN_USER" >/dev/null
install -m 0755 scripts/start-rmw-zenoh-router /usr/local/bin/start-rmw-zenoh-router
install -m 0644 scripts/ros-env.sh "$config/ros-env.sh"
group=$(id -gn "$RUN_USER")
sed -e "s/@USER@/$RUN_USER/g" -e "s/@GROUP@/$group/g" systemd/"$service" > /etc/systemd/system/"$service"
systemctl daemon-reload
systemctl enable "$service"
systemctl restart "$service"
echo 'Check: systemctl status rmw-zenoh-router.service'
