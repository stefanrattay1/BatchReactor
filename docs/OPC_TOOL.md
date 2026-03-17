# OPC Tool

A standalone OPC UA management tool that provides a unified node catalog, managed OPC UA servers, and client connections to external OPC UA endpoints. It runs independently from the reactor simulation and exposes a REST API + web GUI.

## Architecture

```
OPC Tool (port 8001)
  ├── NodeManager         ← central catalog of all OPC UA nodes
  ├── ManagedOPCServer(s) ← asyncua servers exposing catalog nodes
  ├── OPCClientPool       ← connections to external OPC UA servers
  └── Web GUI + REST API  ← Vue 3 frontend + FastAPI backend
```

The reactor (or any other application) discovers and interacts with OPC nodes through the REST API rather than managing OPC UA connections directly.

## Quick Start

```bash
# From the repo root (with the venv activated)
opc-tool

# Or via module
python -m opc_tool

# Custom port and data directory
opc-tool --port 8002 --data-dir /path/to/data
```

Open http://localhost:8001 for the web GUI.

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8001` | Web server port |
| `--data-dir` | `opc_tool_data` | Directory for persisted node catalog and connection configs |
| `--no-build` | `false` | Skip frontend build step on startup |

### Environment Variables

All settings use the `OPC_TOOL_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPC_TOOL_WEB_PORT` | `8001` | Web server port |
| `OPC_TOOL_DATA_DIR` | `opc_tool_data` | Data directory |
| `OPC_TOOL_DEFAULT_SERVER_PORT` | `4840` | Default OPC UA server port |
| `OPC_TOOL_CORS_ORIGINS` | `["*"]` | Allowed CORS origins |

## Concepts

### Node Catalog

Every OPC UA node — whether locally created or discovered from an external server — is registered in the `NodeManager`. Each node has:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier (e.g. `"temperature"`) |
| `name` | Display name / OPC UA browse name (e.g. `"Temperature_K"`) |
| `node_id` | OPC UA NodeId string (e.g. `"ns=2;s=Temperature_K"`) |
| `source` | `"local"` or the connection_id it was imported from |
| `category` | `"sensor"`, `"actuator"`, `"status"`, or `"custom"` |
| `data_type` | `"Double"`, `"String"`, `"Int32"`, `"Boolean"`, etc. |
| `writable` | Whether external clients can write to this node |
| `current_value` | Last known value (updated by polling or REST writes) |

Nodes are persisted to `<data_dir>/nodes.json`.

### Managed OPC UA Servers

You can create one or more OPC UA servers through the GUI or API. Each server:

- Exposes all `source="local"` nodes from the catalog
- Groups nodes into folders by category (`Sensors/`, `Actuators/`, `Status/`, etc.)
- Supports standard asyncua data types and writable nodes

### Client Connections

The OPC Tool can connect to external OPC UA servers (PLCs, SCADA, DCS) as a client:

- **Connections** define the endpoint, security settings, and credentials
- **Subscriptions** poll specific nodes and write values into the catalog
- Passwords are never persisted to disk — they must be provided at runtime
- Node browsing lets you explore remote server trees and import nodes

## REST API

### Health

```
GET /api/health → {"status": "ok", "version": "0.1.0"}
```

### Node CRUD

```
GET    /api/nodes[?category=sensor]     → list nodes (filterable)
GET    /api/nodes/{node_id}             → single node details
POST   /api/nodes                       → create node
PUT    /api/nodes/{node_id}             → update node metadata
DELETE /api/nodes/{node_id}             → remove node
```

### Value Read/Write

```
GET  /api/nodes/{node_id}/value         → read current value
POST /api/nodes/{node_id}/value         → write value (also pushes to OPC UA servers)
POST /api/values/bulk                   → read multiple values
POST /api/values/write-bulk             → write multiple values
```

### Server Management

```
GET    /api/servers                     → list managed OPC UA servers
POST   /api/servers                     → create and start a server
DELETE /api/servers/{server_id}         → stop and remove a server
```

### Client Connections

```
GET    /api/connections                             → list connections + subscriptions
POST   /api/connections                             → add connection
DELETE /api/connections/{conn_id}                    → remove connection
POST   /api/connections/{conn_id}/credentials       → set runtime credentials
POST   /api/connections/{conn_id}/browse             → browse remote node tree
```

### Subscriptions

```
POST   /api/subscriptions               → add subscription (polls remote node → catalog)
DELETE /api/subscriptions/{sub_id}      → remove subscription
```

### Discovery

```
POST /api/discover → discover OPC UA servers on the network
```

## Integration with the Reactor

The reactor connects to the OPC Tool as a REST client. The integration flow:

```
OPC Tool (port 8001)              Reactor (port 8000)
  NodeManager ◄──── REST ────── OPCToolClient
       │                              │
       ▼                              ▼
  ManagedOPCServer            OPCMappingManager
       │                         maps node ↔ state var
       ▼                              │
  External DCS/SCADA              SensorBuffer
