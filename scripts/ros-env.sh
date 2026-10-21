# Source this file; do not execute it.
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="$(bash -c 'unset ROS_DOMAIN_ID DOMAIN_ID; source /etc/zenoh/rmw_zenoh_config/deployment.env; printf "%s" "${ROS_DOMAIN_ID:-${DOMAIN_ID:-}}"')"
unset ZENOH_ROUTER_CONFIG_URI ZENOH_SESSION_CONFIG_URI
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_ROUTER_CHECK_ATTEMPTS=0
export ZENOH_CONFIG_OVERRIDE='mode="peer";listen/endpoints=["tcp/127.0.0.1:0"];connect/endpoints=["tcp/127.0.0.1:7447"];scouting/multicast/enabled=false;scouting/gossip/enabled=true;scouting/gossip/multihop=false'
