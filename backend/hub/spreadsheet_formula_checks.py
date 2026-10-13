"""Validate the supported formula grammar without evaluating spreadsheet data."""

from typing import Any

ARITY = {
    **dict.fromkeys(
        "SUM AVERAGE MIN MAX COUNT COUNTA AND OR SUMPRODUCT MEDIAN CONCAT CONCATENATE".split(),
        (1, 255),
    ),
    **dict.fromkeys(
        "ABS INT SQRT LEN TRIM UPPER LOWER VALUE YEAR MONTH DAY COUNTBLANK NOT".split(), (1, 1)
    ),
    **dict.fromkeys(
        "ROUND ROUNDUP ROUNDDOWN MOD POWER TEXT IFERROR LARGE SMALL EOMONTH".split(), (2, 2)
    ),
    "IF": (2, 3),
    "IFS": (2, 254),
    "SUMIF": (2, 3),
    "AVERAGEIF": (2, 3),
    "COUNTIF": (2, 2),
    "SUMIFS": (3, 255),
    "AVERAGEIFS": (3, 255),
    "COUNTIFS": (2, 254),
    "VLOOKUP": (3, 4),
    "HLOOKUP": (3, 4),
    "INDEX": (2, 4),
    "MATCH": (2, 3),
    "XLOOKUP": (3, 4),
    "SUBTOTAL": (2, 255),
    "LEFT": (1, 2),
    "RIGHT": (1, 2),
    "MID": (3, 3),
    "DATE": (3, 3),
    "TODAY": (0, 0),
    "NPV": (2, 255),
    "IRR": (1, 2),
    "PMT": (3, 5),
}


def validate_syntax(tokens: list[Any]) -> None:
    """Require explicit operands/arguments in the application's finite subset.

    Excel permits some omitted arguments; model plans must spell those out as
    zero/empty text instead of relying on implicit defaults. Optional final
    arguments remain optional according to each supported function's arity.
    """
    values = [token for token in tokens if token.type != "WHITE-SPACE"]
    position = 0

    def expression(depth: int) -> None:
        nonlocal position
        if depth > 32:
            raise ValueError("Formelverschachtelung überschreitet das Limit")
        operand(depth)
        while position < len(values) and values[position].type == "OPERATOR-INFIX":
            position += 1
            operand(depth)

    def operand(depth: int) -> None:
        nonlocal position
        if depth > 32:
            raise ValueError("Formelverschachtelung überschreitet das Limit")
        if position >= len(values):
            raise ValueError("Formeloperator benötigt einen Operanden")
        token = values[position]
        position += 1
        if token.type == "OPERATOR-PREFIX":
            operand(depth + 1)
        elif token.type == "OPERAND":
            pass
        elif token.type == "PAREN" and token.subtype == "OPEN":
            expression(depth + 1)
            close("PAREN")
        elif token.type == "FUNC" and token.subtype == "OPEN":
            name = token.value[:-1].upper()
            count = 0
            if position < len(values) and values[position].subtype != "CLOSE":
                while True:
                    expression(depth + 1)
                    count += 1
                    if position >= len(values) or values[position].type != "SEP":
                        break
                    position += 1
            close("FUNC")
            if name not in ARITY:
                raise ValueError("Excel-Funktion nicht freigegeben: " + name)
            minimum, maximum = ARITY[name]
            if not minimum <= count <= maximum or (
                name in {"IFS", "COUNTIFS"}
                and count % 2
                or name in {"SUMIFS", "AVERAGEIFS"}
                and not count % 2
            ):
                raise ValueError("Ungültige Anzahl von Funktionsargumenten: " + name)
        else:
            raise ValueError("Leerer oder ungültiger Formelausdruck; Argument explizit angeben")
        while position < len(values) and values[position].type == "OPERATOR-POSTFIX":
            position += 1

    def close(kind: str) -> None:
        nonlocal position
        if position >= len(values) or (
            values[position].type != kind or values[position].subtype != "CLOSE"
        ):
            raise ValueError("Formelklammern oder Argumenttrenner sind ungültig")
        position += 1

    expression(0)
    if position != len(values):
        raise ValueError("Formel enthält einen nicht verbundenen Ausdruck")
