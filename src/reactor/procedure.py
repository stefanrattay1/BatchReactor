"""ISA-88 / IEC 61512 procedure hierarchy: Procedure → UnitProcedure → Operation → Phase.

Phase is a type alias for BatchStep; the hierarchy is layered on top of the
existing recipe data model.  ProcedurePlayer is a drop-in replacement for
RecipePlayer with identical tick() semantics plus two new positional properties:
current_operation_name and current_unit_procedure_name.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import operator
import os
import re
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .condition_expression import (
    ConditionParseError,
    evaluate_condition_ast,
    parse_condition_expression,
)
from .recipe import BatchStep, Recipe, _parse_batch_step


# ---------------------------------------------------------------------------
# Recipe approval & versioning (ISA-88 §4.3)
# ---------------------------------------------------------------------------

class RecipeMetadataWarning(UserWarning):
    """Issued when recipe metadata (version, author, approval) is absent or incomplete."""


class RecipeSignatureError(ValueError):
    """Raised when HMAC-SHA256 verification of a signed recipe file fails."""


@dataclass
class RecipeMetadata:
    """Version, authorship, and approval fields for an ISA-88 recipe."""

    version: str = ""
    author: str = ""
    approved_by: str = ""
    approval_date: str = ""   # ISO-8601 date string, e.g. "2026-03-03"
    change_log: list[str] = field(default_factory=list)

# ISA-88 naming alias; no new class needed – BatchStep IS an ISA-88 Phase.
Phase = BatchStep

logger = logging.getLogger("reactor.procedure")


@dataclass
class Operation:
    """ISA-88 Operation: a named group of Phases executed on one unit."""

    name: str
    phases: list[BatchStep] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(p.duration for p in self.phases)


@dataclass
class UnitProcedure:
    """ISA-88 UnitProcedure: a sequence of Operations performed on one process unit."""

    name: str
    operations: list[Operation] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(op.total_duration for op in self.operations)

    @property
    def phases_flat(self) -> list[BatchStep]:
        """All phases in execution order across all operations."""
        phases: list[BatchStep] = []
        for op in self.operations:
            phases.extend(op.phases)
        return phases


@dataclass
class Procedure:
    """ISA-88 Procedure: a complete batch recipe expressed as a hierarchy."""

    name: str
    unit_procedures: list[UnitProcedure] = field(default_factory=list)
    metadata: RecipeMetadata | None = None

    @property
    def total_duration(self) -> float:
        return sum(up.total_duration for up in self.unit_procedures)

    @property
    def phases_flat(self) -> list[BatchStep]:
        """All phases in execution order, flattened across all UPs and Operations."""
        phases: list[BatchStep] = []
        for up in self.unit_procedures:
            phases.extend(up.phases_flat)
        return phases

    @property
    def channels(self) -> set[str]:
        channels: set[str] = set()
        for phase in self.phases_flat:
            channels.update(phase.profiles.keys())
        return channels


class ProcedurePlayer:
    """Plays a Procedure phase-by-phase with hierarchy awareness.

    Drop-in replacement for RecipePlayer:
    - tick(dt) return type is identical: dict[str, float | str]
    - current_step, current_step_idx, step_elapsed, total_elapsed, finished,
      and reset() are all backward-compatible with RecipePlayer.
    - New: current_operation_name, current_unit_procedure_name

    Internal: _phase_to_op is a pre-built flat index mapping each phase
    position to (up_name, op_name) for O(1) lookup during tick.
    """

    def __init__(self, procedure: Procedure) -> None:
        self.procedure = procedure
        self._phases: list[BatchStep] = []
        self._phase_to_op: list[tuple[str, str]] = []
        self._phase_name_to_index: dict[str, int] = {}
        self._build_index()
        self.current_phase_idx: int = 0
        self.phase_elapsed: float = 0.0
        self.finished: bool = False

    def _build_index(self) -> None:
        self._phases = self.procedure.phases_flat
        self._phase_to_op = []
        self._phase_name_to_index = {}
        for up in self.procedure.unit_procedures:
            for op in up.operations:
                for phase in op.phases:
                    self._phase_to_op.append((up.name, op.name))
                    if phase.name not in self._phase_name_to_index:
                        self._phase_name_to_index[phase.name] = len(self._phase_to_op) - 1

    def load(self, procedure: Procedure) -> None:
        """Hot-swap to a new procedure and reset to the beginning."""
        self.procedure = procedure
        self._build_index()
        self.reset()

    # ------------------------------------------------------------------
    # Backward-compatible properties (same names as RecipePlayer)
    # ------------------------------------------------------------------

    @property
    def current_step(self) -> BatchStep | None:
        if self.finished or self.current_phase_idx >= len(self._phases):
            return None
        return self._phases[self.current_phase_idx]

    @property
    def current_step_idx(self) -> int:
        return self.current_phase_idx

    @property
    def step_elapsed(self) -> float:
        return self.phase_elapsed

    @property
    def total_elapsed(self) -> float:
        elapsed = sum(p.duration for p in self._phases[: self.current_phase_idx])
        return elapsed + self.phase_elapsed

    # ------------------------------------------------------------------
    # ISA-88 positional properties
    # ------------------------------------------------------------------

    @property
    def current_operation_name(self) -> str | None:
        if self.finished or self.current_phase_idx >= len(self._phase_to_op):
            return None
        return self._phase_to_op[self.current_phase_idx][1]

    @property
    def current_unit_procedure_name(self) -> str | None:
        if self.finished or self.current_phase_idx >= len(self._phase_to_op):
            return None
        return self._phase_to_op[self.current_phase_idx][0]

    # ------------------------------------------------------------------
    # Core tick / reset
    # ------------------------------------------------------------------

    def tick(
        self,
        dt: float,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, float | str]:
        """Advance by dt seconds and return current channel values.

        Return type is identical to RecipePlayer.tick(): dict[str, float | str].
        Numeric channels return floats; em_mode:* channels return strings.
        """
        if self.finished:
            return {}

        phase = self.current_step
        if phase is None:
            self.finished = True
            return {}

        values: dict[str, float | str] = {}
        for channel, profile in phase.profiles.items():
            values[channel] = profile.evaluate(self.phase_elapsed)
        for channel, mode_name in phase.em_modes.items():
            values[channel] = mode_name

        self.phase_elapsed += dt
        transition_guard = 0
        while self.phase_elapsed >= phase.duration:
            transition_guard += 1
            if transition_guard > max(4, len(self._phases) * 2):
                break

            if not self._can_complete_phase(phase, context):
                self.phase_elapsed = phase.duration
                break

            overflow = self.phase_elapsed - phase.duration
            next_idx = self.current_phase_idx + 1

            branch_idx = self._evaluate_phase_transition(phase, context)
            if branch_idx is not None:
                next_idx = branch_idx

            self.current_phase_idx = next_idx
            self.phase_elapsed = max(overflow, 0.0)

            if self.current_phase_idx >= len(self._phases):
                self.finished = True
                break
            phase = self._phases[self.current_phase_idx]

        return values

    def _can_complete_phase(
        self,
        phase: BatchStep,
        context: dict[str, Any] | None,
    ) -> bool:
        guards = phase.completion_guards or []
        if not guards:
            return True

        em_status = {}
        if context is not None:
            em_status = context.get("em_status", {}) or {}

        for guard in guards:
            if not isinstance(guard, dict):
                continue

            guard_type = str(guard.get("type", "")).strip().lower()
            if guard_type != "em_mode_active":
                continue

            em_tag = str(guard.get("em", "")).strip()
            mode_name = str(guard.get("mode", "")).strip()
            if not em_tag or not mode_name:
                continue

            em = em_status.get(em_tag)
            if not isinstance(em, dict):
                return False

            if str(em.get("state", "")).lower() != "active":
                return False
            if str(em.get("mode", "")) != mode_name:
                return False

        return True

    def _evaluate_phase_transition(
        self,
        phase: BatchStep,
        context: dict[str, Any] | None,
    ) -> int | None:
        transitions = phase.transitions or []
        for transition in transitions:
            if not isinstance(transition, dict):
                continue

            condition = str(transition.get("if", "")).strip()
            then_target = transition.get("then")
            else_target = transition.get("else")

            if not condition or then_target is None:
                continue

            is_true = self._evaluate_condition(condition, context)
            target = then_target if is_true else else_target
            if target is None:
                continue
            idx = self._resolve_transition_target(target)
            if idx is not None:
                return idx
        return None

    def _resolve_transition_target(self, target: Any) -> int | None:
        if isinstance(target, int):
            if 0 <= target < len(self._phases):
                return target
            return None

        target_txt = str(target).strip()
        if not target_txt:
            return None
        if target_txt.lower() == "next":
            return self.current_phase_idx + 1
        if target_txt.isdigit():
            idx = int(target_txt)
            if 0 <= idx < len(self._phases):
                return idx
            return None
        return self._phase_name_to_index.get(target_txt)

    def _evaluate_condition(
        self,
        condition: str,
        context: dict[str, Any] | None,
    ) -> bool:
        condition = condition.strip()
        if not condition:
            return False

        try:
            ast = parse_condition_expression(condition)
        except ConditionParseError as exc:
            logger.warning("Invalid transition condition '%s': %s", condition, exc)
            return False

        return evaluate_condition_ast(ast, lambda atom: self._evaluate_condition_atom(atom, context))

    def _evaluate_condition_atom(
        self,
        condition: str,
        context: dict[str, Any] | None,
    ) -> bool:
        condition = condition.strip()
        if not condition:
            logger.warning("Empty transition condition atom")
            return False

        if condition.startswith("em_mode:"):
            parts = condition.split(":", 2)
            if len(parts) != 3:
                logger.warning("Invalid em_mode condition atom '%s'", condition)
                return False
            em = self._get_em_status(parts[1], context)
            if em is None:
                logger.warning("EM '%s' missing in transition condition '%s'", parts[1], condition)
                return False
            return em is not None and str(em.get("mode", "")) == parts[2]

        if condition.startswith("em_state:"):
            parts = condition.split(":", 2)
            if len(parts) != 3:
                logger.warning("Invalid em_state condition atom '%s'", condition)
                return False
            em = self._get_em_status(parts[1], context)
            if em is None:
                logger.warning("EM '%s' missing in transition condition '%s'", parts[1], condition)
                return False
            return em is not None and str(em.get("state", "")).lower() == parts[2].lower()

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$", condition)
        if not match:
            logger.warning("Invalid transition condition atom '%s'", condition)
            return False

        key, op_txt, rhs_txt = match.groups()
        lhs = self._get_numeric_value(key, context)
        if lhs is None:
            logger.warning(
                "Missing numeric context value for '%s' in transition condition '%s'",
                key,
                condition,
            )
            return False

        rhs = float(rhs_txt)
        op = {
            ">": operator.gt,
            ">=": operator.ge,
            "<": operator.lt,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne,
        }[op_txt]
        return bool(op(lhs, rhs))

    def _get_numeric_value(self, key: str, context: dict[str, Any] | None) -> float | None:
        aliases = {
            "phase_elapsed": "phase_elapsed_s",
            "total_elapsed": "total_elapsed_s",
            "temperature": "temperature_K",
        }
        canonical_key = aliases.get(key, key)

        base: dict[str, Any] = {
            "phase_elapsed_s": self.phase_elapsed,
            "total_elapsed_s": self.total_elapsed,
        }
        if context:
            base.update(context)

        value = base.get(canonical_key)
        if value is None and canonical_key != key:
            value = base.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _get_em_status(self, em_tag: str, context: dict[str, Any] | None) -> dict[str, Any] | None:
        if not context:
            return None
        em_status = context.get("em_status", {})
        if not isinstance(em_status, dict):
            return None
        em = em_status.get(em_tag)
        if isinstance(em, dict):
            return em
        return None

    def reset(self) -> None:
        self.current_phase_idx = 0
        self.phase_elapsed = 0.0
        self.finished = False


# ---------------------------------------------------------------------------
# Recipe approval & versioning helpers
# ---------------------------------------------------------------------------

def _parse_recipe_metadata(raw: dict[str, Any]) -> RecipeMetadata | None:
    """Extract a RecipeMetadata from a raw YAML dict.

    Returns ``None`` when no ``metadata:`` key is present (recipe has no metadata block).
    Returns a :class:`RecipeMetadata` (possibly with empty fields) when the block exists.
    """
    meta_raw = raw.get("metadata")
    if meta_raw is None:
        return None
    meta = meta_raw or {}
    return RecipeMetadata(
        version=str(meta.get("version", "")),
        author=str(meta.get("author", "")),
        approved_by=str(meta.get("approved_by", "")),
        approval_date=str(meta.get("approval_date", "")),
        change_log=list(meta.get("change_log", [])),
    )


def _validate_recipe_metadata(meta: RecipeMetadata | None, path: Path) -> None:
    """Warn if important approval/version fields are absent or the metadata block is missing."""
    if meta is None:
        warnings.warn(
            f"{path.name}: recipe metadata missing: version, author, approved_by, approval_date",
            RecipeMetadataWarning,
            stacklevel=4,
        )
        return
    missing = [f for f in ("version", "author", "approved_by", "approval_date")
               if not getattr(meta, f)]
    if missing:
        warnings.warn(
            f"{path.name}: recipe metadata missing: {', '.join(missing)}",
            RecipeMetadataWarning,
            stacklevel=4,
        )


def _get_hmac_key() -> bytes | None:
    """Read REACTOR_RECIPE_KEY env var (hex string → bytes), or return None."""
    key_hex = os.environ.get("REACTOR_RECIPE_KEY", "")
    if not key_hex:
        return None
    return bytes.fromhex(key_hex)


def _compute_recipe_hmac(content_without_sig: dict[str, Any], key: bytes) -> str:
    """Compute HMAC-SHA256 over a deterministic (sorted) YAML dump of *content_without_sig*."""
    canonical = yaml.dump(
        content_without_sig, default_flow_style=False, sort_keys=True, allow_unicode=True
    )
    return _hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_recipe_signature(raw: dict[str, Any], path: Path) -> None:
    """If *raw* contains ``hmac_sha256``, verify it against the signing key.

    - No signature → silently accepted (unsigned recipes are allowed).
    - Signature present, key absent → :class:`RecipeMetadataWarning` (skips check).
    - Signature present, key present, mismatch → :class:`RecipeSignatureError`.
    """
    sig = raw.get("hmac_sha256")
    if not sig:
        return

    key = _get_hmac_key()
    if key is None:
        warnings.warn(
            f"{path.name}: contains hmac_sha256 but REACTOR_RECIPE_KEY is not set; "
            "skipping verification.",
            RecipeMetadataWarning,
            stacklevel=4,
        )
        return

    raw_without_sig = {k: v for k, v in raw.items() if k != "hmac_sha256"}
    expected = _compute_recipe_hmac(raw_without_sig, key)
    if not _hmac.compare_digest(str(sig), expected):
        raise RecipeSignatureError(
            f"{path.name}: HMAC-SHA256 verification failed — recipe may have been modified."
        )


def _compute_xml_hmac(root: ET.Element, key: bytes) -> str:
    """Compute HMAC-SHA256 over the canonical XML serialisation of *root* (without hmac_sha256 child)."""
    # Remove hmac_sha256 child for canonical form
    import copy
    root_copy = copy.deepcopy(root)
    for child in list(root_copy):
        if child.tag == "hmac_sha256":
            root_copy.remove(child)
    canonical = ET.tostring(root_copy, encoding="unicode")
    return _hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_xml_signature(root: ET.Element, path: Path) -> None:
    """Verify HMAC-SHA256 signature embedded in XML ``<hmac_sha256>`` element."""
    sig_el = root.find("hmac_sha256")
    if sig_el is None or not (sig_el.text or "").strip():
        return

    sig = sig_el.text.strip()
    key = _get_hmac_key()
    if key is None:
        warnings.warn(
            f"{path.name}: contains <hmac_sha256> but REACTOR_RECIPE_KEY is not set; "
            "skipping verification.",
            RecipeMetadataWarning,
            stacklevel=4,
        )
        return

    expected = _compute_xml_hmac(root, key)
    if not _hmac.compare_digest(sig, expected):
        raise RecipeSignatureError(
            f"{path.name}: HMAC-SHA256 verification failed — recipe may have been modified."
        )


def _parse_xml_metadata(root: ET.Element) -> RecipeMetadata | None:
    """Extract RecipeMetadata from a ``<metadata>`` child of an XML recipe root."""
    meta_el = root.find("metadata")
    if meta_el is None:
        return None

    def _text(tag: str) -> str:
        el = meta_el.find(tag)
        return (el.text or "").strip() if el is not None else ""

    change_log = [
        (el.text or "").strip()
        for el in meta_el.findall("change_log")
    ]
    return RecipeMetadata(
        version=_text("version"),
        author=_text("author"),
        approved_by=_text("approved_by"),
        approval_date=_text("approval_date"),
        change_log=change_log,
    )


def sign_recipe_yaml(path: str | Path, key: bytes | None = None) -> str:
    """Return the HMAC-SHA256 hex digest for a YAML recipe file.

    Reads ``REACTOR_RECIPE_KEY`` from the environment if *key* is not given.
    Does **not** modify the file; the caller is responsible for embedding the
    returned digest under the ``hmac_sha256:`` key.
    """
    path = Path(path)
    key = key or _get_hmac_key()
    if key is None:
        raise ValueError("No signing key: provide key argument or set REACTOR_RECIPE_KEY env var.")
    with open(path) as f:
        raw = yaml.safe_load(f)
    raw_without_sig = {k: v for k, v in raw.items() if k != "hmac_sha256"}
    return _compute_recipe_hmac(raw_without_sig, key)


def sign_recipe_xml(path: str | Path, key: bytes | None = None) -> str:
    """Return the HMAC-SHA256 hex digest for an XML recipe file.

    Does **not** modify the file; embed the returned value in ``<hmac_sha256>`` manually.
    """
    path = Path(path)
    key = key or _get_hmac_key()
    if key is None:
        raise ValueError("No signing key: provide key argument or set REACTOR_RECIPE_KEY env var.")
    tree = ET.parse(path)
    root = tree.getroot()
    return _compute_xml_hmac(root, key)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _wrap_recipe_as_procedure(
    recipe: Recipe, metadata: RecipeMetadata | None = None
) -> Procedure:
    """Wrap a flat Recipe as Procedure → 1 UnitProcedure → 1 Operation → N phases."""
    op = Operation(name="BATCH", phases=list(recipe.steps))
    up = UnitProcedure(name="REACTOR", operations=[op])
    return Procedure(name=recipe.name, unit_procedures=[up], metadata=metadata)


def _load_procedure_nested(
    raw: dict[str, Any], stem: str, metadata: RecipeMetadata | None = None
) -> Procedure:
    """Parse the nested unit_procedures / operations / phases YAML format."""
    unit_procedures: list[UnitProcedure] = []
    for up_data in raw["unit_procedures"]:
        operations: list[Operation] = []
        for op_data in up_data["operations"]:
            phases = [_parse_batch_step(p) for p in op_data.get("phases", [])]
            operations.append(Operation(name=op_data["name"], phases=phases))
        unit_procedures.append(UnitProcedure(name=up_data["name"], operations=operations))
    return Procedure(name=raw.get("name", stem), unit_procedures=unit_procedures, metadata=metadata)


def load_procedure(path: str | Path) -> Procedure:
    """Load a Procedure from a YAML or XML file.

    Accepts both the new nested format::

        name: ...
        unit_procedures:
          - name: REACTOR_R101
            operations:
              - name: PREPARATION
                phases: [...]

    and the legacy flat format (``steps:``) which is auto-wrapped as
    Procedure → 1 UnitProcedure (REACTOR) → 1 Operation (BATCH) → N phases.
    XML recipes are always loaded as flat and auto-wrapped.

    Metadata validation (version, author, approval) and optional HMAC-SHA256
    signature verification are performed at load time for all formats.
    """
    path = Path(path)
    if path.suffix == ".xml":
        from .recipe import _load_recipe_xml
        recipe, xml_meta = _load_recipe_xml(path)
        if xml_meta is not None:
            _validate_recipe_metadata(xml_meta, path)
        return _wrap_recipe_as_procedure(recipe, metadata=xml_meta)

    with open(path) as f:
        raw = yaml.safe_load(f)

    _verify_recipe_signature(raw, path)
    meta = _parse_recipe_metadata(raw)
    _validate_recipe_metadata(meta, path)

    if "unit_procedures" in raw:
        return _load_procedure_nested(raw, path.stem, metadata=meta)

    # Legacy flat format: delegate to recipe parser then wrap
    from .recipe import _load_recipe_from_raw
    recipe = _load_recipe_from_raw(raw, path)
    return _wrap_recipe_as_procedure(recipe, metadata=meta)


# ---------------------------------------------------------------------------
# B2MML serialisation
# ---------------------------------------------------------------------------

_B2MML_NS = "http://www.mesa.org/xml/B2MML"


def to_b2mml(procedure: Procedure) -> str:
    """Serialise a Procedure to a B2MML-V0600 XML string.

    Structure:
        OperationsDefinitionInformation
          [RecipeHeader — version, author, approval if metadata present]
          OperationsDefinition (one per UnitProcedure)
            OperationsSegment  (one per Phase; grouped under Operation comments)
              ID, Description
              ParameterSpecification (one per channel/profile)
    """
    ET.register_namespace("", _B2MML_NS)
    root = ET.Element(f"{{{_B2MML_NS}}}OperationsDefinitionInformation")

    # Emit approval/version metadata as a RecipeHeader element when present
    meta = procedure.metadata
    if meta is not None:
        header = ET.SubElement(root, f"{{{_B2MML_NS}}}RecipeHeader")
        _sub_text(header, "ID", procedure.name)
        if meta.version:
            _sub_text(header, "Version", meta.version)
        if meta.author:
            _sub_text(header, "Author", meta.author)
        if meta.approved_by:
            _sub_text(header, "ApprovedBy", meta.approved_by)
        if meta.approval_date:
            _sub_text(header, "ApprovalDate", meta.approval_date)
        for entry in meta.change_log:
            _sub_text(header, "ChangeLog", entry)

    for up in procedure.unit_procedures:
        od = ET.SubElement(root, f"{{{_B2MML_NS}}}OperationsDefinition")
        _sub_text(od, "ID", up.name)
        _sub_text(od, "Description", procedure.name)

        for op in up.operations:
            # Use a comment as Operation boundary marker (valid XML, informational)
            od.append(ET.Comment(f" OPERATION: {op.name} "))
            for phase in op.phases:
                seg = ET.SubElement(od, f"{{{_B2MML_NS}}}OperationsSegment")
                _sub_text(seg, "ID", phase.name)
                _sub_text(seg, "Description", op.name)
                _sub_text(seg, "Duration", str(int(phase.duration)))

                # Numeric profile channels
                for channel, prof in phase.profiles.items():
                    ps = ET.SubElement(seg, f"{{{_B2MML_NS}}}ParameterSpecification")
                    _sub_text(ps, "ID", channel)
                    _sub_text(ps, "Value", str(prof.start_value))
                    if prof.profile_type.value != "constant":
                        _sub_text(ps, "ToValue", str(prof.end_value))
                    _sub_text(ps, "ProfileType", prof.profile_type.value)
                    _sub_text(ps, "UnitOfMeasure", _channel_unit(channel))

                # EM mode channels
                for channel, mode_name in phase.em_modes.items():
                    ps = ET.SubElement(seg, f"{{{_B2MML_NS}}}ParameterSpecification")
                    _sub_text(ps, "ID", channel)
                    _sub_text(ps, "Value", mode_name)
                    _sub_text(ps, "ProfileType", "constant")

    _indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _sub_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{_B2MML_NS}}}{tag}")
    el.text = text
    return el


def _channel_unit(channel: str) -> str:
    mapping = {
        "jacket_temp": "K",
        "temperature": "K",
    }
    if channel.startswith("feed_"):
        return "kg/s"
    return mapping.get(channel, "")


def _indent(elem: ET.Element, level: int = 0) -> None:
    """Add pretty-print indentation in-place (Python 3.9+ has ET.indent but this works on 3.8)."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():  # type: ignore[reportPossiblyUnbound]
            child.tail = indent  # type: ignore[reportPossiblyUnbound]
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
