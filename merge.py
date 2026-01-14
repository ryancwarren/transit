#!/usr/bin/env python3
"""
Update different kinds of port patches in kustomization.yaml
Supports multiple patch types with clean literal block style (using ruamel.yaml)
"""

import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096
yaml.preserve_quotes = True
yaml.allow_duplicate_keys = False


# ── Supported patch types configuration ─────────────────────────────────────────

PATCH_TYPES = {
    "tcp": {
        "path": "/spec/values/tcp",
        "description": "Host port → namespace/service:containerPort",
        "key_arg": "host_port",
        "value_args": ["namespace", "service", "container_port"],
        "value_fmt": "{ns}/{svc}:{cp}",
        "second_args": ["--second-host", "--second-container"],
    },
    "nodeport": {
        "path": "/spec/values/controller/service/nodePorts/tcp",
        "description": "NodePort → containerPort",
        "key_arg": "node_port",
        "value_args": ["container_port"],
        "value_fmt": "{cp}",
        "second_args": ["--second-node", "--second-container"],
    }
}


def find_patch_index(patches: list, target_path: str) -> int:
    """Find index of existing patch with given path"""
    for i, item in enumerate(patches):
        if not isinstance(item, dict) or 'patch' not in item:
            continue
        content = str(item['patch'])
        if f'path: {target_path}' in content and '- op: add' in content:
            return i
    return -1


def parse_port_mappings(patch_text: str) -> Dict[str, str]:
    """Extract port mappings from literal block"""
    mappings = {}
    lines = patch_text.splitlines()
    in_value = False

    for line in lines:
        s = line.rstrip()
        if s.strip() == 'value: |':
            in_value = True
            continue
        if in_value and ':' in s and s.lstrip().startswith(('0','1','2','3','4','5','6','7','8','9')):
            # Remove leading indentation, split on first colon
            content = s.lstrip()
            try:
                key, value = content.split(':', 1)
                key = key.strip()
                value = value.strip()
                if key.isdigit():
                    mappings[key] = value
            except ValueError:
                continue
    return mappings


def build_patch_content(path: str, mappings: Dict[str, str]) -> LiteralScalarString:
    """Create clean literal block patch content"""
    lines = [
        "- op: add",
        f"  path: {path}",
        "  value: |"
    ]

    for port in sorted(mappings, key=int):
        lines.append(f"    {port}: {mappings[port]}")

    if not mappings:
        lines.append("    {}  # empty - will be replaced")

    return LiteralScalarString("\n".join(lines))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add/update port mappings in kustomization.yaml patches",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("type", choices=sorted(PATCH_TYPES.keys()),
                        help="Patch type to modify")

    parser.add_argument("main_key", type=int,
                        help="Primary port number (host_port / node_port)")

    parser.add_argument("--file", default="kustomization.yaml",
                        help="kustomization.yaml file to modify")

    parser.add_argument("--dry-run", action="store_true",
                        help="Only show what would be written")

    # Will be populated dynamically based on type
    # Second pair is always optional
    parser.add_argument("--second", nargs=2, type=int, metavar=("KEY", "PORT"),
                        help="Optional second port pair")

    args = parser.parse_args()

    cfg = PATCH_TYPES[args.type]

    # Build dynamic parser for value arguments
    value_group = parser.add_argument_group(f"{args.type.upper()} required arguments")
    for arg_name in cfg["value_args"]:
        if arg_name == "container_port":
            value_group.add_argument(arg_name, type=int)
        else:
            value_group.add_argument(arg_name)

    # Re-parse with the full set of arguments
    args = parser.parse_args()

    # Get value arguments in order
    value_values = [getattr(args, name) for name in cfg["value_args"]]

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    # Load preserving style/comments
    try:
        with open(file_path, encoding='utf-8') as f:
            data = yaml.load(f) or {}
    except Exception as e:
        print(f"Error loading YAML: {e}", file=sys.stderr)
        return 1

    # Prepare new mapping(s)
    new_mappings = {}
    key_str = str(args.main_key)

    if args.type == "tcp":
        ns, svc, cp = value_values
        new_mappings[key_str] = f"{ns}/{svc}:{cp}"
    else:  # nodeport
        cp, = value_values
        new_mappings[key_str] = str(cp)

    if args.second:
        s_key, s_port = args.second
        s_key_str = str(s_key)
        if args.type == "tcp":
            new_mappings[s_key_str] = f"{ns}/{svc}:{s_port}"
        else:
            new_mappings[s_key_str] = str(s_port)

    # Find or prepare patch
    patches = data.setdefault('patches', [])
    idx = find_patch_index(patches, cfg["path"])

    current_mappings = {}
    if idx >= 0:
        current_mappings = parse_port_mappings(str(patches[idx]['patch']))

    # Apply update
    current_mappings.update(new_mappings)

    # Build new patch
    new_content = build_patch_content(cfg["path"], current_mappings)

    new_patch = {'patch': new_content}

    if idx >= 0:
        patches[idx] = new_patch
        action = "Updated"
    else:
        patches.append(new_patch)
        action = "Created"

    print(f"{action} {args.type} patch with port(s): {args.main_key}", end="")
    if args.second:
        print(f" + {args.second[0]}", end="")
    print()

    # Output / save
    if args.dry_run:
        print("\nWould write the following to", file_path)
        print("-" * 50)
        yaml.dump(data, sys.stdout)
        print("-" * 50)
    else:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f)
            print(f"Successfully written to: {file_path}")
        except Exception as e:
            print(f"Error writing file: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
