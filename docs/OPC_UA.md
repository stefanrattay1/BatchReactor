# OPC UA Setup and Security Guide

This guide explains exactly how to get OPC UA integration working in this project, both for:

1. Running the built-in OPC UA server (the simulator exposing tags)
2. Connecting this simulator as an OPC UA client to external servers/sensors
3. Securing the deployment for real environments

---

## 1) What must be done on the other side

Being on the same network/subnet helps, but OPC UA does **not** work automatically just from network proximity.

On the sensor/PLC/SCADA side, all of these must be in place:

1. OPC UA server running and reachable
   - Endpoint must exist, e.g. `opc.tcp://<device-ip>:4840`
2. Required tags must be published as OPC UA nodes
   - You need valid NodeIds for each value you want to read/write
3. Network path must be open
   - Firewall/ACL must allow inbound TCP from this reactor host to the OPC UA port
4. Security/authentication must match on both sides
   - Anonymous or username/password or certificate-based trust
   - If secure mode is used, `security_mode` and `security_policy` must match exactly
5. Certificate trust must be configured when using Sign/SignAndEncrypt
   - The external OPC UA server must trust this client's certificate

Best practice commissioning flow:

1. Verify endpoint and tags in UAExpert first
2. Then configure the same endpoint in this app
3. Browse nodes and subscribe using the exact NodeIds

---

## 2) What is built-in vs proprietary

- OPC UA protocol itself is an open standard, not proprietary.
- This software uses standard OPC UA via Python `asyncua`.
- The **information model** (tag tree and names) is application-specific. That is normal and expected.

In this project, the built-in server exposes nodes under:

- `Objects/Reactor/Sensors/...`
- `Objects/Reactor/Actuators/...`
- `Objects/Reactor/Status/...`
- `Objects/Reactor/Recipe/...`

---

## 3) Prerequisites

- Python environment with project dependencies installed
- Simulator starts successfully (`python -m reactor`)
- Network/firewall allows OPC UA TCP port (default 4840)
- Optional for secure client connections: certificate/key files

Default ports:

- OPC UA server: `4840`
- Web API/dashboard: `8000`

---

## 4) Quick start: run the built-in OPC UA server

### 4.1 Start simulator

From project root:

```bash
python -m reactor
```

On startup the app initializes:

- OPC UA server endpoint `opc.tcp://0.0.0.0:4840`
- Web API/dashboard on `http://localhost:8000`

### 4.2 Verify from an OPC UA client tool

Using UAExpert (or equivalent):

1. Add server: `opc.tcp://<host-ip>:4840`
2. Connect
3. Browse to `Objects/Reactor`
4. Confirm tags are present, for example:
   - `Sensors/Temperature_K`
   - `Sensors/Pressure_bar`
   - `Actuators/JacketSetpoint_K`
   - `Recipe/Command`

### 4.3 Test read/write behavior

- Read from sensors (read-only)
- Write an actuator value, e.g. `Actuators/JacketSetpoint_K`
- Optionally write `Recipe/Command = START`

---

## 5) Connect simulator to an external OPC UA server (client mode)

This is for ingesting external sensor values into the digital twin state.

### 5.1 Through dashboard UI

1. Open `http://localhost:8000`
2. Go to OPC UA connection manager
3. Add connection endpoint (or discover servers)
4. Confirm connection shows Connected
5. Browse nodes
6. Subscribe variable node and map to state key

Subscription fields:

- `connection_id`: which external server connection to use
- `node_id`: full OPC UA NodeId returned by browse
- `state_key`: simulator field to update (see allowed keys below)
- `polling_rate_ms`: read interval per subscription
- `transform`: arithmetic expression using `value`

Example transforms:

- `value`
- `value * 0.1`
- `value + 273.15`

### 5.2 Supported `state_key` mappings

Only the following keys are accepted (enforced by an allowlist in `opc_client.py`):

| `state_key`            | Target                         |
|------------------------|--------------------------------|
| `temperature`          | reactor temperature (K)        |
| `temperature_K`        | reactor temperature (K)        |
| `jacket_temperature`   | jacket temperature (K)         |
| `jacket_temperature_K` | jacket temperature (K)         |
| `volume`               | reactor volume (m^3)           |
| `pressure_bar`         | model pressure config (bar)    |

Any other `state_key` is rejected and a warning is logged listing the allowed keys.

### 5.3 Discovery: important note

