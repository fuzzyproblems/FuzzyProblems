"""Validated project-relative destinations and source links for learner exports."""
import pipeline_core as v
import workflow as w


def parts(folder):
    if not isinstance(folder, str) or not folder or '\\' in folder:
        raise ValueError('Use a portable output folder with forward slashes')
    names = folder.split('/')
    if any(not name for name in names):
        raise ValueError('Empty output folder component')
    for name in names:
        w.safe_name(name)
    return names


def target(folder):
    names = ['output', *parts(folder)]
    parent = w.safe_tree(v.ROOT)
    for name in names:
        if parent.exists():
            if not parent.is_dir():
                raise ValueError('Output parent is not a directory')
            if any(item.name.casefold() == name.casefold() and item.name != name
                   for item in parent.iterdir()):
                raise ValueError('Output folder case conflicts with an existing path')
        parent = w.safe_tree(parent / name)
    if parent.exists() and not parent.is_dir():
        raise ValueError('Output destination is not a directory')
    return parent


def configured_folder(pack):
    config = w.safe_tree(pack / 'delivery.json')
    if not config.exists():
        return None
    if not config.is_file():
        raise ValueError('Delivery configuration must be a regular file')
    data = v.read(config)
    if not isinstance(data, dict) or set(data) != {'folder'}:
        raise ValueError('Invalid delivery configuration')
    target(data['folder'])
    return data['folder']


def source_prefix(pack):
    folder = configured_folder(pack)
    return '../' * (1 + len(parts(folder))) if folder else '../../'


def source_link(pack, source_path):
    return source_prefix(pack) + source_path
