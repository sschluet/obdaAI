#!/bin/bash
# Dedicated VM only. External access requires a separate operator marker.
set -euo pipefail
[[ $(hostname -s) = obdaai && $(id -u) = 0 ]] || exit 1
cloud_ips=()
if [[ -f /etc/obdaai/openrouter-egress.enabled ]]; then
  mapfile -t cloud_ips < <(python3 - <<'PY'
import ipaddress,socket
values=sorted({v[4][0] for v in socket.getaddrinfo('openrouter.ai',443,family=socket.AF_INET,type=socket.SOCK_STREAM)})
if values and all(ipaddress.ip_address(v).is_global for v in values):
 for value in values:print(value)
PY
)
  ((${#cloud_ips[@]} > 0)) || { echo 'OpenRouter resolution failed; existing rules retained'; exit 1; }
fi
iptables -N OBDAAI_APP 2>/dev/null || true
iptables -F OBDAAI_APP
iptables -A OBDAAI_APP -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OBDAAI_APP -d 127.0.0.1/32 -p tcp -m multiport --dports 5432,8765,8766,11444 -j ACCEPT
if ((${#cloud_ips[@]} > 0)); then
  # The existing host resolver is the only DNS destination for the app UID.
  for proto in udp tcp; do
    iptables -A OBDAAI_APP -d 127.0.0.53/32 -p "$proto" --dport 53 -j ACCEPT
  done
  for ip in "${cloud_ips[@]}"; do
    iptables -A OBDAAI_APP -d "$ip/32" -p tcp --dport 443 -j ACCEPT
  done
fi
iptables -A OBDAAI_APP -j REJECT
iptables -C OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP 2>/dev/null || iptables -A OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP
ip6tables -N OBDAAI_APP 2>/dev/null || true
ip6tables -F OBDAAI_APP
ip6tables -A OBDAAI_APP -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -A OBDAAI_APP -j REJECT
ip6tables -C OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP 2>/dev/null || ip6tables -A OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP
