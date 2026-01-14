#!/usr/bin/env python3
"""
Update kustomization.yaml port patches (TCP or NodePort) with ruamel.yaml

Usage examples:
  python script.py tcp 311337 dremio-4 dremio-client 31010 --file v1.yaml
  python script.py tcp 311338 prod-ns app-svc 31010 --second 349338 32010 --dry-run
  python script.py nodeport 30085 8080 --file v1.yaml
"""

import sys
from pathlib import Path
from typing import Dict

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 8192
yaml.preserve_quotes = True


# ── Configuration ───────────────────────────────────────────────────────────────

PATCH_CONFIG = {
    "tcp": {
        "path": "/spec/values/tcp",
        "name": "TCP host port → namespace/service:containerPort",
        "merge": "update_append",
        "value_template": "{ns}/{svc}:{cp}"
    },
    "nodeport": {
        "path": "/spec/values/controller/service/nodePorts/tcp",
        "name": "NodePort → containerPort",
        "merge": "exclusive",
        "value_template": "{cp}"
    }
}


def find_patch_index(patches: list, target_path: str) -> int:
    for i, item in enumerate(patches):
        if isinstance(item, dict) and 'patch' in item:
            content = str(item['patch'])
            if f'path: {target_path}' in content and '- op: add' in content:
                return i
    return -1


def parse_mappings(patch_content: str) -> Dict[str, str]:
    """Robust extraction of port mappings from patch"""
    mappings = {}
    lines = patch_content.splitlines()
    in_value = False

    for line in lines:
        s = line.rstrip()
        if 'value: |' in s:
            in_value = True
            continue

        if in_value and ':' in s:
            # Try to get content after indentation
            content = s.lstrip()
            if content and content[0].isdigit():
                try:
                    key, value = [x.strip() for x in content.split(':', 1)]
                    if key.isdigit():
                        mappings[key] = value
                except:
                    pass
    return mappings


def build_patch_content(path: str, mappings: Dict[str, str]) -> LiteralScalarString:
    lines = [
        "- op: add",
        f"  path: {path}",
        "  value: |"
    ]
    for port in sorted(mappings, key=int):
        lines.append(f"    {port}: {mappings[port]}")
    if not mappings:
        lines.append("    {}")
    return LiteralScalarString("\n".join(lines))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add/update port patches in kustomization.yaml",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("--file", default="kustomization.yaml",
                        help="Path to kustomization.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show result without writing file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # TCP subcommand
    tcp = subparsers.add_parser("tcp", help="Update TCP host port mappings")
    tcp.add_argument("host_port", type=int, help="Host port (e.g. 33100, 311337)")
    tcp.add_argument("namespace", help="Namespace (e.g. dremio-prod-3)")
    tcp.add_argument("service", help="Service name (e.g. dremio-client)")
    tcp.add_argument("container_port", type=int, help="Container port (e.g. 31010)")
    tcp.add_argument("--second", nargs=2, type=int, metavar=("HOST", "CONTAINER"),
                     help="Optional second pair: host_port container_port")

    # NodePort subcommand
    np = subparsers.add_parser("nodeport", help="Update NodePort mappings")
    np.add_argument("node_port", type=int, help="Node port (e.g. 30085)")
    np.add_argument("container_port", type=int, help="Container port (e.g. 8080)")
    np.add_argument("--second", nargs=2, type=int, metavar=("NODE", "CONTAINER"),
                    help="Optional second pair: node_port container_port")

    args = parser.parse_args()

    cfg = PATCH_CONFIG[args.command]

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    data = yaml.load(file_path) or {}

    # Prepare new mapping(s)
    new_mappings = {}

    if args.command == "tcp":
        main_value = cfg["value_template"].format(
            ns=args.namespace, svc=args.service, cp=args.container_port)
        new_mappings[str(args.host_port)] = main_value

        if args.second:
            s_host, s_container = args.second
            new_mappings[str(s_host)] = cfg["value_template"].format(
                ns=args.namespace, svc=args.service, cp=s_container)
    else:  # nodeport
        new_mappings[str(args.node_port)] = str(args.container_port)
        if args.second:
            s_node, s_container = args.second
            new_mappings[str(s_node)] = str(s_container)

    # Find existing patch
    patches = data.setdefault('patches', [])
    idx = find_patch_index(patches, cfg["path"])

    current = {}
    if idx >= 0:
        current = parse_mappings(str(patches[idx]['patch']))

    # Merge strategy
    if cfg["merge"] == "exclusive":
        overlap = set(new_mappings.keys()) & set(current.keys())
        if overlap:
            print("Error: The following ports already exist:", file=sys.stderr)
            for p in sorted(overlap):
                print(f"  {p} → {current[p]}", file=sys.stderr)
            return 2

    current.update(new_mappings)

    # Build new patch
    new_content = build_patch_content(cfg["path"], current)
    new_patch = {'patch': new_content}

    if idx >= 0:
        patches[idx] = new_patch
        action = "Updated (merged)"
    else:
        patches.append(new_patch)
        action = "Created"

    print(f"{action} {cfg['name']}")
    print(f"  Added/updated: {args.host_port if args.command == 'tcp' else args.node_port}", end="")
    if args.second:
        print(f" + {args.second[0]}", end="")
    print()

    if args.dry_run:
        print("\nDry run result:")
        print("─" * 70)
        yaml.dump(data, sys.stdout)
        print("─" * 70)
    else:
        yaml.dump(data, file_path)
        print(f"File updated: {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
