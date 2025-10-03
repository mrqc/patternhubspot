def split_file(input_file):
    file_index = 1
    output_file = None

    with open(input_file, "r", encoding="utf-8") as infile:
        for line in infile:
            # if line starts with "# " -> close current file and start a new one
            if line.startswith("# "):
                if output_file:
                    output_file.close()
                output_filename = f"index{file_index}.md"
                output_file = open(output_filename, "w", encoding="utf-8")
                file_index += 1

            if output_file:
                output_file.write(line)

    if output_file:
        output_file.close()


if __name__ == "__main__":
    split_file("full.txt")

