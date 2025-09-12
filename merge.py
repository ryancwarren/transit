from jsonmerge import merge
from functools import reduce
import json

def merge_dict_list(dict_list, sort_keys=False):
    """Merge a list of dictionaries using jsonmerge.merge, optionally sorting keys."""
    if not dict_list:
        return {}
    if not all(isinstance(d, dict) for d in dict_list):
        raise ValueError("All elements in the list must be dictionaries")

    # Use reduce to iteratively merge dictionaries
    def merge_reduce(acc, curr):
        return merge(acc, curr)

    merged = reduce(merge_reduce, dict_list)

    # Optionally sort keys recursively
    if sort_keys:
        def sort_dict(obj):
            if isinstance(obj, dict):
                return {k: sort_dict(v) for k, v in sorted(obj.items())}
            elif isinstance(obj, list):
                return [sort_dict(item) for item in obj]
            else:
                return obj
        merged = sort_dict(merged)

    return merged

def merge_json_files(file_paths, output_file=None, sort_keys=False):
    """Merge JSON files containing dictionaries into one, using jsonmerge.merge."""
    dict_list = []
    # Load JSON files into a list of dictionaries
    for file_path in file_paths:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError(f"File {file_path} does not contain a JSON object")
                dict_list.append(data)
        except FileNotFoundError:
            print(f"Error: File not found - {file_path}")
            return None
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in {file_path}")
            return None

    # Merge the dictionaries
    merged = merge_dict_list(dict_list, sort_keys=sort_keys)

    # Output or save result
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(merged, f, indent=2)
        print(f"Merged JSON saved to {output_file}")
    else:
        print(json.dumps(merged, indent=2))

    return merged

# Example usage
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python merge_json.py file1.json file2.json [output.json]")
        sys.exit(1)
    
    file_paths = sys.argv[1:-1] if len(sys.argv) > 3 else sys.argv[1:]
    output = sys.argv[-1] if len(sys.argv) > 3 else None
    merge_json_files(file_paths, output_file=output, sort_keys=True)
