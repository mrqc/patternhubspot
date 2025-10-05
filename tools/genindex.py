import os
import json

def folder_structure(path):
    structure = {"name": os.path.basename(path), "children": []}
    try:
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                structure["children"].append(folder_structure(full_path))
    except PermissionError:
        pass  # skip folders that can't be accessed
    return structure

if __name__ == "__main__":
    root_dir = "."  # change this if you want to start elsewhere
    structure = folder_structure(os.path.abspath(root_dir))
    with open("structure.json", "w", encoding="utf-8") as f:
        json.dump(structure, f, indent=2, ensure_ascii=False)
