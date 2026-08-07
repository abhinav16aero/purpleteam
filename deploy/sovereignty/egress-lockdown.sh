#!/usr/bin/env bash
# egress-lockdown.sh — the NETWORK-LEVEL sovereignty backstop (plan 03 §5, P1 exit gate).
# Blocks ALL container egress to the public internet via Docker's DOCKER-USER hook, while
# allowing intra-Docker + RFC1918 + established traffic. Since Ollama runs as a CONTAINER on
# redblue-shared, the entire LLM path stays on the Docker bridge — no external egress is needed.
#
# ⚠ ORDERING (plan 03 §7): run this AFTER images are pulled/built and models are pulled — a lockdown
#   before provisioning would break `docker pull` / `ollama pull` / apt. It is the LAST bring-up step.
# ⚠ ROOT + host-wide: this edits the host iptables. Review before running on a shared box.
#
# Usage:  sudo ./egress-lockdown.sh apply    # install the DROP rules
#         sudo ./egress-lockdown.sh status   # show current DOCKER-USER rules
#         sudo ./egress-lockdown.sh clear     # remove them (restore normal egress)
set -euo pipefail
CHAIN=DOCKER-USER
TAG="redblue-sovereign"

need_root() { [ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }; }

apply() {
  need_root
  clear_rules
  # Order matters: RETURN the allowed traffic first, DROP the rest last.
  iptables -I "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment "$TAG" -j RETURN
  iptables -A "$CHAIN" -d 10.0.0.0/8      -m comment --comment "$TAG" -j RETURN   # RFC1918
  iptables -A "$CHAIN" -d 172.16.0.0/12   -m comment --comment "$TAG" -j RETURN   # docker bridges + RFC1918
  iptables -A "$CHAIN" -d 192.168.0.0/16  -m comment --comment "$TAG" -j RETURN
  iptables -A "$CHAIN" -d 127.0.0.0/8     -m comment --comment "$TAG" -j RETURN
  iptables -A "$CHAIN" -d 169.254.0.0/16  -m comment --comment "$TAG" -j DROP     # block cloud metadata (IMDS)
  iptables -A "$CHAIN" -m comment --comment "$TAG" -j DROP                        # EVERYTHING else (public internet)
  echo "[sovereign] egress locked down — containers can reach only private/intra-docker + Ollama."
  echo "[sovereign] verify with: ./verify-egress.sh"
}

clear_rules() {
  need_root
  # Remove only OUR tagged rules (idempotent; leaves other DOCKER-USER rules intact).
  while iptables -L "$CHAIN" --line-numbers -n 2>/dev/null | grep -q "$TAG"; do
    n=$(iptables -L "$CHAIN" --line-numbers -n | awk -v t="$TAG" '$0 ~ t {print $1; exit}')
    [ -n "${n:-}" ] && iptables -D "$CHAIN" "$n" || break
  done
}

status() { iptables -L "$CHAIN" -n --line-numbers | grep -E "$TAG|Chain" || echo "no $TAG rules installed"; }

case "${1:-}" in
  apply)  apply ;;
  clear)  clear_rules; echo "[sovereign] egress rules cleared" ;;
  status) status ;;
  *) echo "usage: $0 {apply|clear|status}  (run as root)"; exit 2 ;;
esac
