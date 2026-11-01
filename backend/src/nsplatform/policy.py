"""Policy engine: business rules as versioned data, evaluated deterministically.

A ruleset is an ordered list of rules; the first rule whose `when` matches the facts wins.
Conditions are dotted fact paths mapped to a value (equality) or an operator dict
(eq, ne, lt, lte, gt, gte, in, not_in, exists). Decision values and the explanation may reference
facts with {{ path }}. Every decision names the clause it rests on, so answers can cite it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_TEMPLATE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


@dataclass
class Decision:
    ruleset: str
    rule_id: str
    allowed: bool
    params: dict = field(default_factory=dict)
    clause_ids: list[str] = field(default_factory=list)
    explanation: str = ""

    def as_dict(self) -> dict:
        return {"ruleset": self.ruleset, "rule_id": self.rule_id, "allowed": self.allowed, "params": self.params,
                "clause_ids": self.clause_ids, "explanation": self.explanation}


class PolicyError(Exception):
    pass


def lookup(facts: dict, path: str):
    node = facts
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _matches(actual, condition) -> bool:
    if not isinstance(condition, dict):
        return actual == condition
    for op, expected in condition.items():
        if op == "exists":
            if (actual is not None) != bool(expected):
                return False
            continue
        if actual is None:
            return False
        ok = {
            "eq": lambda: actual == expected, "ne": lambda: actual != expected,
            "lt": lambda: actual < expected, "lte": lambda: actual <= expected,
            "gt": lambda: actual > expected, "gte": lambda: actual >= expected,
            "in": lambda: actual in expected, "not_in": lambda: actual not in expected,
        }.get(op)
        if ok is None:
            raise PolicyError(f"unknown operator {op}")
        if not ok():
            return False
    return True


def render(value, facts: dict):
    if isinstance(value, str):
        whole = _TEMPLATE.fullmatch(value.strip())
        if whole:
            return lookup(facts, whole.group(1))
        return _TEMPLATE.sub(lambda m: str(lookup(facts, m.group(1))), value)
    if isinstance(value, dict):
        return {k: render(v, facts) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, facts) for v in value]
    return value


class PolicyEngine:
    def __init__(self):
        self.rulesets: dict[str, list[dict]] = {}
        self.owners: dict[str, str] = {}

    def load_file(self, path: Path, owner: str) -> None:
        doc = yaml.safe_load(path.read_text())
        name = doc["ruleset"]
        if name in self.rulesets:
            raise PolicyError(f"ruleset {name} defined twice ({self.owners[name]} and {owner})")
        for rule in doc["rules"]:
            if "id" not in rule or "decision" not in rule or "clause" not in rule:
                raise PolicyError(f"{path}: every rule needs id, decision and clause")
        self.rulesets[name] = doc["rules"]
        self.owners[name] = owner

    def evaluate(self, ruleset: str, facts: dict) -> Decision:
        rules = self.rulesets.get(ruleset)
        if rules is None:
            raise PolicyError(f"unknown ruleset {ruleset}")
        for rule in rules:
            if all(_matches(lookup(facts, path), cond) for path, cond in (rule.get("when") or {}).items()):
                decision = render(rule["decision"], facts)
                context = {**facts, "decision": decision}
                clauses = rule["clause"] if isinstance(rule["clause"], list) else [rule["clause"]]
                return Decision(ruleset, rule["id"], bool(decision.get("allowed", True)),
                                {k: v for k, v in decision.items() if k != "allowed"}, clauses,
                                render(rule.get("explain", ""), context))
        raise PolicyError(f"no rule in {ruleset} matched")
