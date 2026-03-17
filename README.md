# Reactor Digital Twin

A batch reactor simulation built as a digital twin with OPC UA and web interfaces following the **ISA-88 / IEC 61512** batch control standard. The physics engine uses Pyomo DAE (Differential-Algebraic Equations) with IPOPT for numerical integration of the Kamal-Sourour autocatalytic kinetic model.

## Architecture

```
                          ┌────────────────┐
                          │  YAML Configs  │
                          │ model · recipe │
                          └───────┬────────┘
                                  │
  ┌───────────────────────────────▼───────────────────────────────┐
  │                     ISA-88 Procedure Model                    │
  │         Procedure → UnitProcedure → Operation → Phase         │
  │     conditional transitions · completion guards · B2MML       │
  └───────────────────────────────┬───────────────────────────────┘
                                  │
  ┌───────────────────────────────▼───────────────────────────────┐
  │                   Equipment / Control Modules                 │
  │                                                               │
  │   ┌──────────────────────────────────────────────────────┐    │
  │   │ Equipment Modules (EM)  — functional units           │    │
  │   │   EM-FILL · EM-DRAIN · EM-TEMP · EM-AGIT · ...      │    │
  │   │   mode transitions · interlocks · step sequences     │    │
  │   └──────────────────────────────────────────────────────┘    │
  │   ┌──────────────────────────────────────────────────────┐    │
  │   │ Control Modules (CM)  — valves · pumps · sensors     │    │
  │   │   OnOffValve · ControlValve · Pump · Sensor · Motor  │    │
  │   └──────────────────────────────────────────────────────┘    │
  └───────────────────────────────┬───────────────────────────────┘
                                  │
  ┌───────────────────────────────▼───────────────────────────────┐
  │                        Physics Engine                         │
  │                                                               │
  │   ┌───────────┐ ┌───────────────┐ ┌─────────┐ ┌──────────┐    │
  │   │ Viscosity │ │ Heat Transfer │ │ Mixing  │ │  Energy  │    │
  │   └───────────┘ └───────────────┘ └─────────┘ └──────────┘    │
  │            ▲  pluggable model blocks (YAML config)            │
  │                                                               │
  │              Pyomo DAE · IPOPT solver                         │
  │         adaptive sub-stepping + Euler fallback                │
  └───────────────────────────────┬───────────────────────────────┘
                                  │
  ┌───────────────┬───────────────┴───────────────┬───────────────┐
  │               │                               │               │
  │ ┌─────────────▼───────────┐ ┌─────────────────▼─────────────┐ │
  │ │   OPC Tool (separate)   │ │       Web Dashboard           │ │
  │ │  REST API · Node Catalog│ │   Vue 3 · Vite · Chart.js    │ │
  │ │  OPC UA Servers/Clients │ │   EM panels · P&ID · trends  │ │
  │ │       port 8001         │ │        port 8000              │ │
  │ └─────────────────────────┘ └───────────────────────────────┘ │
  └───────────────────────────────────────────────────────────────┘
```

## Simulation Model

The digital twin solves coupled ODEs for mass, energy, and conversion in a batch reactor using Pyomo DAE with IPOPT. The core equations are:

- **Mass balance** — per-species feed + stoichiometric consumption/production
- **Energy balance** — reaction exotherm + jacket heat transfer
- **Conversion** — Kamal-Sourour autocatalytic kinetics: `r = [k₁ + k₂·α^m]·(1-α)^n`

Sub-models for viscosity (gel-point divergence), fluid mechanics (Re, Nu, mixing efficiency), heat transfer (Chilton-Drew-Jebens correlation, series wall resistance), and vessel geometry feed into the dynamic UA and effective reaction rate.

IPOPT solves each horizon with adaptive sub-stepping and automatic Euler fallback for stiff regions.

For the complete equation reference, see [docs/equations.md](docs/equations.md).

### Components

