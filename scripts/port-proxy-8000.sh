#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-apply}"

IPT="/usr/sbin/iptables"

apply_rule() {
  local chain="$1" match="$2"
  "$IPT" -t nat -C "$chain" $match 2>/dev/null || "$IPT" -t nat -A "$chain" $match
}

remove_rule() {
  local chain="$1" match="$2"
  "$IPT" -t nat -C "$chain" $match 2>/dev/null && "$IPT" -t nat -D "$chain" $match
}

case "$ACTION" in
  apply)
    apply_rule PREROUTING "-p tcp --dport 8000 -j REDIRECT --to-ports 8001"
    apply_rule OUTPUT "-p tcp -d 127.0.0.1 --dport 8000 -j REDIRECT --to-ports 8001"
    ;;
  remove)
    remove_rule PREROUTING "-p tcp --dport 8000 -j REDIRECT --to-ports 8001"
    remove_rule OUTPUT "-p tcp -d 127.0.0.1 --dport 8000 -j REDIRECT --to-ports 8001"
    ;;
  *)
    echo "Usage: $0 [apply|remove]" >&2
    exit 1
    ;;
esac
