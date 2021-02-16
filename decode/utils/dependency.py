import copy
from typing import Iterable

import yaml


def convert_mixed_list(mix) -> dict:
    """Convert a list of elements and dicts to list of dicts (with None values for non dicts)"""

    mix_dict = dict.fromkeys([k for k in mix if not isinstance(k, dict)])
    for k in [k for k in mix if isinstance(k, dict)]:  # limit to dicts
        mix_dict.update(k)

    return mix_dict


def convert_to_spec(package):
    """Convert yaml style '=' to '==' as in spec."""
    if '=' not in package or '<' in package or '>' in package:
        return package
    return package.replace('=', '==')


def add_update_package(deps: dict, update: dict, level: Iterable) -> dict:
    """Adds or updates a package"""

    update = {k: v for k,v in update.items() if k in level}  # limit to active levels
    for n_deps in update.values():  # loop over level
        for k, v in n_deps.items():
            if k in deps:
                deps[v] = deps.pop(k)
            else:
                deps[k] = None

    return deps


def conda(run_deps, dev_deps, doc_deps, channels, level, mode):
    """
    Generate conda environment or spec file.

    Args:
        run_deps:
        dev_deps:
        doc_deps:
        channels:
        level: which level, i.e. 'run' or 'dev' or ('dev', 'docs')
        mode: either environment file (env) or specs (txt)

    """
    level = (level, ) if not isinstance(level, tuple) else level

    name = 'decode'

    deps = dict.fromkeys(run_deps)
    if 'dev' in level:
        deps.update(dict.fromkeys(dev_deps))
        name += '_dev'
    if 'docs' in level:
        deps.update(dict.fromkeys(doc_deps))
        name += '_docs'

    if mode == 'txt':
        return [convert_to_spec(o) for o in deps]

    elif mode == 'env':
        out = {
            'name': name,
            'channels': channels,
            'dependencies': list(deps.keys())
        }

        return out


def conda_meta(run_deps, meta):

    deps = conda(run_deps, None, None, None, 'run', 'env')['dependencies']
    deps = dict.fromkeys(deps)

    # apply meta changes to environment
    deps = add_update_package(deps, meta, ('run', ))

    build = copy.copy(meta)
    build['run'] = list(deps.keys())

    return build


def pip(run_deps, dev_deps, doc_deps, pip, level, recurse_run: str = None):

    deps = dict()

    if recurse_run is None:
        level = (level,) if not isinstance(level, tuple) else level

        if 'run' in level:
            deps.update(dict.fromkeys(run_deps))
        if 'dev' in level:
            deps.update(dict.fromkeys(dev_deps))
        if 'docs' in level:
            deps.update(dict.fromkeys(doc_deps))

    else:
        deps.update({'-r ' + recurse_run: None})
        if level == 'dev':
            deps.update(dict.fromkeys(dev_deps))
        elif level == 'docs':
            deps.update(dict.fromkeys(doc_deps))
        else:
            raise ValueError

    deps = add_update_package(deps, pip, level)

    return [convert_to_spec(p) for p in deps]


def parse_dependency(path) -> dict:

    with open(path, 'r') as stream:
        data = yaml.safe_load(stream)

    for k, v in data['pip'].items():
        data['pip'][k] = convert_mixed_list(v)

    data['conda-build']['run'] = convert_mixed_list(data['conda-build']['run'])

    return data


if __name__ == '__main__':
    from pathlib import Path
    import argparse
    import textwrap

    parser = argparse.ArgumentParser()
    parser.add_argument('--deps', '-d')
    parser.add_argument('--meta', '-m')
    parser.add_argument('--out', '-o')
    args = parser.parse_args()

    path_yaml = Path(args.deps)
    path_meta = Path(args.meta)
    path_out_dir = Path(args.out)

    data = parse_dependency(path_yaml)

    comment = '# This file or block is auto-generated and must not be edited directly. Refer to dependencies.yaml'

    # generate requirements for pip
    for level in ['run', 'dev', 'docs']:
        file_suffix = level if isinstance(level, str) else f'{level[0]}_{level[1]}'

        if level != 'run':
            recurse_run = 'requirements_run.txt'
        else:
            recurse_run = None

        out = pip(run_deps=data['run'], dev_deps=data['dev'], doc_deps=data['docs'],
                  pip=data['pip'], level=level, recurse_run=recurse_run)

        with (path_out_dir / f'requirements_{file_suffix}.txt').open(mode='w+') as outfile:
            outfile.write(comment + '\n')
            outfile.write("\n".join(out))

    # generate conda environments
    for level in ['run', 'dev', 'docs']:

        out = conda(run_deps=data['run'], dev_deps=data['dev'], doc_deps=data['docs'],
                    channels=data['conda']['channels'], level=level, mode='env')

        with (path_out_dir / f'environment_{level}.yaml').open(mode='w+') as outfile:
            outfile.write(comment + '\n')
            yaml.dump(out, outfile, sort_keys=False)

    # modify meta.yaml
    meta = path_meta.read_text()
    split_pattern = '# @AUTO_GENERATED'

    meta_ = meta.split(split_pattern)
    meta_.insert(1, split_pattern + '\nrequirements:\n')
    meta_[2] = textwrap.indent(
        yaml.dump(conda_meta(run_deps=data['run'], meta=data['conda-build']), sort_keys=False),
        '  ')
    meta_.insert(3, split_pattern)

    (path_out_dir / 'meta.yaml').write_text(''.join(meta_))