| Module | Description |
|--------|-------------|
| `procedure.py` | ISA-88 `Procedure` → `UnitProcedure` → `Operation` → `Phase` hierarchy, `ProcedurePlayer`, B2MML export |
| `recipe.py` | YAML recipe/procedure loader, profile generators (constant, ramp, exponential) |
| `control_module.py` | Control module ABC + concrete types: `OnOffValve`, `ControlValve`, `Pump`, `Sensor`, `Motor`, `Heater` |
| `equipment_module.py` | `EquipmentModule` with named operating modes, step sequences, and state machine transitions |
| `em_manager.py` | `EMManager` — builds CMs/EMs from config, dispatches recipe modes, enforces interlocks |
| `physics.py` | `ReactorModel` wrapping Pyomo DAE integration with adaptive sub-stepping |
| `pyomo_model.py` | Builds the discretized Pyomo `ConcreteModel` (6 ODEs, collocation) |
| `controller.py` | `BatchController` FSM with 7 phases and thermal runaway detection |
| `chemistry.py` | Kamal-Sourour kinetics, heat transfer, viscosity (legacy functions) |
| `viscosity_models.py` | Pluggable viscosity models: constant, arrhenius, conversion, full_composition |
| `heat_transfer_models.py` | Pluggable heat transfer models: constant, geometry_aware, dynamic |
| `mixing_models.py` | Pluggable mixing efficiency models: perfect, reynolds, power_law |
| `energy_models.py` | Pluggable energy balance models: isothermal, adiabatic, full, extended |
| `batch.py` | `BatchRunner` for offline simulation, `SweepRunner` for parametric sweeps |
| `config.py` | `ModelConfig` (YAML) and `Settings` (env vars) |
| `opc_tool_client.py` | REST client for communicating with the [OPC Tool](docs/OPC_TOOL.md) |
| `opc_mapping.py` | Maps OPC Tool nodes to reactor state variables (direction, transform, priority) |
| `web.py` | FastAPI backend serving the built Vue 3 frontend and REST API |
| `frontend/` | Vue 3 + Vite Single Page Application (SPA) source code |

### ISA-88 Hierarchy

The procedural model follows the ISA-88 standard:

```
Procedure (batch recipe)
 └── UnitProcedure (one per process unit)
      └── Operation (logical grouping, e.g. PREPARATION, REACTION, DISCHARGE)
           └── Phase (= BatchStep: timed step with setpoints + EM mode requests)
```

`ProcedurePlayer` walks the hierarchy, evaluating conditional transitions and completion guards at each phase boundary. Equipment module mode requests (`em_mode:EM-TAG`) are dispatched to the `EMManager` on step transitions.

### FSM Phases

```
IDLE -> CHARGING -> HEATING -> EXOTHERM -> COOLING -> DISCHARGING
                          \                  /
                           -> RUNAWAY_ALARM -
```

