#!/bin/bash
# Dedicated obdaAI VM only; API/worker use UID 10001 and host networking.
set -euo pipefail
[[ $(hostname -s) = obdaai && $(id -u) = 0 ]] || exit 1
iptables -N OBDAAI_APP 2>/dev/null || true
iptables -F OBDAAI_APP
iptables -A OBDAAI_APP -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OBDAAI_APP -d 127.0.0.1/32 -p tcp -m multiport --dports 5432,8765,11443 -j ACCEPT
iptables -A OBDAAI_APP -j REJECT
iptables -C OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP 2>/dev/null || iptables -A OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP
ip6tables -N OBDAAI_APP 2>/dev/null || true
ip6tables -F OBDAAI_APP
ip6tables -A OBDAAI_APP -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -A OBDAAI_APP -j REJECT
ip6tables -C OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP 2>/dev/null || ip6tables -A OUTPUT -m owner --uid-owner 10001 -j OBDAAI_APP
