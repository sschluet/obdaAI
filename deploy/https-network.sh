#!/bin/bash
# Dedicated VM only. Restrict reviewed private clients and proxy egress.
set -euo pipefail
[[ $(hostname -s) = obdaai && $(id -u) = 0 ]] || exit 1
. /etc/obdaai/https-network.env
read -r -a clients <<< "$HUB_HTTPS_CLIENT_CIDRS"
python3 - "$HUB_HTTPS_BIND_IP" "${clients[@]}" <<'CHECK'
import ipaddress, sys
private = [ipaddress.ip_network(x) for x in ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']]
assert 2 <= len(sys.argv) - 1 <= 9
address = ipaddress.ip_address(sys.argv[1])
assert any(address in net for net in private)
for value in sys.argv[2:]:
    network = ipaddress.ip_network(value)
    assert any(network.subnet_of(net) for net in private)
CHECK
iptables -N OBDAAI_HTTPS 2>/dev/null || true
iptables -F OBDAAI_HTTPS
for client in "${clients[@]}"; do iptables -A OBDAAI_HTTPS -s "$client" -j ACCEPT; done
iptables -A OBDAAI_HTTPS -j REJECT
iptables -C INPUT -d "$HUB_HTTPS_BIND_IP" -p tcp --dport 443 -j OBDAAI_HTTPS 2>/dev/null || iptables -I INPUT 1 -d "$HUB_HTTPS_BIND_IP" -p tcp --dport 443 -j OBDAAI_HTTPS
proxy_uid=$(id -u www-data)
iptables -N OBDAAI_PROXY 2>/dev/null || true
iptables -F OBDAAI_PROXY
iptables -A OBDAAI_PROXY -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OBDAAI_PROXY -d 127.0.0.1/32 -p tcp --dport 8766 -j ACCEPT
iptables -A OBDAAI_PROXY -j REJECT
iptables -C OUTPUT -m owner --uid-owner "$proxy_uid" -j OBDAAI_PROXY 2>/dev/null || iptables -A OUTPUT -m owner --uid-owner "$proxy_uid" -j OBDAAI_PROXY
ip6tables -N OBDAAI_PROXY 2>/dev/null || true
ip6tables -F OBDAAI_PROXY
ip6tables -A OBDAAI_PROXY -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -A OBDAAI_PROXY -j REJECT
ip6tables -C OUTPUT -m owner --uid-owner "$proxy_uid" -j OBDAAI_PROXY 2>/dev/null || ip6tables -A OUTPUT -m owner --uid-owner "$proxy_uid" -j OBDAAI_PROXY
