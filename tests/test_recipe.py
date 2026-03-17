"""Unit tests for recipe module."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from reactor.recipe import (
    BatchStep,
    ConditionSyntaxWarning,
    ProfileSegment,
    ProfileType,
    Recipe,
    RecipePlayer,
    add_sensor_noise,
    load_recipe,
)
from reactor.procedure import (
    Operation,
    Procedure,
    ProcedurePlayer,
    RecipeMetadata,
    RecipeMetadataWarning,
    RecipeSignatureError,
    UnitProcedure,
    load_procedure,
    sign_recipe_yaml,
    sign_recipe_xml,
    to_b2mml,
)


class TestProfileSegment:
    def test_constant(self):
        p = ProfileSegment(ProfileType.CONSTANT, 10.0, 10.0, 100.0)
        assert p.evaluate(0.0) == 10.0
        assert p.evaluate(50.0) == 10.0
        assert p.evaluate(100.0) == 10.0

    def test_linear_ramp(self):
        p = ProfileSegment(ProfileType.LINEAR_RAMP, 0.0, 100.0, 10.0)
        assert pytest.approx(p.evaluate(0.0)) == 0.0
        assert pytest.approx(p.evaluate(5.0)) == 50.0
        assert pytest.approx(p.evaluate(10.0)) == 100.0

    def test_linear_ramp_clamped(self):
        p = ProfileSegment(ProfileType.LINEAR_RAMP, 0.0, 100.0, 10.0)
        assert pytest.approx(p.evaluate(-5.0)) == 0.0
        assert pytest.approx(p.evaluate(20.0)) == 100.0

    def test_exponential(self):
        p = ProfileSegment(ProfileType.EXPONENTIAL, 1.0, 100.0, 10.0)
        assert pytest.approx(p.evaluate(0.0)) == 1.0
        assert pytest.approx(p.evaluate(10.0)) == 100.0
        mid = p.evaluate(5.0)
        assert 1.0 < mid < 100.0

    def test_zero_duration(self):
        p = ProfileSegment(ProfileType.LINEAR_RAMP, 0.0, 100.0, 0.0)
        assert p.evaluate(0.0) == 100.0


class TestRecipePlayer:
    @pytest.fixture
    def simple_recipe(self) -> Recipe:
        return Recipe(
            name="test",
            steps=[
                BatchStep("step1", 10.0, {
                    "valve": ProfileSegment(ProfileType.CONSTANT, 1.0, 1.0, 10.0),
                }),
                BatchStep("step2", 5.0, {
                    "valve": ProfileSegment(ProfileType.CONSTANT, 0.0, 0.0, 5.0),
                    "heater": ProfileSegment(ProfileType.LINEAR_RAMP, 0.0, 100.0, 5.0),
                }),
            ],
        )

    def test_initial_state(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        assert player.current_step_idx == 0
        assert not player.finished

    def test_tick_returns_values(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        values = player.tick(1.0)
        assert values["valve"] == 1.0

    def test_step_transition(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        # Tick past step 1
        for _ in range(10):
            player.tick(1.0)
        assert player.current_step_idx == 1

    def test_finishes(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        for _ in range(20):
            player.tick(1.0)
        assert player.finished

    def test_finished_returns_empty(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        for _ in range(20):
            player.tick(1.0)
        assert player.tick(1.0) == {}

    def test_reset(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        for _ in range(20):
            player.tick(1.0)
        player.reset()
        assert player.current_step_idx == 0
        assert not player.finished

    def test_total_elapsed(self, simple_recipe: Recipe):
        player = RecipePlayer(simple_recipe)
        for _ in range(5):
            player.tick(1.0)
        assert pytest.approx(player.total_elapsed, abs=0.01) == 5.0

    def test_channels(self, simple_recipe: Recipe):
        assert simple_recipe.channels == {"valve", "heater"}


class TestNoiseInjection:
    def test_noise_around_value(self):
        np.random.seed(42)
        values = [add_sensor_noise(100.0, noise_pct=1.0) for _ in range(1000)]
        assert pytest.approx(np.mean(values), abs=0.5) == 100.0
        assert np.std(values) > 0.5  # noise is present

    def test_zero_value_no_noise(self):
        assert add_sensor_noise(0.0) == 0.0


class TestLoadRecipe:
    def test_load_default_recipe(self):
        recipe_path = Path(__file__).parent.parent / "recipes" / "default.yaml"
        recipe = load_recipe(recipe_path)
        assert recipe.name == "Default Cure Process"
        assert len(recipe.steps) == 10
        assert recipe.steps[0].name == "INERT"
        assert recipe.steps[0].duration == 60.0
        assert recipe.steps[1].name == "CHARGE_COMPONENT_A"
        assert recipe.steps[1].duration == 120.0
        assert "feed_component_a" in recipe.steps[1].profiles

    def test_roundtrip_yaml(self, tmp_path: Path):
        yaml_content = """
