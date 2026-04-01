# Requirements and Setup

This project ships with bash bootstrap scripts and a standard requirements file:

| File | Purpose |
|------|---------|
| `setup.sh` | Main bootstrap entry point for Linux/macOS setup |
| `scripts/setup_reactor.sh` | Reactor bootstrap script used by `setup.sh` |
| `scripts/setup_opc_tool.sh` | OPC Tool bootstrap script |
| `requirements.txt` | Runtime dependency list synced with `pyproject.toml` |

## Install Options

```bash
# Preferred bootstrap flow
./setup.sh

# Runtime dependencies only
pip install -r requirements.txt

# Editable install (recommended for development)
pip install -e ".[dev]"
```

## Web Interface Notes

### Open Platform Communications Unified Architecture (OPC UA) interface
- Connection status indicator and connect/disconnect control
- Input/output management for sensors and actuators

### Reactor model with interactive features
- Reactor model for visual orientation
- Inputs, outputs, and states are visualized and clickable for more info
- Reactor temperature and selectable stats displayed in a diagram with a "NOW" line

## Simulation
