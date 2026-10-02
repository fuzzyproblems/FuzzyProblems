"""User-provided deck labels. No account lookup; no educational approval."""
import re
import unicodedata

import pipeline_core as v
import workflow as w

FIELDS = ('school', 'course', 'lesson')


def segment(value):
    if not isinstance(value, str):
        raise ValueError('Anki labels must be text')
    value = unicodedata.normalize('NFC', value).strip()
    # Unicode is retained; delimiters/whitespace cannot create unintended tags.
    return re.sub(r'[^\w.+-]+', '_', value, flags=re.UNICODE).strip('_.')


def initialize(p, lesson):
    previous = v.BASE / 'preferences/anki.json'
    defaults = v.read(previous) if previous.is_file() else {}
    row = {'version': 1, 'status': 'pending_user_input', 'school': defaults.get('school', ''),
           'course': defaults.get('course', ''), 'lesson': lesson, 'tasks': {}}
    v.write(w.safe_tree(p / 'anki-tags.json'), row)
    return prompt(p)


def prompt(p):
    return {'question': 'How would you like this deck tagged? Supply School/Institution (optional), Course/Module, '
                        'Lesson/Topic, and any Task/Objective labels. Goal numbers are used for tasks unless overridden. '
                        'You may explicitly choose the suggested defaults.',
            'suggested': v.read(p / 'anki-tags.json'), 'status': 'awaiting_user_tag_preferences'}


def configure(p, school=None, course=None, lesson=None, tasks=None, use_defaults=False, interactive=False):
    scope = v.read(p / 'scope.json')
    row = v.read(p / 'anki-tags.json') if (p / 'anki-tags.json').exists() else {
        'version': 1, 'status': 'pending_user_input', 'school': '', 'course': '',
        'lesson': v.read(p / 'content.json')['lesson_label'], 'tasks': {}}
    if interactive:
        import sys
        if not sys.stdin.isatty():
            return prompt(p)
        for key, label in [('school', 'School/Institution'), ('course', 'Course/Module'), ('lesson', 'Lesson/Topic')]:
            answer = input(f'{label} [{row[key]}]: ').strip()
            if answer:
                row[key] = answer
        answer = input('Task name/code for a single-goal deck (blank keeps goal numbering): ').strip()
        if answer:
            if len(scope['objective_ids']) != 1:
                raise ValueError('For multiple goals provide --tasks-json keyed by objective ID')
            row['tasks'] = {scope['objective_ids'][0]: answer}
    elif not use_defaults and all(x is None for x in (school, course, lesson, tasks)):
        return prompt(p)
    for key, value in [('school', school), ('course', course), ('lesson', lesson)]:
        if value is not None:
            row[key] = value.strip()
    if tasks is not None:
        if not isinstance(tasks, dict) or not set(tasks) <= set(scope['objective_ids']):
            raise ValueError('Task labels must map current objective IDs to names/codes')
        row['tasks'] = tasks
    for value in list(row[k] for k in FIELDS) + list(row['tasks'].values()):
        if value and not segment(value):
            raise ValueError('A supplied Anki label has no usable characters')
    row['status'] = 'user_configured'
    row['selection'] = 'explicit_defaults' if use_defaults else 'user_labels'
    v.write(w.safe_tree(p / 'anki-tags.json'), row)
    v.write(w.safe_tree(v.BASE / 'preferences/anki.json'), {k: row[k] for k in ('school', 'course')})
    return {'status': 'tag_preferences_saved', 'file': (p / 'anki-tags.json').relative_to(v.ROOT).as_posix(),
            'requires_rebuild': ['Anki', 'artifact_validation'], 'educational_approval': False}


def read_for(scope):
    if not scope.get('anki_preferences_required'):
        return None
    path = w.pack(scope['pack_id']) / 'anki-tags.json'
    if not path.is_file() or (row := v.read(path)).get('status') != 'user_configured':
        raise ValueError('Ask the user for School/Course/Lesson/Task tag preferences, then run anki-tags; explicit defaults are allowed')
    if row.get('version') != 1 or not set(row.get('tasks', {})) <= set(scope['objective_ids']):
        raise ValueError('Anki preferences refer to an unsupported version or unknown goal')
    return row


def tags(scope, objectives):
    row = read_for(scope)
    if row is None:
        return {}
    prefix = [segment(row.get(k, '')) for k in FIELDS]
    prefix = [part for part in prefix if part]
    result = {}; used = {}
    for objective in objectives:
        oid = objective['id']
        label = row.get('tasks', {}).get(oid) or 'Task_' + objective['original_number']
        task = segment(label)
        occurrence = objective.get('number_occurrence', 1)
        if occurrence > 1 and oid not in row.get('tasks', {}):
            task += '_occurrence_' + str(occurrence)
        tag = '::'.join(prefix + [task])
        if not task or (tag.casefold() in used and used[tag.casefold()] != oid):
            raise ValueError('Task labels collide after tag normalisation; give each task a distinct label')
        used[tag.casefold()] = oid
        result[oid] = tag
    return result