name: test_recipe
steps:
  - name: HEAT
    duration: 100
    profiles:
      jacket_temp:
        type: linear_ramp
        start: 300
        end: 400
"""
        recipe_file = tmp_path / "test.yaml"
        recipe_file.write_text(yaml_content)
        recipe = load_recipe(recipe_file)
        assert recipe.name == "test_recipe"
        step = recipe.steps[0]
        profile = step.profiles["jacket_temp"]
        assert profile.profile_type == ProfileType.LINEAR_RAMP
        assert pytest.approx(profile.evaluate(50.0)) == 350.0


# ---------------------------------------------------------------------------
# ISA-88 Procedure hierarchy tests
# ---------------------------------------------------------------------------

class TestProcedure:
    def test_load_nested_procedure(self, tmp_path: Path):
        yaml_content = """
name: test_proc
unit_procedures:
  - name: REACTOR_R101
    operations:
      - name: PREP
        phases:
          - name: INERT
            duration: 60
            profiles:
              jacket_temp:
                type: constant
                value: 298.15
      - name: REACT
        phases:
          - name: HEAT
            duration: 300
            profiles:
              jacket_temp:
                type: linear_ramp
                start: 298.15
                end: 338.15
"""
        f = tmp_path / "proc.yaml"
        f.write_text(yaml_content)
        proc = load_procedure(f)
        assert proc.name == "test_proc"
        assert len(proc.unit_procedures) == 1
        up = proc.unit_procedures[0]
        assert up.name == "REACTOR_R101"
        assert len(up.operations) == 2
        assert up.operations[0].name == "PREP"
        assert up.operations[1].name == "REACT"
        assert len(up.operations[0].phases) == 1
        assert up.operations[0].phases[0].name == "INERT"
        assert len(proc.phases_flat) == 2

    def test_flat_yaml_autowrap(self, tmp_path: Path):
        yaml_content = """
name: flat_recipe
steps:
  - name: HEAT
    duration: 100
    profiles:
      jacket_temp:
        type: constant
        value: 300.0
"""
        f = tmp_path / "flat.yaml"
        f.write_text(yaml_content)
        proc = load_procedure(f)
        assert len(proc.unit_procedures) == 1
        assert len(proc.unit_procedures[0].operations) == 1
        assert proc.unit_procedures[0].operations[0].name == "BATCH"
        assert len(proc.phases_flat) == 1
        assert proc.phases_flat[0].name == "HEAT"

    def test_load_recipe_backward_compat(self, tmp_path: Path):
        yaml_content = """
name: test_proc
unit_procedures:
  - name: REACTOR_R101
    operations:
      - name: PREP
        phases:
          - name: INERT
            duration: 60
            profiles:
              jacket_temp: {type: constant, value: 298.15}
      - name: REACT
        phases:
          - name: HEAT
            duration: 300
            profiles:
              jacket_temp:
                type: linear_ramp
                start: 298.15
                end: 338.15
"""
        f = tmp_path / "proc.yaml"
        f.write_text(yaml_content)
        recipe = load_recipe(f)
        assert isinstance(recipe, Recipe)
        assert recipe.name == "test_proc"
        assert len(recipe.steps) == 2
        assert recipe.steps[0].name == "INERT"
        assert recipe.steps[1].name == "HEAT"

    def test_procedure_total_duration(self, tmp_path: Path):
        yaml_content = """
name: t
unit_procedures:
  - name: R
    operations:
      - name: OP1
        phases:
          - name: A
            duration: 60
            profiles:
              jacket_temp: {type: constant, value: 298.15}
      - name: OP2
        phases:
          - name: B
            duration: 300
            profiles:
              jacket_temp: {type: constant, value: 338.15}
