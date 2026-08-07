#!/usr/bin/env bash
# verify-egress.sh — the P1 EXIT-GATE proof (plan 03 §5 / 00 §10 "zero foreign-API egress").
# Three checks: (1) local Ollama reachable from the bus, (2) a foreign API is BLOCKED from a
# container on the bus (negative control), (3) no external SYNs during a live run (manual tcpdump).
# Run AFTER `make up` + `egress-lockdown.sh apply`.
set -uo pipefail
NET="${REDBLUE_NET:-redblue-shared}"
CURL_IMG="curlimages/curl:8.11.1"
FAIL=0

echo "=== [1/3] local Ollama reachable from the bus (must SUCCEED) ==="
if docker run --rm --network "$NET" "$CURL_IMG" -sS --max-time 8 http://ollama:11434/api/tags >/dev/null 2>&1; then
  echo "  ✓ ollama:11434 reachable"
else
  echo "  ✗ ollama NOT reachable — the sovereign brain is down"; FAIL=1
fi

echo "=== [2/3] foreign API BLOCKED from a container (negative control — must FAIL) ==="
for host in https://api.anthropic.com/v1/models https://api.openai.com/v1/models; do
  if docker run --rm --network "$NET" "$CURL_IMG" -sS --max-time 8 "$host" >/dev/null 2>&1; then
    echo "  ✗ EGRESS LEAK — reached $host (run egress-lockdown.sh apply)"; FAIL=1
  else
    echo "  ✓ blocked: $host"
  fi
done

echo "=== [3/3] host-level egress capture (manual) ==="
cat <<'EON'
  Run during a live engagement, on the host, and confirm NO external :443 SYNs:
    sudo tcpdump -ni any 'tcp[tcpflags] & tcp-syn != 0 and dst port 443 and not dst net 10.0.0.0/8 and not dst net 172.16.0.0/12 and not dst net 192.168.0.0/16'
  Expected: silence. Any packet = an egress path to close.
EON

echo
[ "$FAIL" -eq 0 ] && echo "RESULT: ✓ sovereignty checks 1-2 PASS (run check 3 under load)" \
                  || echo "RESULT: ✗ sovereignty NOT proven — see failures above"
exit "$FAIL"
