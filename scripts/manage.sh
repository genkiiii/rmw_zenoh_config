#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo 'Run through make (sudo required).'; exit 1; }
config=/etc/zenoh/rmw_zenoh_config
service=rmw-zenoh-router.service
read_local_env() {
  [[ -f config/deployment.env ]] || { echo 'Missing config/deployment.env. Restore the distributed file and edit SERVER/ROS_DOMAIN_ID.' >&2; exit 1; }
  local validated
  validated=$(python3 scripts/read-deployment.py config/deployment.env)
  # Only validated, shell-quoted assignments from our parser are evaluated.
  eval "$validated"
}
write_runtime_env() {
  local temporary
  temporary=$(mktemp "$config/.deployment.XXXXXX")
  printf 'ROLE=%q\nRUN_USER=%q\nSERVER=%q\nROS_DOMAIN_ID=%q\n' "$ROLE" "$RUN_USER" "$SERVER" "$ROS_DOMAIN_ID" > "$temporary"
  chmod 0644 "$temporary"
  if [[ -f "$config/deployment.env" ]]; then
    cp -a "$config/deployment.env" "$config/deployment.env.bak"
  fi
  mv "$temporary" "$config/deployment.env"
}
build_profiles() {
  python3 scripts/merge-profiles.py --directory profiles --device "${1:-}" --devices "${2:-}"
}
prepare_profile() {
  [[ "$ROLE" != central ]] || { echo 'Central router does not accept device profiles'; exit 1; }
  # Validate the whole selection before modifying installed files.
  merged_profile=$(build_profiles "${1:-}" "${2:-}")
  selected_profiles=${1:-${2:-}}
}
write_profile() {
  if [[ -f "$config/deny-profile.json" ]]; then
    cp -a "$config/deny-profile.json" "$config/deny-profile.json.bak"
  fi
  local temporary
  temporary=$(mktemp "$config/.profile.XXXXXX")
  printf '%s\n' "$merged_profile" > "$temporary"
  chmod 0644 "$temporary"
  mv "$temporary" "$config/deny-profile.json"
  temporary=$(mktemp "$config/.selection.XXXXXX")
  printf '%s\n' "$selected_profiles" > "$temporary"
  chmod 0644 "$temporary"
  mv "$temporary" "$config/selected-profiles"
}
case "${1:-}" in
install)
  ROLE=${2:-}; RUN_USER=${3:-}; device=${4:-}; devices=${5:-}
  [[ "$ROLE" =~ ^(central|vehicle|control)$ ]] || { echo 'ROLE=central|vehicle|control is required at install' >&2; exit 1; }
  read_local_env
  if [[ "$ROLE" == central ]]; then
    [[ -z "$device$devices" ]] || { echo 'central does not accept DEVICE/DEVICES'; exit 1; }
  else
    prepare_profile "$device" "$devices"
  fi
  if [[ ! "$RUN_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || ! id "$RUN_USER" >/dev/null 2>&1; then
    echo 'Specify an existing Linux RUN_USER' >&2
    exit 1
  fi
  [[ "$RUN_USER" != root ]] || { echo 'Specify non-root RUN_USER'; exit 1; }
  [[ ! -f "$config/deployment.env" ]] || { echo 'Already installed: use make update; edit deployment.env to change deployment.'; exit 1; }
  [[ -f /opt/ros/humble/setup.bash ]]
  # Resolve shipped configuration from the installed ROS package.
  default=$(bash -c 'source /opt/ros/humble/setup.bash; ros2 pkg prefix --share rmw_zenoh_cpp')/config/DEFAULT_RMW_ZENOH_ROUTER_CONFIG.json5
  [[ -f "$default" ]]
  install -d -m 0755 "$config"
  install -m 0644 "$default" "$config/router.json5"
  write_runtime_env
  if [[ "$ROLE" != central ]]; then write_profile; fi
  ;;
update)
  [[ -f "$config/deployment.env" ]] || { echo 'Not installed'; exit 1; }
  source "$config/deployment.env"
  installed_user=$RUN_USER
  read_local_env
  RUN_USER=$installed_user
  getent passwd "$RUN_USER" >/dev/null
  if [[ "$ROLE" == central ]]; then
    [[ -z "${2:-}${3:-}" ]] || { echo 'central does not accept DEVICE/DEVICES'; exit 1; }
  elif [[ -n "${2:-}${3:-}" ]]; then
    prepare_profile "${2:-}" "${3:-}"
  elif [[ -s "$config/selected-profiles" ]]; then
    prepare_profile "$(cat "$config/selected-profiles")" ""
  else
    echo 'No saved profile selection. Run make update DEVICE="<profile>" once (control PC: DEVICE="control").' >&2
    exit 1
  fi
  write_runtime_env
  if [[ "$ROLE" != central ]]; then write_profile; fi
  # router.json5 is preserved; env, selected profile and code are reapplied.
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
*) echo 'Usage: manage.sh install|update|uninstall|purge'; exit 1 ;;
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