"""
        f = tmp_path / "t.yaml"
        f.write_text(yaml_content)
        proc = load_procedure(f)
        assert proc.total_duration == 360.0
        assert proc.unit_procedures[0].operations[0].total_duration == 60.0
        assert proc.unit_procedures[0].operations[1].total_duration == 300.0

    def test_default_procedure_structure(self):
        recipe_path = Path(__file__).parent.parent / "recipes" / "default.yaml"
        proc = load_procedure(recipe_path)
        assert proc.name == "Default Cure Process"
        assert len(proc.unit_procedures) == 1
        up = proc.unit_procedures[0]
        assert len(up.operations) == 3
        assert up.operations[0].name == "PREPARATION"
        assert up.operations[1].name == "REACTION"
        assert up.operations[2].name == "DISCHARGE"
        assert len(proc.phases_flat) == 10
        assert proc.phases_flat[0].name == "INERT"
        assert proc.phases_flat[8].name == "DISCHARGE_PRODUCT"


class TestProcedurePlayer:
    @pytest.fixture
    def nested_proc(self) -> Procedure:
        return Procedure(
            name="test",
            unit_procedures=[UnitProcedure(
                name="R101",
                operations=[
                    Operation("PREP", phases=[
                        BatchStep("INERT", 10.0, {
                            "jacket_temp": ProfileSegment(ProfileType.CONSTANT, 298.15, 298.15, 10.0),
                        }),
                        BatchStep("CHARGE", 5.0, {
                            "jacket_temp": ProfileSegment(ProfileType.CONSTANT, 298.15, 298.15, 5.0),
                        }),
                    ]),
                    Operation("REACT", phases=[
                        BatchStep("HEAT", 20.0, {
                            "jacket_temp": ProfileSegment(ProfileType.LINEAR_RAMP, 298.15, 338.15, 20.0),
                        }),
                    ]),
                ],
            )],
        )

    def test_initial_state(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        assert player.current_phase_idx == 0
        assert not player.finished
        assert player.current_operation_name == "PREP"
        assert player.current_unit_procedure_name == "R101"
        assert player.current_step is not None
        assert player.current_step.name == "INERT"

    def test_tick_returns_values(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        values = player.tick(1.0)
        assert "jacket_temp" in values
        assert pytest.approx(values["jacket_temp"]) == 298.15

    def test_tick_return_type_identical(self, nested_proc: Procedure):
        """tick() must return dict[str, float|str] — same contract as RecipePlayer."""
        player = ProcedurePlayer(nested_proc)
        values = player.tick(1.0)
        for k, v in values.items():
            assert isinstance(k, str)
            assert isinstance(v, (float, int, str))

    def test_operation_name_tracks_phase_boundary(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        # Advance through PREP (10 + 5 = 15 seconds)
        for _ in range(15):
            player.tick(1.0)
        assert player.current_operation_name == "REACT"
        assert player.current_step is not None
        assert player.current_step.name == "HEAT"

    def test_current_step_idx_compat(self, nested_proc: Procedure):
        """current_step_idx is same as current_phase_idx (backward compat)."""
        player = ProcedurePlayer(nested_proc)
        assert player.current_step_idx == 0
        player.tick(1.0)
        assert player.current_step_idx == player.current_phase_idx

    def test_step_elapsed_compat(self, nested_proc: Procedure):
        """step_elapsed is same as phase_elapsed (backward compat)."""
        player = ProcedurePlayer(nested_proc)
        player.tick(3.0)
        assert pytest.approx(player.step_elapsed) == player.phase_elapsed

    def test_total_elapsed(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        for _ in range(12):
            player.tick(1.0)
        assert pytest.approx(player.total_elapsed) == 12.0

    def test_finished_returns_empty(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        for _ in range(40):
            player.tick(1.0)
        assert player.finished
        assert player.tick(1.0) == {}
        assert player.current_step is None
        assert player.current_operation_name is None

    def test_reset(self, nested_proc: Procedure):
        player = ProcedurePlayer(nested_proc)
        for _ in range(20):
            player.tick(1.0)
        player.reset()
        assert player.current_phase_idx == 0
        assert not player.finished
        assert player.current_operation_name == "PREP"

    def test_load_hot_swap(self, nested_proc: Procedure, tmp_path: Path):
        """player.load() hot-swaps to a new procedure and resets."""
        player = ProcedurePlayer(nested_proc)
        for _ in range(10):
            player.tick(1.0)
        yaml_content = """
