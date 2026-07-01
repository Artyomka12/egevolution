import sys
import copy

MAX_STEPS = 600

SAFE_BUILTINS = {
    'print': None,  # replaced at runtime
    'range': range,
    'len': len,
    'int': int,
    'float': float,
    'str': str,
    'bool': bool,
    'abs': abs,
    'min': min,
    'max': max,
    'sum': sum,
    'round': round,
    'bin': bin,
    'sorted': sorted,
    'reversed': reversed,
    'list': list,
    'tuple': tuple,
    'dict': dict,
    'set': set,
    'enumerate': enumerate,
    'zip': zip,
    'type': type,
    'True': True,
    'False': False,
    'None': None,
}


def _serialize(value, depth=0):
    if depth > 3:
        return '...'
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [_serialize(v, depth + 1) for v in value[:30]]
        return items
    if isinstance(value, dict):
        return {str(k): _serialize(v, depth + 1) for k, v in list(value.items())[:15]}
    if isinstance(value, set):
        return sorted([_serialize(v, depth + 1) for v in list(value)[:15]], key=str)
    return str(value)[:100]


def trace_code(code: str) -> dict:
    steps = []
    error_info = None

    initial_namespace_keys = set(SAFE_BUILTINS.keys()) | {
        '__builtins__', '__name__', '__doc__', '__package__', '__loader__', '__spec__'
    }

    captured_output = []

    def custom_print(*args, sep=' ', end='\n', **kwargs):
        text = sep.join(str(a) for a in args)
        captured_output.append(text)

    namespace = dict(SAFE_BUILTINS)
    namespace['print'] = custom_print
    namespace['__builtins__'] = {}

    def make_tracer():
        step_count    = [0]
        limit_hit     = [False]
        scope_counter = [0]
        # Each entry: (scope_id, func_name, depth, call_step_index)
        scope_stack   = []

        def collect_locals(frame):
            local_vars = {}
            for k, v in frame.f_locals.items():
                if k in initial_namespace_keys or k.startswith('_') or callable(v):
                    continue
                try:
                    local_vars[k] = _serialize(v)
                except Exception:
                    local_vars[k] = '<не отображается>'
            return local_vars

        def tracer(frame, event, arg):
            if frame.f_code.co_filename != 'user_code':
                return None

            # Module-level call/return are not user function calls — skip recording them
            if frame.f_code.co_name == '<module>' and event in ('call', 'return'):
                return tracer

            if event == 'call':
                scope_counter[0] += 1
                sid   = scope_counter[0]
                # parent = innermost scope on stack, or 0 (global) if stack empty
                pid   = scope_stack[-1][0] if scope_stack else 0
                depth = len(scope_stack)       # depth 0 = called from global
                name  = frame.f_code.co_name
                scope_stack.append((sid, name, depth, len(steps)))

                # Record call step — args collected on first line event inside function
                steps.append({
                    'event':      'call',
                    'scope_id':   sid,
                    'parent_id':  pid,
                    'scope_name': name,
                    'args':       {},           # populated on first line inside
                    'depth':      depth,
                    'line':       frame.f_lineno,
                    'variables':  {},
                    'output':     list(captured_output),
                })
                return tracer

            if event == 'return':
                ret_val = None
                try:
                    ret_val = _serialize(arg)
                except Exception:
                    ret_val = '<не отображается>'

                if scope_stack:
                    sid, name, depth, _ = scope_stack.pop()
                else:
                    sid, name, depth = 0, '<module>', 0

                steps.append({
                    'event':        'return',
                    'scope_id':     sid,
                    'scope_name':   name,
                    'return_value': ret_val,
                    'depth':        depth,
                    'line':         frame.f_lineno,
                    'variables':    collect_locals(frame),
                    'output':       list(captured_output),
                })
                return tracer

            if event == 'line':
                if step_count[0] >= MAX_STEPS:
                    limit_hit[0] = True
                    return tracer

                step_count[0] += 1
                sid   = scope_stack[-1][0] if scope_stack else 0
                name  = scope_stack[-1][1] if scope_stack else '<module>'
                depth = scope_stack[-1][2] if scope_stack else 0

                local_vars = collect_locals(frame)

                # Back-fill args into the preceding call step on first line of a function
                if scope_stack:
                    call_idx = scope_stack[-1][3]
                    if call_idx < len(steps) and not steps[call_idx]['args']:
                        steps[call_idx]['args']      = copy.deepcopy(local_vars)
                        steps[call_idx]['variables'] = copy.deepcopy(local_vars)

                steps.append({
                    'event':      'line',
                    'scope_id':   sid,
                    'scope_name': name,
                    'depth':      depth,
                    'line':       frame.f_lineno,
                    'variables':  copy.deepcopy(local_vars),
                    'output':     list(captured_output),
                })

            return tracer

        return tracer, limit_hit

    tracer_fn, limit_hit = make_tracer()

    try:
        compiled = compile(code, 'user_code', 'exec')
        sys.settrace(tracer_fn)
        exec(compiled, namespace)
    except Exception as e:
        error_info = {
            'type': type(e).__name__,
            'message': str(e),
            'line': getattr(e, 'lineno', None),
        }
    finally:
        sys.settrace(None)

    # Final global variable state
    final_vars = {}
    for k, v in namespace.items():
        if k in initial_namespace_keys or k.startswith('_') or callable(v):
            continue
        try:
            final_vars[k] = _serialize(v)
        except Exception:
            final_vars[k] = '<не отображается>'

    final_output = list(captured_output)

    # Synthetic final step (global scope)
    if error_info is None and not limit_hit[0]:
        last_line = next(
            (s for s in reversed(steps) if s.get('event', 'line') == 'line'),
            None
        )
        if last_line is None or last_line['output'] != final_output or last_line['variables'] != final_vars:
            last_lineno = last_line['line'] if last_line else 1
            steps.append({
                'event':      'line',
                'scope_id':   0,
                'scope_name': '<module>',
                'depth':      0,
                'line':       last_lineno,
                'variables':  copy.deepcopy(final_vars),
                'output':     final_output,
                'final':      True,
            })

    return {
        'steps':       steps,
        'error':       error_info,
        'truncated':   limit_hit[0],
        'total_lines': len(code.splitlines()),
    }
