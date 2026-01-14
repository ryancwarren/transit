#!/usr/bin/env python3
"""
Script to add/update TCP port mappings in kustomization.yaml using ruamel.yaml
for clean literal block style output.
"""

import sys
import argparse
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096
yaml.preserve_quotes = True


def parse_existing_tcp_patch(patch_content: str) -> dict:
    """Extract current port:target mappings from existing patch text"""
    current = {}
    lines = patch_content.splitlines()
    in_value = False

    for line in lines:
        stripped = line.rstrip()
        if stripped.strip() == 'value: |':
            in_value = True
            continue
        if in_value and ':' in stripped and stripped.lstrip().startswith(('0','1','2','3','4','5','6','7','8','9')):
            try:
                indent, rest = line.split(':', 1)
                port = rest.split(':', 1)[0].strip() if ':' in rest else ""
                target = rest.split(':', 1)[1].strip() if ':' in rest else rest.strip()
                if port.isdigit():
                    current[port] = target
            except:
                pass
    return current


def build_tcp_patch_text(mappings: dict) -> str:
    """Create clean patch text with literal block"""
    lines = [
        "- op: add",
        "  path: /spec/values/tcp",
        "  value: |"
    ]

    for port in sorted(mappings.keys(), key=int):
        lines.append(f"    {port}: {mappings[port]}")

    if not mappings:
        lines.append("    {}")

    return "\n".join(lines)


def update_tcp_patch(
    data: dict,
    host_port: int,
    namespace: str,
    service: str,
    container_port: int,
    second_pair: tuple | None = None
) -> dict:
    target = f"{namespace}/{service}:{container_port}"

    # Find existing tcp patch
    patch_index = -1
    existing_patch = None

    patches = data.get('patches', [])
    for i, item in enumerate(patches):
        if isinstance(item, dict) and 'patch' in item:
            content = str(item['patch']).strip()
            if 'path: /spec/values/tcp' in content and '- op: add' in content:
                patch_index = i
                existing_patch = item
                break

    # Get current mappings
    current_mappings = {}
    if existing_patch:
        current_mappings = parse_existing_tcp_patch(str(existing_patch['patch']))

    # Add new mapping(s)
    new_mappings = {str(host_port): target}

    if second_pair:
        h2, c2 = second_pair
        t2 = f"{namespace}/{service}:{c2}"
        new_mappings[str(h2)] = t2

    # Merge (new values override if conflict)
    current_mappings.update(new_mappings)

    # Build new patch content
    patch_text = build_tcp_patch_text(current_mappings)

    new_patch_entry = {
        'patch': LiteralScalarString(patch_text)
    }

    if patch_index >= 0:
        # Update existing
        data['patches'][patch_index] = new_patch_entry
        print(f"Updated existing TCP patch → added/updated {host_port}")
        if second_pair:
            print(f"                           + {second_pair[0]}")
    else:
        # Add new patch
        if 'patches' not in data:
            data['patches'] = []
        data['patches'].append(new_patch_entry)
        print(f"Created new TCP patch → added {host_port}")
        if second_pair:
            print(f"                    + {second_pair[0]}")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Add/update TCP port mapping(s) in kustomization.yaml (clean literal style)"
    )
    parser.add_argument("host_port", type=int, help="First host port (e.g. 33107)")
    parser.add_argument("namespace", help="Namespace (e.g. dremio-prod-3)")
    parser.add_argument("service", help="Service name (e.g. dremio-client)")
    parser.add_argument("container_port", type=int, help="Target container port (e.g. 31010)")

    parser.add_argument("--second-host", type=int, help="Second host port (e.g. 34907)")
    parser.add_argument("--second-container", type=int, help="Second container port (e.g. 32010)")

    parser.add_argument("--file", default="kustomization.yaml", help="Path to file")
    parser.add_argument("--dry-run", action="store_true", help="Only show result")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    # Load with ruamel.yaml
    with open(file_path, encoding='utf-8') as f:
        data = yaml.load(f) or {}

    second = None
    if args.second_host is not None and args.second_container is not None:
        second = (args.second_host, args.second_container)

    updated_data = update_tcp_patch(
        data,
        args.host_port,
        args.namespace,
        args.service,
        args.container_port,
        second
    )

    if args.dry_run:
        print("\n--- DRY RUN - would write to file: ---")
        yaml.dump(updated_data, sys.stdout)
        print("\n--- end of dry run ---")
    else:
        # Write back using ruamel.yaml (preserves style)
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(updated_data, f)
        print(f"File updated: {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
