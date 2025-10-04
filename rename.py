import os

root_dir = os.getcwd()  # change this to your folder path

for subdir, dirs, files in os.walk(root_dir):
    if len(files) == 1:
        old_file = os.path.join(subdir, files[0])
        new_file = os.path.join(subdir, "index.md")
        if ".git" in old_file:
            print(f"{old_file} in .git")
        elif ".idea" in old_file:
            print(f"{old_file} in .idea")
        elif ".png" in old_file:
            print(f"{old_file} is png file")
        elif files[0] != "index.md":
            print(f"Renaming {old_file} -> {new_file}")
            os.rename(old_file, new_file)
    else:
        #print(f"Skipping {subdir} - contains {len(files)} files")
        pass
