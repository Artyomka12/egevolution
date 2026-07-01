import ast

ALLOWED_NODE_TYPES = {
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.For, ast.While, ast.If, ast.Break, ast.Continue, ast.Pass,
    ast.Call, ast.Return,
    ast.Name, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.Subscript, ast.Slice,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.Invert,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.Load, ast.Store, ast.Del,
    ast.Attribute,
    ast.ListComp, ast.comprehension,
    ast.FunctionDef, ast.arguments, ast.arg, ast.keyword,
}

ALLOWED_BUILTIN_CALLS = {
    'print', 'range', 'len', 'int', 'float', 'str', 'bool',
    'abs', 'min', 'max', 'sum', 'round', 'bin',
    'sorted', 'reversed', 'list', 'tuple', 'dict', 'set',
    'enumerate', 'zip', 'type',
}

ALLOWED_METHODS = {
    'append', 'pop', 'insert', 'remove', 'sort', 'reverse',
    'count', 'index', 'extend', 'clear', 'copy',
    'upper', 'lower', 'strip', 'split', 'join', 'replace',
    'find', 'startswith', 'endswith',
    'keys', 'values', 'items', 'get',
}

FORBIDDEN_MESSAGES = {
    ast.Import: 'Импорт модулей не разрешён',
    ast.ImportFrom: 'Импорт модулей не разрешён',
    ast.Global: 'Оператор global не разрешён',
    ast.Nonlocal: 'Оператор nonlocal не разрешён',
    ast.Delete: 'Оператор del не разрешён',
    ast.With: 'Оператор with не разрешён',
    ast.Try: 'Блок try/except не разрешён',
    ast.Raise: 'Оператор raise не разрешён',
    ast.Lambda: 'Lambda-функции не разрешены',
    ast.ClassDef: 'Определение классов не разрешено',
    ast.AsyncFunctionDef: 'Async-функции не разрешены',
    ast.AsyncFor: 'Async for не разрешён',
    ast.AsyncWith: 'Async with не разрешён',
    ast.Yield: 'Yield не разрешён',
    ast.YieldFrom: 'Yield from не разрешён',
    ast.GeneratorExp: 'Генераторы не разрешены',
}


def validate(code: str) -> tuple[bool, str]:
    if not code.strip():
        return False, 'Код не может быть пустым'

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f'Синтаксическая ошибка в строке {e.lineno}: {e.msg}'

    user_functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    for node in ast.walk(tree):
        node_type = type(node)

        if node_type in FORBIDDEN_MESSAGES:
            return False, FORBIDDEN_MESSAGES[node_type]

        if node_type not in ALLOWED_NODE_TYPES and node_type not in FORBIDDEN_MESSAGES:
            return False, f'Конструкция не разрешена: {node_type.__name__}'

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ALLOWED_BUILTIN_CALLS and node.func.id not in user_functions:
                    return False, f"Функция '{node.func.id}' не разрешена"
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in ALLOWED_METHODS:
                    return False, f"Метод '.{node.func.attr}()' не разрешён"

    return True, ''
