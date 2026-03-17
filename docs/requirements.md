# Requirements and Setup

This project ships with both a classic setup script and a standard requirements file:

| File | Purpose |
|------|---------|
| `setup.py` | Legacy setup entry point for tools that expect a setup script |
| `requirements.txt` | Runtime dependency list synced with `pyproject.toml` |

## Install Options

```bash
# Runtime dependencies only
pip install -r requirements.txt

# Editable install (recommended for development)
pip install -e ".[dev]"

# Legacy setup flow
python setup.py develop
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
