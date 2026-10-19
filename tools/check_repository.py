"""Check the repository without launching services or fault experiments."""
import ast
import hashlib
import json
import re
import struct
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.work', 'results', '__pycache__', '.venv', 'venv'}


def source_value(node, bindings, current):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [source_value(element, bindings, current) for element in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return source_value(node.left, bindings, current) / source_value(node.right, bindings, current)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return source_value(node.left, bindings, current) + source_value(node.right, bindings, current)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'sorted' and len(node.args) == 1 and not node.keywords:
        return sorted(source_value(node.args[0], bindings, current))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'glob' and len(node.args) == 1:
        base = source_value(node.func.value, bindings, current)
        if not isinstance(base, Path):
            raise ValueError('Only local Path glob is supported')
        return list(base.glob(source_value(node.args[0], bindings, current)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Path' and len(node.args) == 1:
        arg = node.args[0]
        if isinstance(arg, ast.Name) and arg.id == '__file__':
            return current
        return Path(source_value(arg, bindings, current))
    if isinstance(node, ast.ListComp) and len(node.generators) == 1:
        generator = node.generators[0]
        if not isinstance(generator.target, ast.Name) or generator.ifs:
            raise ValueError('Dynamic comprehension')
        return [source_value(node.elt, {**bindings, generator.target.id: item}, current)
                for item in source_value(generator.iter, bindings, current)]
    raise ValueError('Dynamic expression')


def check(root=ROOT):
    failures = []
    files = [p for p in root.rglob('*') if p.is_file() and not (set(p.relative_to(root).parts) & IGNORED)]
    labs = sorted((root / 'labs').glob('[0-9][0-9][0-9]-*'))
    assert len(labs) == 50, f'Expected 50 labs, found {len(labs)}'
    counts = {'labs': len(labs), 'python_files': 0, 'markdown_files': 0,
              'png_files': 0, 'source_input_references': 0, 'fixed_data_references': 0}
    for lab in labs:
        for relative in ['README.md', 'scripts/reproduce.ps1']:
            if not (lab / relative).is_file():
                failures.append(f'Missing {lab.name}/{relative}')
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix == '.py':
            text = path.read_text(encoding='utf-8')
            tree = ast.parse(text, filename=relative)
            compile(tree, relative, 'exec')
            counts['python_files'] += 1
            if relative.startswith('labs/'):
                lab = root / 'labs' / path.relative_to(root).parts[1]
                bindings = {'LAB': lab, 'ROOT': root}
                for statement in ast.walk(tree):
                    if isinstance(statement, ast.Assign):
                        try:
                            value = source_value(statement.value, bindings, path)
                        except (ValueError, TypeError, KeyError):
                            continue
                        for target in statement.targets:
                            if isinstance(target, ast.Name):
                                bindings[target.id] = value
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Evidence' and len(node.args) >= 3:
                        try:
                            inputs = source_value(node.args[2], bindings, path)
                        except (ValueError, TypeError, KeyError):
                            failures.append(f'Cannot resolve source inputs: {relative}:{node.lineno}')
                            continue
                        for item in inputs:
                            counts['source_input_references'] += 1
                            if not isinstance(item, Path) or not item.is_file():
                                failures.append(f'Missing source input: {relative}: {item}')
                # Local imported modules must remain available; optional installed
                # packages are declared by the experiment's setup/requirements.
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom) or not node.module:
                        continue
                    name = node.module.split('.')[0]
                    if name in {'evidence', 'http_capture', 'mysql_session', 'redis_session', 'mysql_cartesian'}:
                        if not (root / 'shared/scripts' / (name + '.py')).exists():
                            failures.append(f'Missing shared import {name}: {relative}')
        elif path.suffix == '.md':
            counts['markdown_files'] += 1
            text = re.sub(r'(?ms)^(```|~~~).*?^\1\s*$', '', path.read_text(encoding='utf-8'))
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
                if re.match(r'^[a-zA-Z]+:', target) or target.startswith('#'):
                    continue
                target = unquote(target.split('#', 1)[0].split('?', 1)[0])
                if target and not (path.parent / target).resolve().exists():
                    failures.append(f'Broken link: {relative}: {target}')
        elif path.suffix == '.png':
            data = path.read_bytes()
            if data[:8] != b'\x89PNG\r\n\x1a\n' or len(data) < 24 or not all(struct.unpack('>II', data[16:24])):
                failures.append(f'Invalid PNG: {relative}')
            counts['png_files'] += 1
    spec = json.loads((root / 'labs/029-rag-hybrid-search/input-spec.json').read_text(encoding='utf-8'))
    for name, item in spec['files'].items():
        path = root / item['path']
        counts['fixed_data_references'] += 1
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            failures.append(f'Invalid fixed data: {name}')
    assert counts['png_files'] == 50, counts
    if failures:
        raise SystemExit('\n'.join(failures))
    print(json.dumps({'status': 'PASS', **counts}, ensure_ascii=False))
    return counts


if __name__ == '__main__':
    check()
