"""Boolean condition expression parser/evaluator (AST-based, no eval())."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ConditionParseError(ValueError):
    """Raised when a condition expression cannot be parsed."""


@dataclass(frozen=True)
class ConditionAtom:
    text: str


@dataclass(frozen=True)
class ConditionUnary:
    op: str
    expr: ConditionNode


@dataclass(frozen=True)
class ConditionBinary:
    op: str
    left: ConditionNode
    right: ConditionNode


ConditionNode = ConditionAtom | ConditionUnary | ConditionBinary


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0

    def parse(self) -> ConditionNode:
        self._skip_ws()
        node = self._parse_or()
        self._skip_ws()
        if self.i != self.n:
            raise ConditionParseError(f"Unexpected token near '{self.text[self.i:self.i + 20]}'")
        return node

    def _parse_or(self) -> ConditionNode:
        left = self._parse_and()
        while True:
            self._skip_ws()
            if not self._consume_word("OR"):
                return left
            right = self._parse_and()
            left = ConditionBinary(op="OR", left=left, right=right)

    def _parse_and(self) -> ConditionNode:
        left = self._parse_not()
        while True:
            self._skip_ws()
            if not self._consume_word("AND"):
                return left
            right = self._parse_not()
            left = ConditionBinary(op="AND", left=left, right=right)

    def _parse_not(self) -> ConditionNode:
        self._skip_ws()
        if self._consume_word("NOT"):
            return ConditionUnary(op="NOT", expr=self._parse_not())
        return self._parse_primary()

    def _parse_primary(self) -> ConditionNode:
        self._skip_ws()
        if self.i >= self.n:
            raise ConditionParseError("Unexpected end of expression")

        if self.text[self.i] == "(":
            self.i += 1
            node = self._parse_or()
            self._skip_ws()
            if self.i >= self.n or self.text[self.i] != ")":
                raise ConditionParseError("Missing closing ')' in expression")
            self.i += 1
            return node

        atom = self._read_atom()
        if not atom:
            raise ConditionParseError(f"Expected condition atom near '{self.text[self.i:self.i + 20]}'")
        return ConditionAtom(text=atom)

    def _read_atom(self) -> str:
        start = self.i
        while self.i < self.n:
            ch = self.text[self.i]
            if ch == ")":
                break
            if ch == "(":
                break
            if self._peek_word("AND") or self._peek_word("OR"):
                break
            self.i += 1
        return self.text[start:self.i].strip()

    def _skip_ws(self) -> None:
        while self.i < self.n and self.text[self.i].isspace():
            self.i += 1

    def _peek_word(self, word: str) -> bool:
        end = self.i + len(word)
        if end > self.n:
            return False
        token = self.text[self.i:end]
        if token.upper() != word:
            return False
        prev_ok = self.i == 0 or not (self.text[self.i - 1].isalnum() or self.text[self.i - 1] == "_")
        next_ok = end == self.n or not (self.text[end].isalnum() or self.text[end] == "_")
        return prev_ok and next_ok

    def _consume_word(self, word: str) -> bool:
        if not self._peek_word(word):
            return False
        self.i += len(word)
        return True


def parse_condition_expression(text: str) -> ConditionNode:
    """Parse boolean expression with AND/OR/NOT and parentheses."""
    return _Parser(text).parse()


def evaluate_condition_ast(node: ConditionNode, eval_atom: Callable[[str], bool]) -> bool:
    """Evaluate a parsed condition AST using a caller-provided atom evaluator."""
    if isinstance(node, ConditionAtom):
        return bool(eval_atom(node.text))
    if isinstance(node, ConditionUnary):
        if node.op == "NOT":
            return not evaluate_condition_ast(node.expr, eval_atom)
        raise ConditionParseError(f"Unsupported unary operator '{node.op}'")
    if node.op == "AND":
        return evaluate_condition_ast(node.left, eval_atom) and evaluate_condition_ast(node.right, eval_atom)
    if node.op == "OR":
        return evaluate_condition_ast(node.left, eval_atom) or evaluate_condition_ast(node.right, eval_atom)
    raise ConditionParseError(f"Unsupported binary operator '{node.op}'")


def iter_condition_atoms(node: ConditionNode) -> list[str]:
    """Return all atom strings in left-to-right order."""
    atoms: list[str] = []

    def _walk(cur: ConditionNode) -> None:
        if isinstance(cur, ConditionAtom):
            atoms.append(cur.text)
            return
        if isinstance(cur, ConditionUnary):
            _walk(cur.expr)
            return
        _walk(cur.left)
        _walk(cur.right)

    _walk(node)
    return atoms