name: new_recipe
steps:
  - name: STEP_A
    duration: 50
    profiles:
      jacket_temp: {type: constant, value: 300.0}
"""
        f = tmp_path / "new.yaml"
        f.write_text(yaml_content)
        new_proc = load_procedure(f)
        player.load(new_proc)
        assert player.current_phase_idx == 0
        assert not player.finished
        assert player.procedure.name == "new_recipe"
        assert player.current_operation_name == "BATCH"

    def test_flat_procedure_operation_name(self, tmp_path: Path):
        """Auto-wrapped flat recipe has operation name BATCH."""
        yaml_content = """
name: flat
steps:
  - name: S1
    duration: 10
    profiles:
      jacket_temp: {type: constant, value: 300.0}
"""
        f = tmp_path / "flat.yaml"
        f.write_text(yaml_content)
        proc = load_procedure(f)
        player = ProcedurePlayer(proc)
        assert player.current_operation_name == "BATCH"

    def test_em_modes_returned_as_strings(self):
        step = BatchStep(
            "TEST", 10.0,
            profiles={"jacket_temp": ProfileSegment(ProfileType.CONSTANT, 300.0, 300.0, 10.0)},
            em_modes={"em_mode:EM-FILL": "dose_component_a"},
        )
        proc = Procedure(
            name="t",
            unit_procedures=[UnitProcedure("R", [Operation("OP", [step])])],
        )
        player = ProcedurePlayer(proc)
        values = player.tick(1.0)
        assert values["em_mode:EM-FILL"] == "dose_component_a"
        assert isinstance(values["em_mode:EM-FILL"], str)

    def test_conditional_transition_then_else(self):
        phases = [
            BatchStep(
                "DECIDE", 1.0,
                profiles={"jacket_temp": ProfileSegment(ProfileType.CONSTANT, 300.0, 300.0, 1.0)},
                transitions=[{
                    "if": "conversion >= 0.9",
                    "then": "TARGET_HIGH",
                    "else": "TARGET_LOW",
                }],
            ),
            BatchStep("TARGET_LOW", 2.0, profiles={}),
            BatchStep("TARGET_HIGH", 2.0, profiles={}),
        ]
        proc = Procedure(
            name="branch",
            unit_procedures=[UnitProcedure("R", [Operation("OP", phases)])],
        )

        player = ProcedurePlayer(proc)
        player.tick(1.0, context={"conversion": 0.2})
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_LOW"

        player.reset()
        player.tick(1.0, context={"conversion": 0.95})
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_HIGH"

    def test_completion_guard_waits_for_em_active_mode(self):
        guarded = BatchStep(
            "CHARGE", 1.0,
            profiles={"jacket_temp": ProfileSegment(ProfileType.CONSTANT, 298.15, 298.15, 1.0)},
            completion_guards=[{
                "type": "em_mode_active",
                "em": "EM-FILL",
                "mode": "dose_component_a",
            }],
        )
        proc = Procedure(
            name="guarded",
            unit_procedures=[UnitProcedure("R", [Operation("OP", [guarded, BatchStep("NEXT", 1.0, {})])])],
        )
        player = ProcedurePlayer(proc)

        player.tick(1.5, context={
            "em_status": {
                "EM-FILL": {"mode": "dose_component_a", "state": "transitioning"},
            },
        })
        assert player.current_step is not None
        assert player.current_step.name == "CHARGE"

        player.tick(0.2, context={
            "em_status": {
                "EM-FILL": {"mode": "dose_component_a", "state": "active"},
            },
        })
        assert player.current_step is not None
        assert player.current_step.name == "NEXT"

    def test_compound_transition_condition_and_or_not(self):
        phases = [
            BatchStep(
                "DECIDE", 1.0,
                profiles={},
                transitions=[{
                    "if": "(temperature >= 350 AND conversion <= 0.8) OR NOT em_mode:EM-FILL:dose_component_a",
                    "then": "TARGET_HIGH",
                    "else": "TARGET_LOW",
                }],
            ),
            BatchStep("TARGET_LOW", 1.0, profiles={}),
            BatchStep("TARGET_HIGH", 1.0, profiles={}),
        ]
        proc = Procedure(
            name="branch-compound",
            unit_procedures=[UnitProcedure("R", [Operation("OP", phases)])],
        )

        player = ProcedurePlayer(proc)
        player.tick(1.0, context={
            "temperature": 351.0,
            "conversion": 0.7,
            "em_status": {"EM-FILL": {"mode": "dose_component_a", "state": "active"}},
        })
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_HIGH"

        player.reset()
        player.tick(1.0, context={
            "temperature": 330.0,
            "conversion": 0.9,
            "em_status": {"EM-FILL": {"mode": "dose_component_a", "state": "active"}},
        })
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_LOW"

    def test_compound_transition_condition_case_insensitive_operators(self):
        phases = [
            BatchStep(
                "DECIDE", 1.0,
                profiles={},
                transitions=[{
                    "if": "temperature >= 350 aNd nOt em_mode:EM-FILL:aus",
                    "then": "TARGET_HIGH",
                    "else": "TARGET_LOW",
                }],
            ),
            BatchStep("TARGET_LOW", 1.0, profiles={}),
            BatchStep("TARGET_HIGH", 1.0, profiles={}),
        ]
        proc = Procedure(
            name="branch-case",
            unit_procedures=[UnitProcedure("R", [Operation("OP", phases)])],
        )
        player = ProcedurePlayer(proc)
        player.tick(1.0, context={
            "temperature": 360.0,
            "em_status": {"EM-FILL": {"mode": "dose_component_a", "state": "active"}},
        })
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_HIGH"

    def test_invalid_transition_condition_warns_and_fails_closed(self, caplog):
        phases = [
            BatchStep(
                "DECIDE", 1.0,
                profiles={},
                transitions=[{
                    "if": "temperature >= 350 AND (conversion <= 0.8",
                    "then": "TARGET_HIGH",
                    "else": "TARGET_LOW",
                }],
            ),
            BatchStep("TARGET_LOW", 1.0, profiles={}),
            BatchStep("TARGET_HIGH", 1.0, profiles={}),
        ]
        proc = Procedure(
            name="branch-invalid",
            unit_procedures=[UnitProcedure("R", [Operation("OP", phases)])],
        )
        player = ProcedurePlayer(proc)

        player.tick(1.0, context={"temperature": 360.0, "conversion": 0.1})
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_LOW"
        assert "Invalid transition condition" in caplog.text

    def test_missing_transition_variable_warns_and_fails_closed(self, caplog):
        phases = [
            BatchStep(
                "DECIDE", 1.0,
                profiles={},
                transitions=[{
                    "if": "conversion >= 0.9",
                    "then": "TARGET_HIGH",
                    "else": "TARGET_LOW",
                }],
            ),
            BatchStep("TARGET_LOW", 1.0, profiles={}),
            BatchStep("TARGET_HIGH", 1.0, profiles={}),
        ]
        proc = Procedure(
            name="branch-missing",
            unit_procedures=[UnitProcedure("R", [Operation("OP", phases)])],
        )
        player = ProcedurePlayer(proc)

        player.tick(1.0, context={"temperature": 360.0})
        assert player.current_step is not None
        assert player.current_step.name == "TARGET_LOW"
        assert "Missing numeric context value" in caplog.text


class TestConditionSyntaxValidation:
    def test_invalid_transition_syntax_warns_at_load_time(self, tmp_path: Path):
        content = """
