import os

def process_files():
    index = 1
    while True:
        filename = f"index{index}.md"
        filename_new = f"index{index}-n.md"
        if not os.path.exists(filename):
            break  # stop if file doesn't exist
        
        output_lines = []
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("You: "):
                    break  # stop processing further lines
                output_lines.append(line)
        
        with open(filename_new, "w", encoding="utf-8") as f:
            f.writelines(output_lines)
        
        print(f"Processed {filename}")
        index += 1

if __name__ == "__main__":
    process_files()

