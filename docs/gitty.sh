#!/data/data/com.termux/files/usr/bin/bash
# Gitty - GitHub Manager for Termux (TUI) v2.2
# gitty-patch-id: p5-fullbody-order-1to10

DEBUG="${DEBUG:-false}"
set -eo pipefail
if [[ "$DEBUG" == true ]]; then set -x; fi