name: bad_transition
steps:
  - name: DECIDE
    duration: 5
    transitions:
      - if: "temperature >= 350 AND (conversion <= 0.8"
        then: "next"
    profiles:
      jacket_temp: {type: constant, value: 300.0}
"""
        f = tmp_path / "bad_transition.yaml"
        f.write_text(content)
        with pytest.warns(ConditionSyntaxWarning, match="Invalid transition condition syntax"):
            load_procedure(f)


class TestB2MML:
    def test_produces_valid_xml(self):
        import xml.etree.ElementTree as ET
        recipe_path = Path(__file__).parent.parent / "recipes" / "default.yaml"
        proc = load_procedure(recipe_path)
        xml_str = to_b2mml(proc)
        # Must parse without error
        root = ET.fromstring(xml_str)
        assert root is not None

    def test_phase_count(self):
        import xml.etree.ElementTree as ET
        recipe_path = Path(__file__).parent.parent / "recipes" / "default.yaml"
        proc = load_procedure(recipe_path)
        xml_str = to_b2mml(proc)
        root = ET.fromstring(xml_str)
        ns = {"b": "http://www.mesa.org/xml/B2MML"}
        segs = root.findall(".//b:OperationsSegment", ns)
        assert len(segs) == 10

    def test_phase_ids_match(self):
        import xml.etree.ElementTree as ET
        recipe_path = Path(__file__).parent.parent / "recipes" / "default.yaml"
        proc = load_procedure(recipe_path)
        xml_str = to_b2mml(proc)
        root = ET.fromstring(xml_str)
        ns = {"b": "http://www.mesa.org/xml/B2MML"}
        ids = [seg.findtext("b:ID", namespaces=ns) for seg in root.findall(".//b:OperationsSegment", ns)]
        expected = [p.name for p in proc.phases_flat]
        assert ids == expected

    def test_flat_recipe_also_works(self, tmp_path: Path):
        import xml.etree.ElementTree as ET
        yaml_content = """