```

1. **Create nodes** in the OPC Tool (sensors, actuators, etc.)
2. **Map nodes** to reactor variables in the reactor GUI (OPC Tool Integration tab)
3. Each simulation tick:
   - Reactor bulk-reads mapped sensor nodes via REST → feeds into SensorBuffer
   - Reactor bulk-writes state variables to mapped output nodes via REST
4. External systems connect via OPC UA to the managed server

### Reactor Configuration

In the reactor's environment or `Settings`:

| Variable | Default | Description |
|----------|---------|-------------|
| `REACTOR_OPC_TOOL_URL` | `http://localhost:8001` | OPC Tool base URL |
| `REACTOR_OPC_TOOL_ENABLED` | `true` | Enable OPC Tool integration |

The reactor degrades gracefully: if the OPC Tool is not reachable, simulation runs without OPC and retries the health check every 30 seconds.

### Mapping Configuration

Mappings are stored in `configs/opc_mappings.json` and define:

| Field | Description |
|-------|-------------|
| `opc_node_id` | Node ID in the OPC Tool catalog |
| `reactor_var` | Reactor state key (`temperature`, `jacket_temperature`, etc.) |
| `direction` | `"read"` (OPC → reactor) or `"write"` (reactor → OPC) |
| `transform` | Math expression (e.g. `"value + 273.15"`) |
| `priority` | SensorBuffer priority for read mappings (0-100) |
| `enabled` | Enable/disable without deleting |

## Frontend Development

The OPC Tool frontend is a Vue 3 + Vite application in `opc_frontend/`.

```bash
cd opc_frontend
npm install
npm run dev    # Dev server with HMR (proxies API to :8001)
npm run build  # Production build to opc_frontend/dist/
```

## Package Structure

```
src/opc_tool/
  ├── __init__.py          # Package version
  ├── __main__.py          # Entry point (CLI + server startup)
  ├── config.py            # OPCToolSettings (pydantic-settings)
  ├── node_manager.py      # NodeManager + OPCNode dataclass
  ├── server.py            # ManagedOPCServer (asyncua wrapper)
  ├── client.py            # OPCClientPool + OPCConnection
  └── web.py               # FastAPI app + REST API

opc_frontend/
  ├── src/
  │   ├── App.vue                      # Shell with tabs + health indicator
  │   ├── components/
  │   │   ├── NodeList.vue             # Node catalog CRUD
  │   │   ├── ServerManager.vue        # Managed server lifecycle
  │   │   └── ConnectionManager.vue    # Client connections + subscriptions
  │   └── services/api.js             # API client
  └── package.json
```

## Tests

```bash
# OPC Tool unit tests
pytest tests/test_opc_tool/

# Reactor ↔ OPC Tool integration
pytest tests/test_opc_tool_client.py    # REST client (mocked)
pytest tests/test_opc_mapping.py        # Mapping manager
pytest tests/test_opc_client_manager.py # Client pool
pytest tests/test_opcua_integration.py  # Full OPC UA protocol tests (requires IPOPT)
```