The "Scan Network" / discovery feature queries a discovery URL (default `opc.tcp://localhost:4840`) for registered OPC UA servers. Because this application itself runs an OPC UA server on port 4840, **discovery will find the application's own server**. This is expected — it does not mean an external device was found.

To discover external servers, enter their actual discovery endpoint (e.g. `opc.tcp://10.10.20.15:4840`).

### 5.4 Persistent configuration file

Connections/subscriptions persist in:

- `configs/opc_connections.json`

Example secure-capable connection object:

```json
{
  "id": "plant-opc-1",
  "endpoint": "opc.tcp://10.10.20.15:4840",
  "security_mode": "SignAndEncrypt",
  "security_policy": "Basic256Sha256",
  "certificate_path": "certs/opc/client_cert.der",
  "private_key_path": "certs/opc/client_key.pem",
  "username": null,
  "enabled": true
}
```

Password handling:

- Passwords are runtime-only and are not persisted to `configs/opc_connections.json`.
- If `username` is configured, provide password each app run via the dashboard credentials action.

Dashboard API supports `security_mode`, `security_policy`, `certificate_path`, and `private_key_path`.

---

## 6) Security: what exists now and what to do

### 6.1 Current state in code

- Built-in OPC UA **server** currently starts without certificate/policy hardening.
- OPC UA **client manager** supports secure mode parameters (`security_mode`, `security_policy`, cert/key paths) when provided.
- If secure mode is set (`Sign` or `SignAndEncrypt`) and policy/cert/key are missing/invalid, client connection fails closed (no insecure fallback).
- Transform expressions are restricted to safe arithmetic parsing (no arbitrary code execution).
- Subscription `state_key` values are checked against an explicit allowlist (no arbitrary attribute writes).

### 6.2 Minimum safe deployment baseline

If you are not enabling full OPC UA application security yet, do all of these:

1. Restrict network exposure
   - Bind services to trusted interfaces only
   - Allow port 4840 only from required source hosts
2. Isolate with VLAN/OT segment or VPN
3. Disable unnecessary write paths in client applications
4. Run with least privilege user account
5. Enable log collection and alerting for repeated failed connections/writes

### 6.3 Recommended production security model

1. Enable OPC UA SignAndEncrypt end-to-end
2. Use certificate trust stores (server and client)
3. Prefer strong policy (for example Basic256Sha256)
4. Enforce authentication (username/cert), disable anonymous where possible
5. Rotate credentials/certificates on schedule
6. Keep host OS and dependencies patched
7. Add monitoring for:
   - connection churn
   - bad certificate events
   - unauthorized write attempts

### 6.4 Certificate generation example (OpenSSL)

Use your PKI if available. For lab use only:

```bash
mkdir -p certs/opc
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/opc/client_key.pem \
  -out certs/opc/client_cert.pem \
  -days 365 \
  -subj "/CN=reactor-opc-client"
openssl x509 -outform der -in certs/opc/client_cert.pem -out certs/opc/client_cert.der
```

Then configure:

- `certificate_path`: DER certificate path
- `private_key_path`: PEM private key path

Also trust this client certificate on the external OPC UA server side.

---

## 7) Network and Docker notes

- If running in Docker, publish `4840:4840` and `8000:8000` as needed.
- For cross-host clients, use host IP or DNS name instead of localhost.
- If behind NAT/firewall, allow inbound TCP 4840 from trusted clients only.

---

## 8) Validation checklist

Use this quick checklist after setup:

- Simulator starts with no OPC errors in logs
- OPC UA client tool can browse `Objects/Reactor`
- Sensor values change over time
- Writable nodes accept writes (where expected)
- External subscription appears in dashboard
- `last_value` updates for active subscriptions
- Mapped simulator variable actually changes
- Security controls (firewall, auth, cert trust) verified

---

## 9) Troubleshooting

### Cannot connect to endpoint

- Verify process is running
- Verify endpoint URL and port
- Check firewall rules
- Check Docker port mapping

### Browse works but values do not update

- Confirm subscription is enabled
- Confirm correct `node_id`
- Confirm `state_key` is one of the allowed keys (see section 5.2)
- Confirm transform expression is valid

### Secure connection fails

- Verify `security_policy` and `security_mode` exactly match server
- Verify certificate format/path
- Verify remote server trusts your client cert
- Verify hostname/application URI expectations on server

### Discovery only shows own server

- The default discovery URL (`localhost:4840`) points at this application's own OPC UA server
- Enter the actual IP/hostname of the external device to discover its servers

### Frequent disconnects/timeouts

- Increase polling interval
- Check network latency/loss
- Review server session limits
