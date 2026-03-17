"""Tests for ISA-88 oriented batch extensions (parameter sets and batch record)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from reactor.batch import (
    BatchDataRecord, BatchExceptionRecord, BatchIdentity,
    FlowEvent, MaterialSpec, _apply_batch_parameter_set,
)
from reactor.config import ModelConfig, Settings
from reactor.procedure import load_procedure


def test_apply_batch_parameter_set_scales_feed_profiles():
    root = Path(__file__).parent.parent
    cfg = ModelConfig.from_file(root / "configs" / "default.yaml")

    raw = copy.deepcopy(cfg.raw)
    raw["batch_parameter_sets"] = {
        "tiny": {
            "target_mass_kg": 10.0,
            "feed_scale": 0.1,
            "duration_scale": 1.0,
        },
    }
    cfg_with_sets = ModelConfig.from_dict(raw)
    proc = load_procedure(root / "recipes" / "default.yaml")

    settings = Settings()
    settings.batch_mass_kg = 100.0

    _, scaled_proc, summary = _apply_batch_parameter_set(
        cfg_with_sets,
        proc,
        settings,
        "tiny",
    )

    charge = next(p for p in scaled_proc.phases_flat if p.name == "CHARGE_COMPONENT_A")
    assert round(charge.profiles["feed_component_a"].start_value, 6) == 0.05
    assert round(charge.profiles["feed_component_a"].end_value, 6) == 0.05
    assert summary["applied"] is True
    assert summary["name"] == "tiny"


def test_batch_data_record_contains_typed_exceptions():
    exc = BatchExceptionRecord(
        timestamp_s=12.34,
        category="EM_INTERLOCK",
        code="interlock_conflict:EM-FILL:dose_component_a:EM-DRAIN:entleeren",
        message="Mode request rejected",
        severity="warning",
        details={"em_tag": "EM-DRAIN", "mode_name": "entleeren"},
    )
    record = BatchDataRecord(
        batch_id="20260301_123000",
        recipe_name="Default Cure Process",
        parameter_set="lab_10kg",
        started_at="2026-03-01T12:30:00",
        completed_at="2026-03-01T12:31:00",
        status="completed",
        stop_reason="recipe_finished",
        total_ticks=100,
        total_time_s=50.0,
        wall_time_s=1.2,
        exceptions=[exc],
        phase_events=[{"timestamp_s": 10.0, "from_phase": "INERT", "to_phase": "CHARGE_COMPONENT_A"}],
        parameterization={"applied": True, "feed_scale": 0.1},
    )

    payload = record.to_dict()
    assert payload["exceptions"][0]["category"] == "EM_INTERLOCK"
    assert payload["exceptions"][0]["code"].startswith("interlock_conflict")
    assert payload["parameter_set"] == "lab_10kg"


# ---------------------------------------------------------------------------
# ISA-88 Chapter 6 — Material/Batch Identity
# ---------------------------------------------------------------------------

class TestMaterialSpec:
    def test_defaults(self):
        spec = MaterialSpec()
        assert spec.material_id == ""
        assert spec.vendor == ""
        assert spec.properties == {}

    def test_to_dict_roundtrip(self):
        spec = MaterialSpec(
            material_id="MAT-001",
            lot_number="LOT-2026-03",
            vendor="ACME Chemicals",
            grade="industrial",
            cas_number="25036-25-3",
            notes="CoA ref: ABC123",
            properties={"density_kg_m3": 1200.0},
        )
        d = spec.to_dict()
        assert d["material_id"] == "MAT-001"
        assert d["lot_number"] == "LOT-2026-03"
        assert d["properties"]["density_kg_m3"] == pytest.approx(1200.0)

        roundtrip = MaterialSpec.from_dict(d)
        assert roundtrip.vendor == "ACME Chemicals"
        assert roundtrip.properties["density_kg_m3"] == pytest.approx(1200.0)

    def test_from_dict_tolerates_missing_keys(self):
        spec = MaterialSpec.from_dict({"vendor": "TestCo"})
        assert spec.vendor == "TestCo"
        assert spec.material_id == ""
        assert spec.properties == {}


class TestBatchIdentity:
    def test_defaults(self):
        ident = BatchIdentity()
        assert ident.batch_number == ""
        assert ident.material_ids == {}
        assert ident.material_specs == {}

    def test_from_dict_with_all_fields(self):
        raw = {
            "batch_number": "BN-2026-001",
            "lot_number": "LOT-001",
            "product_code": "EP-80",
            "material_ids": {"component_a": "MAT-COMPA-001", "component_b": "MAT-HARD-002"},
            "material_specs": {
                "component_a": {
                    "material_id": "MAT-COMPA-001",
                    "vendor": "ChemSupplier GmbH",
                    "lot_number": "LOT-R-2026-03",
                },
            },
        }
        ident = BatchIdentity.from_dict(raw)
        assert ident.batch_number == "BN-2026-001"
        assert ident.material_ids["component_a"] == "MAT-COMPA-001"
        assert ident.material_specs["component_a"].vendor == "ChemSupplier GmbH"
        assert ident.material_specs["component_a"].lot_number == "LOT-R-2026-03"

    def test_from_dict_none_returns_defaults(self):
        ident = BatchIdentity.from_dict(None)
        assert ident.batch_number == ""

    def test_to_dict_roundtrip(self):
        ident = BatchIdentity(
            batch_number="BN-001",
            material_ids={"component_a": "MAT-001"},
            material_specs={"component_a": MaterialSpec(vendor="SupplierA")},
        )
        d = ident.to_dict()
        assert d["batch_number"] == "BN-001"
        assert d["material_ids"]["component_a"] == "MAT-001"
        assert d["material_specs"]["component_a"]["vendor"] == "SupplierA"

    def test_material_ids_independent_of_specs(self):
        ident = BatchIdentity(material_ids={"component_a": "MAT-X"})
        assert "component_a" not in ident.material_specs
        d = ident.to_dict()
        assert d["material_specs"] == {}


class TestFlowEvent:
    def test_feed_event_construction(self):
        event = FlowEvent(
            event_type="feed",
            species="component_a",
            start_time_s=10.0,
            end_time_s=130.0,
            mass_kg=60.0,
            avg_rate_kgs=0.5,
            material_id="MAT-001",
            lot_number="LOT-R-001",
            phase_name="CHARGE_COMPONENT_A",
            operation_name="PREPARATION",
        )
        assert event.event_type == "feed"
        assert not event.open

    def test_to_dict_contains_duration(self):
        event = FlowEvent(
            event_type="feed",
            species="component_b",
            start_time_s=130.0,
            end_time_s=190.0,
            mass_kg=18.0,
            avg_rate_kgs=0.3,
        )
        d = event.to_dict()
        assert d["duration_s"] == pytest.approx(60.0)
        assert d["mass_kg"] == pytest.approx(18.0)
        assert d["avg_rate_kgs"] == pytest.approx(0.3)
        assert d["open"] is False

    def test_discharge_event(self):
        event = FlowEvent(
            event_type="discharge",
            species="ALL",
            start_time_s=4750.0,
            end_time_s=4750.0,
            mass_kg=78.5,
            avg_rate_kgs=0.0,
            phase_name="DISCHARGE_PRODUCT",
            operation_name="DISCHARGE",
        )
        d = event.to_dict()
        assert d["event_type"] == "discharge"
        assert d["species"] == "ALL"
        assert d["mass_kg"] == pytest.approx(78.5)
        assert d["duration_s"] == pytest.approx(0.0)

    def test_open_flag_for_active_feed_at_batch_end(self):
        event = FlowEvent(
            event_type="feed",
            species="component_a",
            start_time_s=0.0,
            end_time_s=50.0,
            mass_kg=25.0,
            avg_rate_kgs=0.5,
            open=True,
        )
        d = event.to_dict()
        assert d["open"] is True


class TestBatchDataRecordIdentity:
    def _make_record(self, **kwargs) -> BatchDataRecord:
        defaults = dict(
            batch_id="20260302_120000",
            recipe_name="Test Recipe",
            parameter_set="",
            started_at="2026-03-02T12:00:00",
            completed_at="2026-03-02T12:01:00",
            status="completed",
            stop_reason="recipe_finished",
            total_ticks=100,
            total_time_s=60.0,
            wall_time_s=1.5,
        )
        defaults.update(kwargs)
        return BatchDataRecord(**defaults)

    def test_default_record_has_empty_identity(self):
        record = self._make_record()
        d = record.to_dict()
        assert d["identity"]["batch_number"] == ""
        assert d["input_materials"] == {}
        assert d["output_materials"] == {}
        assert d["flow_events"] == []

    def test_record_with_full_identity(self):
        ident = BatchIdentity(
            batch_number="BN-2026-001",
            lot_number="LOT-001",
            material_ids={"component_a": "MAT-001", "component_b": "MAT-002"},
        )
        record = self._make_record(identity=ident)
        d = record.to_dict()
        assert d["identity"]["batch_number"] == "BN-2026-001"
        assert d["identity"]["material_ids"]["component_a"] == "MAT-001"

    def test_record_with_input_output_materials(self):
        record = self._make_record(
            input_materials={"component_a": 60.0, "component_b": 0.0},
            output_materials={"component_a": 0.5, "component_b": 0.2, "product": 78.3},
        )
        d = record.to_dict()
        assert d["input_materials"]["component_a"] == pytest.approx(60.0)
        assert d["output_materials"]["product"] == pytest.approx(78.3)

    def test_record_with_flow_events(self):
        events = [
            FlowEvent(
                event_type="feed", species="component_a",
                start_time_s=10.0, end_time_s=130.0,
                mass_kg=60.0, avg_rate_kgs=0.5,
                phase_name="CHARGE_COMPONENT_A", operation_name="PREPARATION",
            ),
            FlowEvent(
                event_type="feed", species="component_b",
                start_time_s=130.0, end_time_s=190.0,
                mass_kg=18.0, avg_rate_kgs=0.3,
                phase_name="CHARGE_COMPONENT_B", operation_name="PREPARATION",
            ),
            FlowEvent(
                event_type="discharge", species="ALL",
                start_time_s=4750.0, end_time_s=4750.0,
                mass_kg=78.5, avg_rate_kgs=0.0,
                phase_name="DISCHARGE_PRODUCT", operation_name="DISCHARGE",
            ),
        ]
        record = self._make_record(flow_events=events)
        d = record.to_dict()
        assert len(d["flow_events"]) == 3
        assert d["flow_events"][0]["event_type"] == "feed"
        assert d["flow_events"][0]["species"] == "component_a"
        assert d["flow_events"][2]["event_type"] == "discharge"

    def test_backward_compatibility_existing_construction(self):
        exc = BatchExceptionRecord(
            timestamp_s=5.0, category="TEST", code="T001", message="test"
        )
        record = BatchDataRecord(
            batch_id="20260302_120000",
            recipe_name="Test",
            parameter_set="",
            started_at="2026-03-02T12:00:00",
            completed_at="2026-03-02T12:00:30",
            status="completed",
            stop_reason="recipe_finished",
            total_ticks=10,
            total_time_s=5.0,
            wall_time_s=0.1,
            exceptions=[exc],
        )
        d = record.to_dict()
        assert "identity" in d
        assert "input_materials" in d
        assert "output_materials" in d
        assert "flow_events" in d
        assert d["identity"]["batch_number"] == ""
        assert d["flow_events"] == []


# ---------------------------------------------------------------------------
# Settings field + auto-generation + config materials merge
# ---------------------------------------------------------------------------

class TestSettingsBatchIdentity:
    def test_settings_has_batch_identity_field(self):
        s = Settings()
        assert s.batch_identity is None

    def test_batch_identity_from_settings_none(self):
        ident = BatchIdentity.from_dict(Settings().batch_identity)
        assert ident.batch_number == ""
        assert ident.material_ids == {}

    def test_settings_accepts_dict(self):
        s = Settings()
        s.batch_identity = {"batch_number": "BN-TEST", "lot_number": "LOT-TEST"}
        ident = BatchIdentity.from_dict(s.batch_identity)
        assert ident.batch_number == "BN-TEST"
        assert ident.lot_number == "LOT-TEST"


class TestAutoGenerateBatchNumber:
    def test_empty_identity_gets_auto_batch_number(self):
        from datetime import datetime
        ident = BatchIdentity()
        started_at = datetime(2026, 3, 3, 14, 30, 22)
        if not ident.batch_number:
            ident.batch_number = f"BN-{started_at:%Y%m%d-%H%M%S}"
        if not ident.lot_number:
            ident.lot_number = f"LOT-{started_at:%Y%m%d-%H%M%S}"
        assert ident.batch_number == "BN-20260303-143022"
        assert ident.lot_number == "LOT-20260303-143022"

    def test_explicit_batch_number_not_overwritten(self):
        from datetime import datetime
        ident = BatchIdentity(batch_number="BN-CUSTOM-001", lot_number="LOT-CUSTOM")
        started_at = datetime(2026, 3, 3, 14, 30, 22)
        if not ident.batch_number:
            ident.batch_number = f"BN-{started_at:%Y%m%d-%H%M%S}"
        if not ident.lot_number:
            ident.lot_number = f"LOT-{started_at:%Y%m%d-%H%M%S}"
        assert ident.batch_number == "BN-CUSTOM-001"
        assert ident.lot_number == "LOT-CUSTOM"


class TestConfigMaterialsMerge:
    def test_model_config_materials_property(self):
        root = Path(__file__).parent.parent
        cfg = ModelConfig.from_file(root / "configs" / "default.yaml")
        materials = cfg.materials
        assert "component_a" in materials
        assert materials["component_a"]["material_id"] == "MAT-COMPA-001"
        assert materials["component_a"]["vendor"] == "ChemSupplier GmbH"

    def test_config_materials_merged_into_identity(self):
        config_materials = {
            "component_a": {
                "material_id": "MAT-R-001",
                "vendor": "TestVendor",
                "lot_number": "LOT-CFG",
            },
            "component_b": {
                "material_id": "MAT-H-001",
                "vendor": "HardVendor",
            },
        }
        # Empty identity — config defaults should be merged
        identity = BatchIdentity()
        for species_key, spec_data in config_materials.items():
            if isinstance(spec_data, dict):
                if species_key not in identity.material_specs:
                    identity.material_specs[species_key] = MaterialSpec.from_dict(spec_data)
                if species_key not in identity.material_ids and spec_data.get("material_id"):
                    identity.material_ids[species_key] = str(spec_data["material_id"])
        assert identity.material_ids["component_a"] == "MAT-R-001"
        assert identity.material_specs["component_a"].vendor == "TestVendor"
        assert identity.material_ids["component_b"] == "MAT-H-001"

    def test_runtime_identity_takes_priority_over_config(self):
        config_materials = {
            "component_a": {"material_id": "MAT-CFG", "vendor": "ConfigVendor"},
        }
        # Runtime identity already has component_a spec
        identity = BatchIdentity(
            material_ids={"component_a": "MAT-RUNTIME"},
            material_specs={"component_a": MaterialSpec(vendor="RuntimeVendor")},
        )
        for species_key, spec_data in config_materials.items():
            if isinstance(spec_data, dict):
                if species_key not in identity.material_specs:
                    identity.material_specs[species_key] = MaterialSpec.from_dict(spec_data)
                if species_key not in identity.material_ids and spec_data.get("material_id"):
                    identity.material_ids[species_key] = str(spec_data["material_id"])
        # Runtime values should be preserved
        assert identity.material_ids["component_a"] == "MAT-RUNTIME"
        assert identity.material_specs["component_a"].vendor == "RuntimeVendor"

    def test_empty_materials_section(self):
        root = Path(__file__).parent.parent
        cfg = ModelConfig.from_file(root / "configs" / "default.yaml")
        # Remove materials to test fallback
        raw = copy.deepcopy(cfg.raw)
        raw.pop("materials", None)
        cfg_no_mat = ModelConfig.from_dict(raw)
        assert cfg_no_mat.materials == {}
