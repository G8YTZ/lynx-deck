#!/bin/bash
# Lynx Deck: SNMP monitoring, the same arrangement as Lynx-Tx's.
# snmpd serves the lynxDeck branch of mibs/LYNX-MIB.txt through
# tools/lynx-deck-snmp-agent.py, which reads the Deck's /api/health.
# Read-only, community "lynx". Safe to run again; install.sh runs it.
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y snmpd >/dev/null
sudo install -D -m 755 "$APP_DIR/tools/lynx-deck-snmp-agent.py" /usr/local/lib/lynx-deck/lynx-deck-snmp-agent.py
sudo install -D -m 644 "$APP_DIR/mibs/LYNX-MIB.txt" /usr/share/snmp/mibs/LYNX-MIB.txt
# Debian's snmpd answers only the Pi itself: open it to the network.
sudo sed -i 's/^agentaddress .*/agentaddress udp:161,udp6:[::1]:161/' /etc/snmp/snmpd.conf
sudo mkdir -p /etc/snmp/snmpd.conf.d
sudo tee /etc/snmp/snmpd.conf.d/lynx-deck.conf >/dev/null <<'SNMP'
view   lynxview  included  .1.3.6.1.2.1.1
view   lynxview  included  .1.3.6.1.4.1.8072.9999.1
rocommunity lynx default -V lynxview
pass_persist .1.3.6.1.4.1.8072.9999.1.3 /usr/bin/python3 /usr/local/lib/lynx-deck/lynx-deck-snmp-agent.py
SNMP
sudo systemctl enable snmpd >/dev/null 2>&1
sudo systemctl restart snmpd
echo "SNMP on: community 'lynx', the Deck at .1.3.6.1.4.1.8072.9999.1.3 (LYNX-MIB::lynxDeck)."
echo "Try:  snmpwalk -v2c -c lynx localhost .1.3.6.1.4.1.8072.9999.1.3"
