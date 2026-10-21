#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo 'Run through make (sudo required).'; exit 1; }
config=/etc/zenoh/rmw_zenoh_config
service=rmw-zenoh-router.service
build_profiles() {
  python3 scripts/merge-profiles.py --directory profiles --device "${1:-}" --devices "${2:-}"
}
apply_profile() {
  [[ "$ROLE" != central ]] || { echo 'Central router does not accept device profiles'; exit 1; }
  local merged
  merged=$(build_profiles "${1:-}" "${2:-}")
  if [[ -f "$config/deny-profile.json" ]]; then
    cp -a "$config/deny-profile.json" "$config/deny-profile.json.bak"
  fi
  local temporary
  temporary=$(mktemp "$config/.profile.XXXXXX")
  printf '%s\n' "$merged" > "$temporary"
  chmod 0644 "$temporary"
  mv "$temporary" "$config/deny-profile.json"
}
case "${1:-}" in
install)
  role=${2:-}; user=${3:-}; server=${4:-}; domain=${5:-}; device=${6:-}; devices=${7:-}
  if [[ "$role" == central ]]; then
    [[ -z "$device$devices" ]] || { echo 'central does not accept DEVICE/DEVICES'; exit 1; }
  else
    build_profiles "$device" "$devices" >/dev/null
  fi
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
  if [[ "$role" != central ]]; then ROLE=$role; apply_profile "$device" "$devices"; fi
  ;;
apply-profile)
  [[ -f "$config/deployment.env" ]] || { echo "Run make install first"; exit 1; }
  source "$config/deployment.env"
  apply_profile "${2:-}" "${3:-}"
  ;;
update)
  [[ -f "$config/deployment.env" ]] || { echo 'Not installed'; exit 1; }
  # Local configuration and ACL are deliberately preserved on update.
  ;;
uninstall|purge)
  systemctl disable --now "$service" 2>/dev/null || true
  rm -f /etc/systemd/system/"$service" /usr/local/bin/start-rmw-zenoh-router
  rm -f /usr/local/lib/rmw_zenoh_config/generate-acl.py /usr/local/lib/rmw_zenoh_config/supervise-router.py
  rmdir /usr/local/lib/rmw_zenoh_config 2>/dev/null || true
  systemctl daemon-reload
  if [[ "$1" == purge ]]; then rm -rf "$config"; fi
  echo 'Service removed. Remove the source line from your .bashrc if no longer needed.'
  exit 0
  ;;
*) echo 'Usage: manage.sh install|update|apply-profile|uninstall|purge'; exit 1 ;;
esac
source "$config/deployment.env"
getent passwd "$RUN_USER" >/dev/null
install -d -m 0755 /usr/local/lib/rmw_zenoh_config
install -m 0644 scripts/generate-acl.py /usr/local/lib/rmw_zenoh_config/generate-acl.py
install -m 0644 scripts/supervise-router.py /usr/local/lib/rmw_zenoh_config/supervise-router.py
install -m 0755 scripts/start-rmw-zenoh-router /usr/local/bin/start-rmw-zenoh-router
install -m 0644 scripts/ros-env.sh "$config/ros-env.sh"
group=$(id -gn "$RUN_USER")
sed -e "s/@USER@/$RUN_USER/g" -e "s/@GROUP@/$group/g" systemd/"$service" > /etc/systemd/system/"$service"
systemctl daemon-reload
systemctl enable "$service"
systemctl restart "$service"
echo 'Check: systemctl status rmw-zenoh-router.service'
