#!/usr/bin/env python3
"""
Flexible kustomization.yaml TCP/NodePort patch updater using ruamel.yaml
Supports different patch paths and mapping styles.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Optional, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096
yaml.preserve_quotes = True


# ── Configuration of supported patch types ──────────────────────────────────────

PATCH_TYPES = {
    "tcp": {
        "path": "/spec/values/tcp",
        "format": lambda k, v: f"{k}: {v}",                    # hostPort: ns/svc:port
        "key_name": "host_port",
        "value_factory": lambda ns, svc, cp: f"{ns}/{svc}:{cp}",
        "arg_names": ["namespace", "service", "container_port"],
        "second_arg_names": ["second-host", "second-container"],
    },
    "nodeport": {
        "path": "/spec/values/controller/service/nodePorts/tcp",
        "format": lambda k, v: f"{k}: {v}",                    # nodePort: containerPort
        "key_name": "node_port",
        "value_factory": lambda *args: str(args[2]),           # just container port
        "arg_names": ["container_port"],
        "second_arg_names": ["second-node", "second-container"],
        "value_is_int": True,
    }
}


def parse_existing_mappings(patch_content: str, target_path: str) -> Dict[str, str]:
    """Extract current key:value mappings from patch text"""
    current = {}
    lines = patch_content.splitlines()
    in_value_block = False

    for line in lines:
        stripped = line.rstrip()
        if stripped.strip() == 'value: |':
            in_value_block = True
            continue
        if in_value_block and ':' in stripped and stripped.lstrip().startswith(('0','1','2','3','4','5','6','7','8','9')):
            try:
                _, rest = line.split(':', 1)
                key, value = rest.split(':', 1) if ':' in rest else (rest.strip(), '')
                key = key.strip()
                value = value.strip()
                if key.isdigit():
                    current[key] = value
            except:
                pass
    return current


def build_patch_text(path: str, mappings: Dict[str, str]) -> str:
    lines = [
        "- op: add",
        f"  path: {path}",
        "  value: |"
    ]

    for k in sorted(mappings.keys(), key=int):
        lines.append(f"    {k}: {mappings[k]}")

    if not mappings:
        lines.append("    {}")

    return "\n".join(lines)


def update_patch(
    data: dict,
    patch_type: str,
    main_key: int,
    main_args: list,
    second_pair: Optional[Tuple[int, int]] = None
) -> dict:
    cfg = PATCH_TYPES[patch_type]
    target_path = cfg["path"]

    # Prepare new mapping(s)
    value_factory = cfg["value_factory"]
    new_mappings = {}

    if patch_type == "tcp":
        ns, svc, cp = main_args
        new_mappings[str(main_key)] = value_factory(ns, svc, cp)
    else:  # nodeport
        cp = main_args[0]
        new_mappings[str(main_key)] = value_factory(None, None, cp)

    if second_pair:
        k2, v2 = second_pair
        if patch_type == "tcp":
            new_mappings[str(k2)] = value_factory(ns, svc, v2)
        else:
            new_mappings[str(k2)] = value_factory(None, None, v2)

    # Find existing patch
    patch_index = -1
    existing_patch = None
    patches = data.get('patches', [])

    for i, item in enumerate(patches):
        if isinstance(item, dict) and 'patch' in item:
            content = str(item['patch'])
            if f'path: {target_path}' in content and '- op: add' in content:
                patch_index = i
                existing_patch = item
                break

    # Get current mappings
    current_mappings = {}
    if existing_patch:
        current_mappings = parse_existing_mappings(str(existing_patch['patch']), target_path)

    # Merge (new overrides old)
    current_mappings.update(new_mappings)

    # Build and wrap new patch
    patch_text = build_patch_text(target_path, current_mappings)
    new_patch_entry = {'patch': LiteralScalarString(patch_text)}

    if patch_index >= 0:
        data['patches'][patch_index] = new_patch_entry
        print(f"Updated existing {patch_type} patch → added/updated {main_key}")
        if second_pair:
            print(f"                           + {second_pair[0]}")
    else:
        if 'patches' not in data:
            data['patches'] = []
        data['patches'].append(new_patch_entry)
        print(f"Created new {patch_type} patch → added {main_key}")
        if second_pair:
            print(f"                    + {second_pair[0]}")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Update different types of port patches in kustomization.yaml",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("patch_type", choices=list(PATCH_TYPES.keys()),
                        help="Type of patch to update\n  tcp       → /spec/values/tcp\n  nodeport  → /spec/values/controller/service/nodePorts/tcp")

    parser.add_argument("--file", default="kustomization.yaml",
                        help="Path to kustomization.yaml")

    parser.add_argument("--dry-run", action="store_true")

    # Common positional args will be checked based on type
    parser.add_argument("main_key", type=int, help="Primary port (host_port or node_port)")
    parser.add_argument("extra_args", nargs="*", help="Additional arguments depending on patch_type")

    # Second pair (optional for both types)
    parser.add_argument("--second", type=int, nargs=2, metavar=("KEY", "PORT"),
                        help="Second pair: key containerPort (for both types)")

    args = parser.parse_args()

    cfg = PATCH_TYPES[args.patch_type]
    expected_count = len(cfg["arg_names"])

    if len(args.extra_args) != expected_count:
        parser.error(
            f"For patch_type '{args.patch_type}' expected {expected_count} extra arguments "
            f"({', '.join(cfg['arg_names'])}), got {len(args.extra_args)}"
        )

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    with open(file_path, encoding='utf-8') as f:
        data = yaml.load(f) or {}

    second_pair = None
    if args.second:
        second_pair = tuple(args.second)

    updated = update_patch(
        data,
        args.patch_type,
        args.main_key,
        args.extra_args,
        second_pair
    )

    if args.dry_run:
        print("\n--- DRY RUN --------------------------------")
        yaml.dump(updated, sys.stdout)
        print("--------------------------------------------\n")
    else:
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(updated, f)
        print(f"Updated: {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