- **IDLE**: Waiting for START command
- **CHARGING**: Feeding component_a and component_b into the reactor
- **HEATING**: Ramping jacket temperature to cure setpoint
- **EXOTHERM**: Reaction exotherm in progress, monitoring conversion
- **COOLING**: Conversion complete, cooling down
- **DISCHARGING**: Batch complete, ready for discharge
- **RUNAWAY_ALARM**: Thermal runaway detected (T > threshold or dT/dt > limit)

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js & npm (for frontend development only)
- IPOPT solver (see [Installing IPOPT](#installing-ipopt))

### Installation

```bash
# Clone and install
git clone <repository-url>
cd reactor
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -e ".[dev]"
```

### Setup Script and Requirements

If you prefer a classic setup workflow, this project includes a minimal `setup.py`.
Runtime dependencies are also pinned in `requirements.txt` for environments that
do not use editable installs.

```bash
# Install runtime requirements only
pip install -r requirements.txt

# Optional legacy setup entry point
python setup.py develop
```

### Installing IPOPT

IPOPT is the nonlinear optimization solver used by Pyomo. Choose one method:

**Option A: IDAES (recommended for most users)**
```bash
pip install idaes-pse
idaes get-extensions --verbose
```
This downloads pre-built IPOPT binaries to `~/.idaes/bin/`. The application automatically adds this directory to PATH at runtime.

**Option B: Conda**
```bash
conda install -c conda-forge ipopt
```

**Option C: System package (Linux)**
```bash
sudo apt install coinor-libipopt-dev
```

### Running the Simulation

```bash
# Start with defaults
python -m reactor

# Or use the console script
reactor
```

The simulation will:
1. Load the model config from `configs/default.yaml`
2. Load the batch recipe from `recipes/default.yaml`
3. Connect to the OPC Tool (if running on port 8001)
4. Serve the Web Dashboard on port 8000
5. Auto-start the recipe after 1 second

Open http://localhost:8000 for the live dashboard.

To enable OPC UA connectivity, start the OPC Tool in a separate terminal:

```bash
opc-tool
```

Open http://localhost:8001 for the OPC Tool GUI. See [docs/OPC_TOOL.md](docs/OPC_TOOL.md) for full documentation.

### Docker

```bash
# Build container here
docker compose build \
   && image_id=$(docker images -q reactor-reactor | head -n 1) \
   && docker save -o "reactor_image_$(date +%Y%m%d).tar" "$image_id"

# Run the container (detached)
docker compose up -d
  
# Stop and remove the container
docker compose down

# Or run from another folder
docker compose -f /path/to/reactor/docker-compose.yml --project-directory /path/to/reactor up --build
```

To edit recipes without rebuilding the image, bind-mount the host recipes folder:

```yaml
services:
   reactor:
      volumes:
         - ./recipes:/app/recipes
```

To regenerate the Dockerfile from the template script:

```bash
python scripts/generate_dockerfile.py
```

Ports exposed:
- `8000` - Reactor web dashboard
- `8001` - OPC Tool web GUI + REST API
- `4840` - OPC UA server (managed by OPC Tool)

## Configuration

### Environment Variables

All settings use the `REACTOR_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `REACTOR_WEB_PORT` | `8000` | Web dashboard port |
| `REACTOR_OPC_TOOL_URL` | `http://localhost:8001` | OPC Tool base URL |
| `REACTOR_OPC_TOOL_ENABLED` | `true` | Enable OPC Tool integration |
| `REACTOR_TICK_INTERVAL` | `0.5` | Simulation time step (seconds) |
| `REACTOR_ENABLE_WEB` | `true` | Enable web dashboard |
| `REACTOR_NOISE_PCT` | `0.5` | Sensor noise as % of reading |
| `REACTOR_INITIAL_TEMP_K` | `298.15` | Override initial temperature |
| `REACTOR_BATCH_MASS_KG` | `100` | Reference batch mass |
| `REACTOR_RECIPE_FILE` | `recipes/default.yaml` | Recipe file path |
| `REACTOR_MODEL_CONFIG_FILE` | `configs/default.yaml` | Model config path |

### Model Config (`configs/default.yaml`)

All physics, chemistry, and controller parameters are in a single YAML file. Edit this to change reaction kinetics, heat transfer, controller thresholds, or solver settings without modifying code.

#### Simulation Model Selection

The physics engine is modular: each simulation block (viscosity, heat transfer, mixing, energy balance) can use a different equation set. Add a `simulation` section to your config YAML to select models per block:

```yaml
simulation:
  models:
    viscosity: full_composition    # constant | arrhenius | conversion | full_composition
    heat_transfer: dynamic         # constant | geometry_aware | dynamic
    mixing: reynolds               # perfect | reynolds | power_law
    energy: full                   # isothermal | adiabatic | full | extended
```

If the `simulation` section is omitted, the simulator defaults to full-fidelity models (matching previous behavior). Available models:

| Block | Model | Description |
|-------|-------|-------------|
| **Viscosity** | `constant` | Fixed `eta_0`, ignores temperature and conversion |
| | `arrhenius` | Temperature-dependent only (Arrhenius) |
| | `conversion` | Temperature + conversion with gel-point divergence |
| | `full_composition` | Full model with species log-mixing rule (default) |
| **Heat Transfer** | `constant` | Fixed UA from config (default when mixing disabled) |
| | `geometry_aware` | Scales UA with wetted area ratio |
| | `dynamic` | Full Chilton-Drew-Jebens correlation from fluid mechanics (default when mixing enabled) |
| **Mixing** | `perfect` | Always 1.0 (default when mixing disabled) |
| | `reynolds` | Logistic sigmoid based on Reynolds number (default when mixing enabled) |
| | `power_law` | Power-law scaling with Re/Re_crit |
| **Energy** | `isothermal` | dT/dt = 0 (perfect temperature control) |
| | `adiabatic` | Reaction heat only, no jacket (worst-case runaway) |
| | `full` | Reaction + jacket heat transfer (default) |
| | `extended` | Adds frictional heating from agitator |

Custom models can be registered at runtime via `register_*_model()` functions in each module.

### Batch Recipe (`recipes/default.yaml`)

Recipes follow the ISA-88 procedural hierarchy. The default recipe uses a nested structure:

```yaml
name: Default Batch Cure
unit_procedures:
  - name: CURE_BATCH
    operations:
      - name: PREPARATION
        phases:
          - name: CHARGE_COMPONENT_A
            duration: 60
            channels:
              em_mode:EM-FILL: dose_component_a
              # ...
      - name: REACTION
        phases: [...]
      - name: DISCHARGE
        phases: [...]
```

Legacy flat recipe format (list of steps) is still supported and auto-wrapped into a single unit procedure/operation.

#### ISA-88 Procedural Features

- **Procedure hierarchy**: `Procedure` → `UnitProcedure` → `Operation` → `Phase` (phase = batch step)
- **Equipment module modes**: phases specify `em_mode:EM-TAG` channels to request EM mode changes
- **Conditional transitions**: per-phase `transitions` rules (e.g., branch based on conversion or temperature)
- **Completion guards**: block phase completion until required EM mode reaches `ACTIVE`
- **B2MML export**: `GET /api/recipe/{file}/b2mml` auto-generates MESA B2MML XML
- **Interlocks / preconditions**: config-driven mutual exclusions under `equipment.interlocks`
- **Batch parameter sets**: define in model config, select at runtime via `/api/batch/run`
- **Structured batch record**: each run writes `logs/batch_record_<timestamp>.json` with phase transition events

Transition conditions support boolean expressions with parentheses and case-insensitive `AND`/`OR`/`NOT`, for example:

```yaml
transitions:
  - if: "(temperature >= 350 AND conversion <= 0.8) OR NOT em_mode:EM-FILL:dose_component_a"
    then: "DISCHARGE_PRODUCT"
    else: "next"
```

### Equipment Modules (`configs/default.yaml`)

The `equipment:` section in the model config defines control modules and equipment modules. This section is optional — omitting it runs the simulator in direct recipe-to-physics mode (backward compatible).

```yaml
equipment:
  control_modules:
    - tag: XV-101
      type: on_off_valve
      name: Component A Inlet Valve
      maps_to: feed_component_a
      flow_rate: 1.0
    - tag: FT-301
      type: sensor
      name: Flow Transmitter
      maps_to: feed_rate
      # ...

  equipment_modules:
    - tag: EM-FILL
      name: Filling System
      cms: [XV-101, XV-102, PP-101, FT-301]
      modes:
        - name: dose_component_a
          display_name: Dose Component A
          steps:
            - action: "command:XV-101:open"
              check: "cm_state:XV-101:running"
            - action: "command:PP-101:start"
              check: "pv_gt:FT-301:0.1"

  interlocks:
    mode_conflicts:
      - [EM-FILL:dose_component_a, EM-DRAIN:drain]
    mode_preconditions:
      - mode: EM-TEMP:heat
        requires: EM-AGIT:run
```

Six equipment modules are pre-configured: **EM-FILL** (filling), **EM-DRAIN** (draining), **EM-TEMP** (temperature control), **EM-AGIT** (agitation), **EM-PRESS** (pressure), **EM-INERT** (inerting).

Equipment check strings in `check`, `preconditions`, and `postconditions` also support case-insensitive boolean expressions with parentheses:

```yaml
preconditions:
  - "cm_state:XV-101:idle AND pv_lt:LT-101:95"
steps:
  - action: "noop"
    check: "pv_gt:FT-301:0.1 OR NOT cm_state:P-101:running"
```

## OPC UA Interface

OPC UA connectivity is handled by the **OPC Tool**, a standalone service that manages OPC UA servers, client connections, and a unified node catalog. The reactor communicates with the OPC Tool via REST API.

For full OPC Tool documentation, see [docs/OPC_TOOL.md](docs/OPC_TOOL.md).
For OPC UA setup and security hardening guidance, see [docs/OPC_UA.md](docs/OPC_UA.md).

### How It Works

1. Start the OPC Tool (`opc-tool`) — it runs on port 8001 with its own web GUI
2. Create nodes in the OPC Tool (sensors, actuators, status, etc.)
3. Create a managed OPC UA server to expose nodes to external DCS/SCADA systems
4. In the reactor GUI, map OPC Tool nodes to reactor variables (temperature, conversion, etc.)
5. The reactor reads/writes mapped nodes via REST each simulation tick

The reactor runs without the OPC Tool — if it's not reachable, simulation continues normally and retries every 30 seconds.

## Web Dashboard Development

The frontend is a Vue 3 application built with Vite. The source code is located in `frontend/`.

### Setup

```bash
cd frontend
npm install
```

### Running in Development Mode

To edit the UI with Hot Module Replacement (HMR):

1. Start the Python backend (needed for API):
   ```bash
   python -m reactor
   ```
2. Start the Vue development server:
   ```bash
   cd frontend
   npm run dev
   ```
3. Open `http://localhost:5173`. The development server proxies API requests to the Python backend on port 8000.

### Building for Production

To update the static files served by Python:

```bash
cd frontend
npm run build
```
This builds the app to `frontend/dist`. The Python application is configured to serve this directory automatically.

## Project Structure

```
reactor/
├── configs/                    # Physics/Chemistry YAML configs + equipment definitions
├── recipes/                    # Batch recipes (ISA-88 procedure format)
├── frontend/                   # Reactor Vue 3 Frontend
│   ├── src/                    # Vue components and logic
│   │   └── components/
│   │       └── EquipmentModulePanel.vue  # EM mode control panel
│   ├── dist/                   # Built static files (served by Python)
│   └── package.json
├── src/reactor/                # Reactor Python Backend
│   ├── __main__.py             # Entry point
│   ├── procedure.py            # ISA-88 Procedure hierarchy + ProcedurePlayer + B2MML
│   ├── recipe.py               # Recipe/procedure YAML loader
│   ├── control_module.py       # Control module types (valves, pumps, sensors, etc.)
│   ├── equipment_module.py     # Equipment modules with operating modes
│   ├── em_manager.py           # EM/CM orchestrator, interlocks, recipe dispatch
│   ├── physics.py              # Pyomo DAE Model
│   ├── pyomo_model.py          # Pyomo ConcreteModel builder
│   ├── controller.py           # FSM Logic
│   ├── viscosity_models.py     # Pluggable viscosity models
│   ├── heat_transfer_models.py # Pluggable heat transfer models
│   ├── mixing_models.py        # Pluggable mixing models
│   ├── energy_models.py        # Pluggable energy balance models
│   ├── opc_tool_client.py      # REST client for OPC Tool
│   ├── opc_mapping.py          # Node ↔ reactor variable mappings
│   ├── web.py                  # FastAPI Web Server
│   └── ...
├── src/opc_tool/               # OPC Tool (standalone package)
│   ├── __main__.py             # Entry point
│   ├── node_manager.py         # Node catalog CRUD + persistence
│   ├── server.py               # Managed OPC UA servers (asyncua)
│   ├── client.py               # Client connections to external servers
│   └── web.py                  # FastAPI REST API
├── opc_frontend/               # OPC Tool Vue 3 Frontend
│   ├── src/
│   └── package.json
├── tests/                      # Pytest suite
│   ├── test_batch_isa88.py     # ISA-88 procedure integration tests
│   ├── test_control_module.py  # Control module unit tests
│   ├── test_equipment_module.py # Equipment module + manager tests
│   ├── test_opc_tool/          # OPC Tool unit tests
│   └── ...
├── docs/
│   ├── OPC_TOOL.md             # OPC Tool documentation
│   └── ...
├── pyproject.toml
└── Dockerfile
```

## License

MIT
