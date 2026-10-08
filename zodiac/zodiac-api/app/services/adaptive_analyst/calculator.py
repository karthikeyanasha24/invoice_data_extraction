"""Bounded decimal arithmetic for self-contained questions, independent of models.

Only a complete numeric expression is accepted. Names, calls, data references,
and compound requests remain with the conversational/analytical router.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Optional


@dataclass(frozen=True)
class Calculation:
    expression: str
    answer: str
    value: Optional[str] = None
    approximate: bool = False


_NUMBERS = dict(enumerate((
    'zero one two three four five six seven eight nine ten eleven twelve '
    'thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'
).split()))
_WORDS = {word: str(number) for number, word in _NUMBERS.items()}
_OPERATORS = (
    (r'\b(?:to the power of|raised to)\b', '**'),
    (r'\b(?:multiplied by|times)\b', '*'),
    (r'\b(?:divided by|over)\b', '/'),
    (r'\bplus\b', '+'), (r'\bminus\b', '-'),
)


def calculate_question(question: str) -> Optional[Calculation]:
    raw = str(question or '').strip().lower()
    if not raw or len(raw) > 240:
        return None
    # Common mistyped question prefixes; never rewrite business entities.
    raw = re.sub(r'^(?:what|whst|whats|what\'s)\s+i(?=\d)', '', raw)
    raw = re.sub(r'^(?:please\s+)?(?:what is|what\'s|whats|whst is|calculate|compute|evaluate|solve)\s+', '', raw)
    raw = re.sub(r'\s*(?:equals?|=)\s*$', '', raw.rstrip('?.!').strip())
    raw = raw.replace('×', '*').replace('÷', '/').replace('−', '-').replace('^', '**')
    for pattern, replacement in _OPERATORS:
        raw = re.sub(pattern, replacement, raw)
    raw = re.sub(r'\b(' + '|'.join(_WORDS) + r')\b', lambda m: _WORDS[m.group()], raw)
    percentage = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+([+-]?\d+(?:\.\d+)?)', raw)
    if percentage:
        raw = f'({percentage[1]} / 100) * {percentage[2]}'
    # Require an operation: bare numbers may answer a pending clarification.
    if not re.fullmatch(r'[\d.\s()+*/%-]+', raw) or not re.search(r'[+*/%]|(?<=\d)\s*-', raw):
        return None
    try:
        tree = ast.parse(raw.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(list(ast.walk(tree))) > 64:
        return None

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(ast.get_source_segment(raw.strip(), node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if not isinstance(node, ast.BinOp):
            raise ValueError('unsupported expression')
        left, right = evaluate(node.left), evaluate(node.right)
        if isinstance(node.op, ast.Add): value = left + right
        elif isinstance(node.op, ast.Sub): value = left - right
        elif isinstance(node.op, ast.Mult): value = left * right
        elif isinstance(node.op, ast.Div): value = left / right
        elif isinstance(node.op, ast.Mod): value = left % right
        elif isinstance(node.op, ast.Pow):
            if right != right.to_integral_value() or abs(right) > 100:
                raise ValueError('exponent outside calculator bounds')
            value = left ** int(right)
        else: raise ValueError('unsupported operator')
        if not value.is_finite() or abs(value) > Decimal('1e100'):
            raise ValueError('result outside calculator bounds')
        return value

    try:
        with localcontext() as context:
            context.prec = 40
            value = evaluate(tree.body)
            approximate = context.flags[Inexact]
    except ValueError:
        return None
    except DecimalException:
        return Calculation(raw, 'This calculation is undefined (for example, division by zero).')
    rendered = format(value, 'f')
    if '.' in rendered:
        rendered = rendered.rstrip('0').rstrip('.')
    if value == 0: rendered = '0'
    symbol = '≈' if approximate else '='
    return Calculation(raw, f'{raw} {symbol} {rendered}', rendered, approximate)
