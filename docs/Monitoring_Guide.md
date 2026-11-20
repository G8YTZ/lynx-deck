# Lynx Deck: Monitoring (SNMP)

The Deck reports its health over SNMP, the same way Lynx-Tx does, so Home
Assistant (or any SNMP monitor) can show at a glance that the playout is
healthy: playing, the player healthy, the clock on time, the schedule making
its cuts.

- **Read-only,** SNMP v2c, community `lynx`.
- **One MIB for the Lynx family:** `mibs/LYNX-MIB.txt`, the same file as
  Lynx-Tx's. The Deck is the `lynxDeck` branch,
  `.1.3.6.1.4.1.8072.9999.1.3`; Lynx-Tx is `lynxTx`, `.1.3.6.1.4.1.8072.9999.1.1`.
- **Nothing on air depends on it.** If SNMP stops, the Deck plays on.

## Setting it up

New installs: `scripts/install.sh` does it. A Deck installed before
version 1.8.0, once, after updating:

```
cd ~/lynx-deck && ./scripts/setup_snmp.sh
```

It installs `snmpd`, the `snmp` tools for checking it, the agent (`tools/lynx-deck-snmp-agent.py`) and the MIB,
and opens SNMP to the network. Check it on the Deck:

```
snmpwalk -v2c -c lynx -On localhost .1.3.6.1.4.1.8072.9999.1.3
```

Twenty lines, by number. Names (`LYNX-MIB::lynxDeck`) need the standard MIB
files as well, as described in Lynx-Tx's monitoring guide; Home Assistant uses
the numbers and needs none of that.

## What it reports

All under `.1.3.6.1.4.1.8072.9999.1.3`, each ending `.0`:

| No. | Name | What it means | Alarm when |
|---|---|---|---|
| 1 | lynxDeckState | 1 playing, 2 stopped (holding), 3 player fault, 4 not answering | 3 or 4 |
| 2 | lynxDeckPlayerState | 1 ok, 2 stalled, 3 restarting, 4 unknown | not 1 |
| 3 | lynxDeckClipName | The clip on the output now | |
| 4 | lynxDeckClipIndex | Its number in the clip list | |
| 5 | lynxDeckClipCount | Clips in the media folder | 0 |
| 6 | lynxDeckDecoderDrops | Frames the decoder dropped | rising |
| 7 | lynxDeckLateFrames | Frames shown late | rising fast |
| 8 | lynxDeckPlayerRestarts | Player restarts by the watchdog since the Deck started | rising |
| 9 | lynxDeckTimeSynced | 1 the Pi's clock is on NTP, 2 not | 2 |
| 10 | lynxDeckScheduleEntries | Schedule entries switched on | 0 |
| 11 | lynxDeckScheduleOnAir | What the schedule says is on air | |
| 12 | lynxDeckScheduleCuts | Scheduled cuts made since the Deck started | |
| 13 | lynxDeckScheduleMisses | Scheduled cuts that could not be made | rising |
| 14 | lynxDeckHdmiConnected | 1 something is on the HDMI output, 2 nothing | 2 |
| 15 | lynxDeckCpuTemp | Processor temperature, tenths of a degree | above 800 |
| 16 | lynxDeckUptime | Seconds since the Pi started | drops (it restarted) |
| 17 | lynxDeckCpuLoad | Load as a percentage of all four cores | above 80 for long |
| 18 | lynxDeckDiskFreeMB | Free space where the media lives | below 1000 |
| 19 | lynxDeckVersion | The Deck's software version | |
| 20 | lynxDeckClockOffset | The clock's *ahead by* setting, in milliseconds | |

Counters (6, 7, 8, 12, 13) start again from zero when the Deck's software
restarts. If the Deck's software stops answering, state reads 4 and the rest
read empty or zero: an alarm, as it should be.

## Home Assistant

In `configuration.yaml`, with the Deck's address in place of
`192.168.40.117`:

```yaml
sensor:
  - platform: snmp
    name: Lynx Deck state
    unique_id: lynx_deck_state
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.1.0
    value_template: >-
      {{ {'1': 'playing', '2': 'stopped', '3': 'player fault', '4': 'not answering'}.get(value, 'unknown') }}

  - platform: snmp
    name: Lynx Deck clip
    unique_id: lynx_deck_clip
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.3.0

  - platform: snmp
    name: Lynx Deck clock synchronised
    unique_id: lynx_deck_time_synced
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.9.0
    value_template: "{{ 'yes' if value == '1' else 'no' }}"

  - platform: snmp
    name: Lynx Deck schedule on air
    unique_id: lynx_deck_schedule_on_air
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.11.0

  - platform: snmp
    name: Lynx Deck missed cuts
    unique_id: lynx_deck_schedule_misses
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.13.0

  - platform: snmp
    name: Lynx Deck CPU temperature
    unique_id: lynx_deck_cpu_temp
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.15.0
    unit_of_measurement: "°C"
    value_template: "{{ (value | int / 10) | round(1) }}"

  - platform: snmp
    name: Lynx Deck free space
    unique_id: lynx_deck_disk_free
    host: 192.168.40.117
    community: lynx
    version: "2c"
    baseoid: 1.3.6.1.4.1.8072.9999.1.3.18.0
    unit_of_measurement: "MB"
```

An automation to tell you when something is wrong:

```yaml
automation:
  - alias: Lynx Deck needs attention
    trigger:
      - platform: state
        entity_id: sensor.lynx_deck_state
        to: ["player fault", "not answering"]
        for: "00:01:00"
      - platform: state
        entity_id: sensor.lynx_deck_clock_synchronised
        to: "no"
        for: "00:10:00"
    action:
      - service: notify.notify
        data:
          message: "Lynx Deck: {{ trigger.to_state.name }} is {{ trigger.to_state.state }}"
```
