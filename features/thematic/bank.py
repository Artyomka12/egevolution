"""Read-only bank adapter and a deliberately small condition markup allowlist."""
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from .grading import answer_spec
from .validation import digest, validate_sources


class ConditionParser(HTMLParser):
    tags = set('p br sup sub b i strong em u ul ol li code pre table thead tbody tr th td caption'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.tags:
            safe = ''
            for key, value in attrs:
                if tag in {'td', 'th'} and key in {'colspan', 'rowspan'} and value and value.isdigit() and 1 <= int(value) <= 100:
                    safe += f' {key}="{int(value)}"'
            self.parts.append(f'<{tag}{safe}>')

    def handle_endtag(self, tag):
        if tag in self.tags and tag != 'br':
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(escape(data))


def condition_html(text):
    text = re.sub(r'\[(/?)(sup|sub|b|i|strong|em|u|ul|ol|li|code|pre)\]', r'<\1\2>', text)
    parser = ConditionParser()
    parser.feed(text)
    parser.close()
    return ''.join(parser.parts)


def safe_path(root, relative):
    root = Path(root).resolve(strict=True)
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Недопустимый путь материала')
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Материал находится вне банка')
    return path


class Bank:
    def __init__(self, root):
        self.root = Path(root)

    def tasks(self, number):
        if type(number) is not int or not 1 <= number <= 27:
            raise ValueError('Номер ЕГЭ должен быть от 1 до 27')
        path = safe_path(self.root, f'task_{number:02d}/tasks.json')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        tasks = data['tasks']
        validate_sources([{'source_task_num': number, 'source_task_id': t['id']} for t in tasks], allow_empty=True)
        return tasks

    def task(self, number, ident):
        for task in self.tasks(number):
            if task['id'] == ident:
                answer_spec(task)
                return task
        raise ValueError(f'Задача №{number}, ID {ident} отсутствует в банке')

    def materials(self, number, task):
        images = task.get('images') or []
        files = task.get('files') or ([task['file']] if task.get('file') else [])
        result = []
        for role, entries, folder in [('condition', images, 'images'), ('attachment', files, 'files')]:
            for position, item in enumerate(entries, 1):
                # Bank metadata may be edited elsewhere; filenames are not paths.
                if not isinstance(item, dict) or not isinstance(item.get('path'), str) or '/' in item['path'] or '\\' in item['path']:
                    raise ValueError('Недопустимое имя материала задачи')
                path = safe_path(self.root, f'task_{number:02d}/{folder}/{item["path"]}')
                result.append({'role': role, 'position': position, 'source_path': item['path'],
                               'path': path, 'original': item})
        return result

    def dto(self, number, task):
        # No answer keys or arbitrary filesystem paths in the bank response.
        return {'source_task_num': number, 'source_task_id': task['id'],
                'title': task.get('title') or f'Задание №{number} · ID {task["id"]}',
                'description_html': [condition_html(p) for p in task['description']],
                'source_hash': digest(task),
                'materials': [{'role': m['role'], 'position': m['position'],
                    'alt': m['original'].get('alt', ''),
                    'after_paragraph': m['original'].get('after_paragraph'),
                    'name': m['path'].name,
                    'url': f'/api/admin/thematic-bank/{number}/{task["id"]}/media/{m["role"]}/{m["position"]}'}
                    for m in self.materials(number, task)]}
