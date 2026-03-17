"""Unit tests for pluggable energy balance models."""

import pytest

from reactor.energy_models import (
    AdiabaticModel,
    EnergyModel,
    ExtendedEnergyModel,
    FullEnergyModel,
    IsothermalModel,
    ENERGY_REGISTRY,
    build_energy_model,
    register_energy_model,
)


class TestIsothermalModel:
    def test_returns_zero(self):
        model = IsothermalModel()
        assert model.compute_dT_dt(100.0, 50.0, 10.0, 80.0, 1.8) == 0.0

    def test_ignores_all_inputs(self):
        model = IsothermalModel()
        assert model.compute_dT_dt(0.0, 0.0, 0.0, 0.0, 0.0) == 0.0
        assert model.compute_dT_dt(1e6, -1e6, 1e6, 1.0, 1.0) == 0.0


class TestAdiabaticModel:
    def test_exothermic_positive_dT(self):
        model = AdiabaticModel()
        # Q_rxn = 100 kW, m = 80 kg, Cp = 1.8 kJ/(kg·K)
        dT = model.compute_dT_dt(Q_rxn=100.0, Q_jacket=50.0, Q_frictional=10.0,
                                  m_total=80.0, Cp=1.8)
        # Should only use Q_rxn, ignore Q_jacket and Q_frictional
        expected = 100.0 / (80.0 * 1.8)
        assert pytest.approx(dT) == expected

    def test_ignores_jacket_heat(self):
        model = AdiabaticModel()
        dT_with_jacket = model.compute_dT_dt(100.0, 1000.0, 0.0, 80.0, 1.8)
        dT_no_jacket = model.compute_dT_dt(100.0, 0.0, 0.0, 80.0, 1.8)
        assert pytest.approx(dT_with_jacket) == dT_no_jacket

    def test_zero_mass_raises(self):
        """m_total=0 is a caller error; no silent guard (required for Pyomo compatibility)."""
        model = AdiabaticModel()
        with pytest.raises(ZeroDivisionError):
            model.compute_dT_dt(100.0, 50.0, 10.0, 0.0, 1.8)


class TestFullEnergyModel:
    def test_heating_from_jacket(self):
        model = FullEnergyModel()
        # Only jacket heat (no reaction)
        dT = model.compute_dT_dt(Q_rxn=0.0, Q_jacket=50.0, Q_frictional=0.0,
                                  m_total=80.0, Cp=1.8)
        expected = 50.0 / (80.0 * 1.8)
        assert pytest.approx(dT) == expected

    def test_combined_rxn_and_jacket(self):
        model = FullEnergyModel()
        dT = model.compute_dT_dt(Q_rxn=100.0, Q_jacket=-30.0, Q_frictional=5.0,
                                  m_total=80.0, Cp=1.8)
        # Full model ignores frictional
        expected = (100.0 + (-30.0)) / (80.0 * 1.8)
        assert pytest.approx(dT) == expected

    def test_ignores_frictional(self):
        model = FullEnergyModel()
        dT_with = model.compute_dT_dt(100.0, 50.0, 999.0, 80.0, 1.8)
        dT_without = model.compute_dT_dt(100.0, 50.0, 0.0, 80.0, 1.8)
        assert pytest.approx(dT_with) == dT_without

    def test_zero_mass_raises(self):
        """m_total=0 is a caller error; no silent guard (required for Pyomo compatibility)."""
        model = FullEnergyModel()
        with pytest.raises(ZeroDivisionError):
            model.compute_dT_dt(100.0, 50.0, 10.0, 0.0, 1.8)


class TestExtendedEnergyModel:
    def test_includes_frictional(self):
        model = ExtendedEnergyModel()
        dT = model.compute_dT_dt(Q_rxn=100.0, Q_jacket=-30.0, Q_frictional=5.0,
                                  m_total=80.0, Cp=1.8)
        expected = (100.0 + (-30.0) + 5.0) / (80.0 * 1.8)
        assert pytest.approx(dT) == expected

    def test_differs_from_full_when_frictional(self):
        extended = ExtendedEnergyModel()
        full = FullEnergyModel()
        dT_ext = extended.compute_dT_dt(100.0, 50.0, 10.0, 80.0, 1.8)
        dT_full = full.compute_dT_dt(100.0, 50.0, 10.0, 80.0, 1.8)
        assert dT_ext > dT_full  # Extended includes frictional heating

    def test_matches_full_when_no_frictional(self):
        extended = ExtendedEnergyModel()
        full = FullEnergyModel()
        dT_ext = extended.compute_dT_dt(100.0, 50.0, 0.0, 80.0, 1.8)
        dT_full = full.compute_dT_dt(100.0, 50.0, 0.0, 80.0, 1.8)
        assert pytest.approx(dT_ext) == dT_full


class TestModelHierarchy:
    """Verify model ordering for same input."""

    def test_isothermal_always_zero(self):
        iso = IsothermalModel()
        assert iso.compute_dT_dt(100.0, 50.0, 10.0, 80.0, 1.8) == 0.0

    def test_adiabatic_highest_dT(self):
        """Adiabatic should give highest dT for exothermic + cooling scenario."""
        adiabatic = AdiabaticModel()
        full = FullEnergyModel()

        # Exothermic reaction with cooling jacket
        Q_rxn = 100.0
        Q_jacket = -30.0  # Cooling
        m, Cp = 80.0, 1.8

        dT_adi = adiabatic.compute_dT_dt(Q_rxn, Q_jacket, 0.0, m, Cp)
        dT_full = full.compute_dT_dt(Q_rxn, Q_jacket, 0.0, m, Cp)

        # Adiabatic ignores cooling -> higher temperature rise
        assert dT_adi > dT_full


class TestRegistry:
    def test_all_models_registered(self):
        assert "isothermal" in ENERGY_REGISTRY
        assert "adiabatic" in ENERGY_REGISTRY
        assert "full" in ENERGY_REGISTRY
        assert "extended" in ENERGY_REGISTRY

    def test_build_known_model(self):
        model = build_energy_model("full")
        assert isinstance(model, FullEnergyModel)

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown energy model"):
            build_energy_model("nonexistent")

    def test_register_custom_model(self):
        class Custom(EnergyModel):
            def compute_dT_dt(self, Q_rxn, Q_jacket, Q_frictional, m_total, Cp):
                return 42.0

        register_energy_model("test_custom", Custom)
        assert "test_custom" in ENERGY_REGISTRY
        model = build_energy_model("test_custom")
        assert model.compute_dT_dt(0, 0, 0, 1, 1) == 42.0
        del ENERGY_REGISTRY["test_custom"]
