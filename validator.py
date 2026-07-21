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
    ast.ListComp, ast.GeneratorExp, ast.comprehension,
    ast.FunctionDef, ast.arguments, ast.arg, ast.keyword,
    ast.Import, ast.ImportFrom, ast.alias,
}

# Модули, которые можно импортировать целиком (реальный import, без подмены) —
# math сознательно не входит (решение пользователя, не нужен). 'sys' обрабатывается
# отдельно в _check_import()/tracer.py — не настоящий импорт, а заглушка только
# под sys.setrecursionlimit().
ALLOWED_IMPORT_MODULES = {'re', 'itertools'}

ALLOWED_BUILTIN_CALLS = {
    'print', 'range', 'len', 'int', 'float', 'str', 'bool',
    'abs', 'min', 'max', 'sum', 'round', 'bin',
    'sorted', 'reversed', 'list', 'tuple', 'dict', 'set',
    'enumerate', 'zip', 'type',
    'open',
    'any', 'all',
}

ALLOWED_METHODS = {
    'append', 'pop', 'insert', 'remove', 'sort', 'reverse',
    'count', 'index', 'extend', 'clear', 'copy',
    'upper', 'lower', 'strip', 'split', 'join', 'replace',
    'find', 'startswith', 'endswith',
    'keys', 'values', 'items', 'get',
    # re — как функции модуля (re.findall(...)), так и методы Pattern/Match объектов
    # (re.compile(...).findall(...), match.group()) — проверка по имени атрибута общая,
    # отдельно от того, на каком объекте вызвано.
    'findall', 'finditer', 'match', 'fullmatch', 'search', 'sub', 'compile',
    'group', 'groups', 'span', 'start', 'end',
    # itertools — функции модуля
    'permutations', 'combinations', 'product', 'count', 'chain', 'groupby', 'accumulate',
    # sys — единственный разрешённый метод фейковой заглушки (см. tracer.py)
    'setrecursionlimit',
    # open() — методы файлового объекта (io.StringIO, см. tracer.py)
    'read', 'readline', 'readlines', 'close',
}

FORBIDDEN_MESSAGES = {
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
}


def _check_import(node) -> tuple[bool, str]:
    """Проверяет один узел ast.Import/ast.ImportFrom против whitelist модулей.
    'sys' — не настоящий модуль (см. tracer.py), разрешён только как
    ровно 'import sys', без 'as' и без 'from sys import ...'."""
    if isinstance(node, ast.Import):
        if len(node.names) != 1:
            return False, 'В одной строке можно импортировать только один модуль'
        alias = node.names[0]
        if alias.name == 'sys':
            if alias.asname is not None:
                return False, "Модуль 'sys' можно импортировать только как 'import sys', без алиаса"
            return True, ''
        if alias.name not in ALLOWED_IMPORT_MODULES:
            return False, f"Модуль '{alias.name}' не разрешён"
        return True, ''

    if isinstance(node, ast.ImportFrom):
        if node.module not in ALLOWED_IMPORT_MODULES:
            return False, f"Модуль '{node.module}' не разрешён"
        return True, ''

    return True, ''


def validate(code: str) -> tuple[bool, str]:
    if not code.strip():
        return False, 'Код не может быть пустым'

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f'Синтаксическая ошибка в строке {e.lineno}: {e.msg}'

    user_functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    # Имена, попавшие в locals через 'from re import findall' — далее вызываются
    # голым именем (findall(...)), а не через атрибут, поэтому это не покрывается
    # проверкой ALLOWED_METHODS и должно отдельно попасть в список разрешённых имён.
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    for node in ast.walk(tree):
        node_type = type(node)

        if node_type in (ast.Import, ast.ImportFrom):
            ok, msg = _check_import(node)
            if not ok:
                return False, msg
            continue

        if node_type in FORBIDDEN_MESSAGES:
            return False, FORBIDDEN_MESSAGES[node_type]

        if node_type not in ALLOWED_NODE_TYPES and node_type not in FORBIDDEN_MESSAGES:
            return False, f'Конструкция не разрешена: {node_type.__name__}'

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if (node.func.id not in ALLOWED_BUILTIN_CALLS
                        and node.func.id not in user_functions
                        and node.func.id not in imported_names):
                    return False, f"Функция '{node.func.id}' не разрешена"
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in ALLOWED_METHODS:
                    return False, f"Метод '.{node.func.attr}()' не разрешён"

    return True, ''
