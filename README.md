# Cala (MQTT)

Home Assistant custom integration for Cala water heaters.

## Installation (HACS)
1. Install HACS
2. HACS → Integrations → ⋮ → Custom repositories
3. Add this repository URL
4. Category: Integration
5. Install “Cala”
6. Restart Home Assistant

## Setup
- Preferred: discovery via mDNS/Zeroconf (device advertises itself).
- Fallback: manual setup (enter device host/port), then enter provisioning code and MQTT credentials.

## Notes
This integration requires the MQTT integration enabled in Home Assistant.
