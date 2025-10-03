import os

root_dir = os.getcwd()  # change this to your folder path

for subdir, dirs, files in os.walk(root_dir):
    print(".")
    if len(files) == 1:
        old_file = os.path.join(subdir, files[0])
        new_file = os.path.join(subdir, "index.md")
        if files[0] != "index.md":
            print(f"Renaming {old_file} -> {new_file}")
            os.rename(old_file, new_file)
    else:
        print(f"Skipping {subdir} - contains {len(files)} files")