name: simple
steps:
  - name: HEAT
    duration: 100
    profiles:
      jacket_temp: {type: constant, value: 300.0}
"""
        f = tmp_path / "simple.yaml"
        f.write_text(yaml_content)
        with pytest.warns(RecipeMetadataWarning):
            proc = load_procedure(f)
        xml_str = to_b2mml(proc)
        root = ET.fromstring(xml_str)
        ns = {"b": "http://www.mesa.org/xml/B2MML"}
        segs = root.findall(".//b:OperationsSegment", ns)
        assert len(segs) == 1


# ---------------------------------------------------------------------------
# ISA-88 Recipe Approval & Versioning (TODO Step 4)
# ---------------------------------------------------------------------------

_FULL_META_YAML = """
name: "Signed Recipe"
metadata:
  version: "2.0.0"
  author: "alice"
  approved_by: "bob"
  approval_date: "2026-03-03"
  change_log:
    - "2.0.0 (2026-03-03): initial"
steps:
  - name: HEAT
    duration: 60
    profiles:
      jacket_temp: {type: constant, value: 353.15}
"""

_NO_META_YAML = """
name: "Unsigned Recipe"
steps:
  - name: HEAT
    duration: 60
    profiles:
      jacket_temp: {type: constant, value: 353.15}
"""

_PARTIAL_META_YAML = """
name: "Partial Meta Recipe"
metadata:
  version: "1.0.0"
  author: "alice"
steps:
  - name: HEAT
    duration: 60
    profiles:
      jacket_temp: {type: constant, value: 353.15}
"""

_TEST_KEY = bytes.fromhex("a" * 64)  # 32 bytes, valid HMAC key


class TestRecipeApprovalMetadata:
    """Tests for ISA-88 recipe versioning, approval metadata, and HMAC-SHA256 signing."""

    # ------------------------------------------------------------------
    # Metadata loading
    # ------------------------------------------------------------------

    def test_metadata_loaded_from_yaml(self, tmp_path: Path):
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        proc = load_procedure(f)
        assert proc.metadata is not None
        assert proc.metadata.version == "2.0.0"
        assert proc.metadata.author == "alice"
        assert proc.metadata.approved_by == "bob"
        assert proc.metadata.approval_date == "2026-03-03"
        assert proc.metadata.change_log == ["2.0.0 (2026-03-03): initial"]

    def test_metadata_on_nested_yaml(self, tmp_path: Path):
        content = """
name: "Nested"
metadata:
  version: "1.1"
  author: "x"
  approved_by: "y"
  approval_date: "2026-01-01"
unit_procedures:
  - name: REACTOR_R101
    operations:
      - name: PREP
        phases:
          - name: INERT
            duration: 10
            profiles:
              jacket_temp: {type: constant, value: 298.15}
