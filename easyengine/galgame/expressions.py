"""A small, bounded expression language for story conditions and values."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping
from typing import Any

_MAX_EXPRESSION_LENGTH = 512
_MAX_NODES = 128
_MAX_DEPTH = 24
_MAX_STRING_LENGTH = 4096
_MAX_NUMBER_MAGNITUDE = 1e100


class ExpressionError(ValueError):
    """Invalid or unsafe expression in a story script."""


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_COMPARISON_OPERATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def validate_expression(expression: str) -> None:
    """Parse and validate syntax without evaluating variable references."""
    _validated_tree(expression)


def evaluate_expression(
    expression: str,
    variables: Mapping[str, Any],
) -> Any:
    """Evaluate an expression using only JSON values and explicitly allowed AST nodes."""
    tree = _validated_tree(expression)
    return _Evaluator(variables).evaluate(tree.body)


def lookup_variable(variables: Mapping[str, Any], key: str) -> Any:
    """Resolve a flat key first, then fall back to a dotted nested-object path."""
    if key in variables:
        return variables[key]

    current: Any = variables
    for part in key.split("."):
        if not part or not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _validated_tree(expression: str) -> ast.Expression:
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("表达式必须是非空字符串")
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ExpressionError(
            f"表达式长度不能超过 {_MAX_EXPRESSION_LENGTH} 个字符"
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(
            f"表达式语法错误（第 {exc.lineno} 行，第 {exc.offset} 列）：{exc.msg}"
        ) from exc

    count = 0

    def validate(node: ast.AST, depth: int = 0) -> None:
        nonlocal count
        count += 1
        if count > _MAX_NODES:
            raise ExpressionError(f"表达式节点不能超过 {_MAX_NODES} 个")
        if depth > _MAX_DEPTH:
            raise ExpressionError(f"表达式嵌套不能超过 {_MAX_DEPTH} 层")

        if isinstance(node, ast.Expression):
            validate(node.body, depth + 1)
        elif isinstance(node, ast.Constant):
            _validate_literal(node.value)
        elif isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ExpressionError("表达式不允许访问以下划线开头的变量")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ExpressionError("表达式不允许访问以下划线开头的属性")
            validate(node.value, depth + 1)
        elif isinstance(node, ast.Subscript):
            validate(node.value, depth + 1)
            validate(node.slice, depth + 1)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                validate(element, depth + 1)
        elif isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise ExpressionError("表达式不支持字典展开")
            for key, value in zip(node.keys, node.values, strict=True):
                validate(key, depth + 1)
                validate(value, depth + 1)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BINARY_OPERATORS:
                raise ExpressionError(f"不支持的算术运算符：{type(node.op).__name__}")
            validate(node.left, depth + 1)
            validate(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.Not, ast.UAdd, ast.USub)):
                raise ExpressionError(f"不支持的一元运算符：{type(node.op).__name__}")
            validate(node.operand, depth + 1)
        elif isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                raise ExpressionError(f"不支持的逻辑运算符：{type(node.op).__name__}")
            for value in node.values:
                validate(value, depth + 1)
        elif isinstance(node, ast.Compare):
            if any(type(op) not in _COMPARISON_OPERATORS for op in node.ops):
                raise ExpressionError("表达式包含不支持的比较运算符")
            validate(node.left, depth + 1)
            for comparator in node.comparators:
                validate(comparator, depth + 1)
        elif isinstance(node, ast.IfExp):
            validate(node.test, depth + 1)
            validate(node.body, depth + 1)
            validate(node.orelse, depth + 1)
        else:
            raise ExpressionError(
                f"表达式不允许使用 {type(node).__name__}"
            )

    validate(tree)
    return tree


def _validate_literal(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value) > _MAX_STRING_LENGTH:
            raise ExpressionError(
                f"表达式字符串不能超过 {_MAX_STRING_LENGTH} 个字符"
            )
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ExpressionError(f"表达式包含不支持的字面值：{value!r}")


class _Evaluator:
    def __init__(self, variables: Mapping[str, Any]) -> None:
        self.variables = variables

    def evaluate(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == "true":
                return True
            if node.id == "false":
                return False
            if node.id == "null":
                return None
            if node.id == "vars":
                return self.variables
            return lookup_variable(self.variables, node.id)
        if isinstance(node, ast.Attribute):
            path = _attribute_path(node)
            if path is not None:
                return lookup_variable(self.variables, path)
            value = self.evaluate(node.value)
            if isinstance(value, Mapping):
                return value.get(node.attr)
            raise ExpressionError("点号属性只能读取嵌套对象")
        if isinstance(node, ast.Subscript):
            value = self.evaluate(node.value)
            key = self.evaluate(node.slice)
            if isinstance(value, Mapping):
                try:
                    return value.get(key)
                except TypeError as exc:
                    raise ExpressionError("对象下标必须是可用的键") from exc
            if isinstance(value, (list, tuple)) and isinstance(key, int) and not isinstance(key, bool):
                try:
                    return value[key]
                except IndexError:
                    return None
            raise ExpressionError("下标访问仅支持对象键或数组整数下标")
        if isinstance(node, ast.List):
            return [self.evaluate(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return [self.evaluate(item) for item in node.elts]
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                key = self.evaluate(key_node)
                if not isinstance(key, str):
                    raise ExpressionError("表达式对象的键必须是字符串")
                result[key] = self.evaluate(value_node)
            return result
        if isinstance(node, ast.BinOp):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            return _apply_binary(node.op, left, right)
        if isinstance(node, ast.UnaryOp):
            operand = self.evaluate(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(operand)
            number = _number(operand)
            return number if isinstance(node.op, ast.UAdd) else -number
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(self.evaluate(value)) for value in node.values)
            return any(bool(self.evaluate(value)) for value in node.values)
        if isinstance(node, ast.Compare):
            left = self.evaluate(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = self.evaluate(comparator)
                if not _apply_comparison(op, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            branch = node.body if self.evaluate(node.test) else node.orelse
            return self.evaluate(branch)
        raise ExpressionError(f"表达式不允许使用 {type(node).__name__}")


def _attribute_path(node: ast.Attribute) -> str | None:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id == "vars":
        return None
    parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpressionError("算术运算只接受数字")
    return value


def _apply_binary(operator_node: ast.operator, left: Any, right: Any) -> Any:
    if isinstance(operator_node, ast.Add) and isinstance(left, str) and isinstance(right, str):
        result = left + right
        if len(result) > _MAX_STRING_LENGTH:
            raise ExpressionError("表达式结果字符串过长")
        return result

    left_number = _number(left)
    right_number = _number(right)
    try:
        result = _BINARY_OPERATORS[type(operator_node)](left_number, right_number)
    except (ArithmeticError, OverflowError) as exc:
        raise ExpressionError(f"算术运算失败：{exc}") from exc

    if isinstance(result, float) and not math.isfinite(result):
        raise ExpressionError("算术结果必须是有限数字")
    if abs(result) > _MAX_NUMBER_MAGNITUDE:
        raise ExpressionError("算术结果超出允许范围")
    return result


def _apply_comparison(operator_node: ast.cmpop, left: Any, right: Any) -> bool:
    operation = _COMPARISON_OPERATORS[type(operator_node)]
    if isinstance(operator_node, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
        numeric_pair = (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
        )
        string_pair = isinstance(left, str) and isinstance(right, str)
        if not (numeric_pair or string_pair):
            return False
    if isinstance(operator_node, (ast.In, ast.NotIn)) and not isinstance(
        right, (str, list, tuple, dict)
    ):
        return False
    try:
        return bool(operation(left, right))
    except (TypeError, ValueError):
        return False
