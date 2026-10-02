"""The base-model rule table, loaded from JSON files in ``rules_data/``.

A rule matches when every condition it declares holds. Rules are tried highest priority first,
and the first match wins, so a more specific rule gets a higher priority than its parent.

Rule fields (all optional except ``id`` and ``base_model``):

- ``kinds``: the kinds the rule applies to. Empty means any kind.
- ``required_keys``: keys that must exist, after the kind's key prefix.
- ``absent_keys``: keys that must not exist, after the prefix.
- ``any_key_prefixes``: at least one key must start with one of these, after the prefix.
- ``shapes``: key to expected shape, after the prefix. ``null`` in a shape is a wildcard.
- ``regex_shapes``: list of ``{"regex": ..., "shape": [...]}``. The first key that the anchored
  regex matches must have that shape.
- ``prediction``: list of ``{"key": ..., "value": ...}``. The first key present, looked up
  without the prefix, sets the prediction type.
- ``priority`` (default 0) and ``confidence`` (default 0.9).
"""

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Rule:
    id: str
    base_model: str
    kinds: tuple[str, ...] = ()
    required_keys: tuple[str, ...] = ()
    absent_keys: tuple[str, ...] = ()
    any_key_prefixes: tuple[str, ...] = ()
    shapes: dict[str, tuple[int | None, ...]] = field(default_factory=dict)
    regex_shapes: tuple[tuple[re.Pattern[str], tuple[int | None, ...]], ...] = ()
    prediction: tuple[tuple[str, str], ...] = ()
    priority: int = 0
    confidence: float = 0.9

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        return cls(
            id=data["id"],
            base_model=data["base_model"],
            kinds=tuple(data.get("kinds", ())),
            required_keys=tuple(data.get("required_keys", ())),
            absent_keys=tuple(data.get("absent_keys", ())),
            any_key_prefixes=tuple(data.get("any_key_prefixes", ())),
            shapes={k: tuple(v) for k, v in data.get("shapes", {}).items()},
            regex_shapes=tuple((re.compile(r["regex"]), tuple(r["shape"])) for r in data.get("regex_shapes", ())),
            prediction=tuple((p["key"], p["value"]) for p in data.get("prediction", ())),
            priority=int(data.get("priority", 0)),
            confidence=float(data.get("confidence", 0.9)),
        )


def _shape_matches(actual: list[int] | None, expected: tuple[int | None, ...]) -> bool:
    if actual is None or len(actual) < len(expected):
        return False
    return all(e is None or a == e for a, e in zip(actual, expected))


@dataclass
class RuleMatch:
    rule: Rule
    prediction_type: str | None


class RuleTable:
    def __init__(self, rules: list[Rule]) -> None:
        ids = [r.id for r in rules]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate rule ids: {sorted(duplicates)}")
        self.rules = sorted(rules, key=lambda r: -r.priority)

    @classmethod
    def load_default(cls) -> "RuleTable":
        rules: list[Rule] = []
        folder = resources.files("hanakura.core.detection") / "rules_data"
        for entry in sorted(folder.iterdir(), key=lambda e: e.name):
            if entry.name.endswith(".json"):
                rules.extend(Rule.from_dict(r) for r in json.loads(entry.read_text(encoding="utf-8")))
        return cls(rules)

    @classmethod
    def load_files(cls, paths: list[Path]) -> "RuleTable":
        rules: list[Rule] = []
        for path in paths:
            rules.extend(Rule.from_dict(r) for r in json.loads(path.read_text(encoding="utf-8")))
        return cls(rules)

    def match(self, kind: str, tensors: dict[str, list[int]], prefix: str = "") -> RuleMatch | None:
        for rule in self.rules:
            if rule.kinds and kind not in rule.kinds:
                continue
            if self._matches(rule, tensors, prefix):
                prediction = next((value for key, value in rule.prediction if key in tensors), None)
                return RuleMatch(rule, prediction)
        return None

    @staticmethod
    def _matches(rule: Rule, tensors: dict[str, list[int]], prefix: str) -> bool:
        if any(prefix + k not in tensors for k in rule.required_keys):
            return False
        if any(prefix + k in tensors for k in rule.absent_keys):
            return False
        if rule.any_key_prefixes:
            wanted = tuple(prefix + p for p in rule.any_key_prefixes)
            if not any(k.startswith(wanted) for k in tensors):
                return False
        for key, shape in rule.shapes.items():
            if not _shape_matches(tensors.get(prefix + key), shape):
                return False
        for pattern, shape in rule.regex_shapes:
            hit = next((k for k in tensors if pattern.match(k)), None)
            if hit is None or not _shape_matches(tensors[hit], shape):
                return False
        return True