"""
        f = tmp_path / "nested.yaml"
        f.write_text(content)
        proc = load_procedure(f)
        assert proc.metadata is not None
        assert proc.metadata.version == "1.1"
        assert proc.metadata.approved_by == "y"

    # ------------------------------------------------------------------
    # Metadata warnings
    # ------------------------------------------------------------------

    def test_missing_metadata_warns(self, tmp_path: Path):
        f = tmp_path / "recipe.yaml"
        f.write_text(_NO_META_YAML)
        with pytest.warns(RecipeMetadataWarning, match="metadata missing"):
            load_procedure(f)

    def test_partial_metadata_warns(self, tmp_path: Path):
        f = tmp_path / "recipe.yaml"
        f.write_text(_PARTIAL_META_YAML)
        with pytest.warns(RecipeMetadataWarning, match="approved_by"):
            load_procedure(f)

    def test_full_metadata_no_warning(self, tmp_path: Path):
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", RecipeMetadataWarning)
            load_procedure(f)  # should not raise

    # ------------------------------------------------------------------
    # HMAC signing — YAML
    # ------------------------------------------------------------------

    def test_no_signature_accepted(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("REACTOR_RECIPE_KEY", "a" * 64)
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        proc = load_procedure(f)  # unsigned → accepted
        assert proc.name == "Signed Recipe"

    def test_valid_signature_accepted(self, tmp_path: Path, monkeypatch):
        import yaml as _yaml
        monkeypatch.setenv("REACTOR_RECIPE_KEY", "a" * 64)
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        sig = sign_recipe_yaml(f, _TEST_KEY)
        raw = _yaml.safe_load(f.read_text())
        raw["hmac_sha256"] = sig
        f.write_text(_yaml.dump(raw, default_flow_style=False, sort_keys=True, allow_unicode=True))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", RecipeMetadataWarning)
            proc = load_procedure(f)
        assert proc.name == "Signed Recipe"

    def test_invalid_signature_rejected(self, tmp_path: Path, monkeypatch):
        import yaml as _yaml
        monkeypatch.setenv("REACTOR_RECIPE_KEY", "a" * 64)
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        raw = _yaml.safe_load(f.read_text())
        raw["hmac_sha256"] = "deadbeef" * 8  # wrong digest
        f.write_text(_yaml.dump(raw, default_flow_style=False, sort_keys=True, allow_unicode=True))
        with pytest.raises(RecipeSignatureError, match="verification failed"):
            load_procedure(f)

    def test_signature_skipped_without_key(self, tmp_path: Path, monkeypatch):
        import yaml as _yaml
        monkeypatch.delenv("REACTOR_RECIPE_KEY", raising=False)
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        raw = _yaml.safe_load(f.read_text())
        raw["hmac_sha256"] = "deadbeef" * 8
        f.write_text(_yaml.dump(raw, default_flow_style=False, sort_keys=True, allow_unicode=True))
        with pytest.warns(RecipeMetadataWarning, match="REACTOR_RECIPE_KEY is not set"):
            proc = load_procedure(f)  # bad sig but no key → warn, accept
        assert proc.name == "Signed Recipe"

    def test_sign_recipe_yaml_utility(self, tmp_path: Path):
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        sig1 = sign_recipe_yaml(f, _TEST_KEY)
        sig2 = sign_recipe_yaml(f, _TEST_KEY)
        assert sig1 == sig2  # deterministic
        assert len(sig1) == 64  # sha256 hex digest

    def test_sign_ignores_existing_hmac_field(self, tmp_path: Path):
        """Signature must be invariant to an existing hmac_sha256 field in the file."""
        import yaml as _yaml
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        sig_clean = sign_recipe_yaml(f, _TEST_KEY)
        # Now embed a garbage signature and re-sign
        raw = _yaml.safe_load(f.read_text())
        raw["hmac_sha256"] = "aaaa"
        f.write_text(_yaml.dump(raw, default_flow_style=False, sort_keys=True, allow_unicode=True))
        sig_with = sign_recipe_yaml(f, _TEST_KEY)
        assert sig_clean == sig_with

    # ------------------------------------------------------------------
    # HMAC signing — XML
    # ------------------------------------------------------------------

    def test_xml_metadata_loaded(self, tmp_path: Path):
        xml_content = """<?xml version="1.0"?>
<recipe name="XML Test">
  <metadata>
    <version>3.0</version>
    <author>charlie</author>
    <approved_by>diana</approved_by>
    <approval_date>2026-03-03</approval_date>
    <change_log>3.0: initial</change_log>
  </metadata>
  <step name="HEAT" duration="60">
    <profile channel="jacket_temp" type="constant" value="353.15"/>
  </step>
</recipe>"""
        f = tmp_path / "recipe.xml"
        f.write_text(xml_content)
        proc = load_procedure(f)
        assert proc.metadata is not None
        assert proc.metadata.version == "3.0"
        assert proc.metadata.author == "charlie"
        assert proc.metadata.approved_by == "diana"

    def test_xml_no_metadata_gives_none(self, tmp_path: Path):
        xml_content = """<?xml version="1.0"?>
<recipe name="Plain XML">
  <step name="HEAT" duration="60">
    <profile channel="jacket_temp" type="constant" value="353.15"/>
  </step>
</recipe>"""
        f = tmp_path / "recipe.xml"
        f.write_text(xml_content)
        proc = load_procedure(f)
        assert proc.metadata is None

    def test_xml_valid_signature_accepted(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("REACTOR_RECIPE_KEY", "a" * 64)
        xml_content = """<?xml version="1.0"?>
<recipe name="Signed XML">
  <metadata><version>1.0</version><author>x</author><approved_by>y</approved_by><approval_date>2026-03-03</approval_date></metadata>
  <step name="HEAT" duration="60">
    <profile channel="jacket_temp" type="constant" value="353.15"/>
  </step>
</recipe>"""
        f = tmp_path / "recipe.xml"
        f.write_text(xml_content)
        sig = sign_recipe_xml(f, _TEST_KEY)
        # Inject valid signature
        import xml.etree.ElementTree as ET
        tree = ET.parse(f)
        root = tree.getroot()
        sig_el = ET.SubElement(root, "hmac_sha256")
        sig_el.text = sig
        tree.write(str(f), encoding="unicode", xml_declaration=True)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", RecipeMetadataWarning)
            proc = load_procedure(f)
        assert proc.name == "Signed XML"

    def test_xml_invalid_signature_rejected(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("REACTOR_RECIPE_KEY", "a" * 64)
        xml_content = """<?xml version="1.0"?>
<recipe name="Tampered XML">
  <hmac_sha256>deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef</hmac_sha256>
  <step name="HEAT" duration="60">
    <profile channel="jacket_temp" type="constant" value="353.15"/>
  </step>
</recipe>"""
        f = tmp_path / "recipe.xml"
        f.write_text(xml_content)
        with pytest.raises(RecipeSignatureError, match="verification failed"):
            load_procedure(f)

    # ------------------------------------------------------------------
    # B2MML metadata output
    # ------------------------------------------------------------------

    def test_b2mml_emits_metadata(self, tmp_path: Path):
        import xml.etree.ElementTree as ET
        f = tmp_path / "recipe.yaml"
        f.write_text(_FULL_META_YAML)
        proc = load_procedure(f)
        xml_str = to_b2mml(proc)
        root = ET.fromstring(xml_str)
        ns = {"b": "http://www.mesa.org/xml/B2MML"}
        header = root.find("b:RecipeHeader", ns)
        assert header is not None
        assert header.findtext("b:Version", namespaces=ns) == "2.0.0"
        assert header.findtext("b:Author", namespaces=ns) == "alice"
        assert header.findtext("b:ApprovedBy", namespaces=ns) == "bob"
        assert header.findtext("b:ApprovalDate", namespaces=ns) == "2026-03-03"
        assert header.findtext("b:ChangeLog", namespaces=ns) == "2.0.0 (2026-03-03): initial"

    def test_b2mml_no_header_without_metadata(self, tmp_path: Path):
        import xml.etree.ElementTree as ET
        f = tmp_path / "recipe.yaml"
        f.write_text(_NO_META_YAML)
        with pytest.warns(RecipeMetadataWarning):
            proc = load_procedure(f)
        xml_str = to_b2mml(proc)
        root = ET.fromstring(xml_str)
        ns = {"b": "http://www.mesa.org/xml/B2MML"}
        header = root.find("b:RecipeHeader", ns)
        assert header is None  # no metadata → no header element
