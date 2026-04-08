import glob
import os
from collections import defaultdict
import pandas as pd

def list_all_file_types(root_dir):
    """
    Traverses subdirectories to map every file to its extension.
    """
    categorized_files = defaultdict(list)
   
    # The ** pattern with recursive=True handles the subdirectory traversal.
    # iglob returns an iterator for better performance on large filesystems.
    search_path = os.path.join(root_dir, '**', '*')
   
    for entry in glob.iglob(search_path, recursive=True):
        if os.path.isfile(entry):
            # Extracting the extension and normalizing to lowercase.
            # Files without extensions are grouped separately.
            ext = os.path.splitext(entry)[1].lower() or 'no_extension'
            categorized_files[ext].append(entry)
           
    return categorized_files

def display_results(data):
    """
    Outputs the categorized list to the console.
    """
    if not data:
        print("No files identified.")
        return

    for ext, files in sorted(data.items()):
        print(f"\n[TYPE: {ext.upper()}] - {len(files)} file(s) found")
        print("-" * 40)
        for f_path in sorted(files):
            print(f"  {f_path}")

def sanitize_filename(name):

    #removes problematic naming errors in excel
    trigger_chars = ('=','-','+','@')
    if name.startswith(trigger_chars):
        return f"'{name}"
    return name


def export_file_inventory(root_dir, output_filename="inventory.csv"):
    """
    Scans a directory recursively and exports file metadata to a document.
    """
    records = []
    # **/* handles recursive depth in the file tree
    pattern = os.path.join(root_dir, '**', '*')
   
    for path in glob.iglob(pattern, recursive=True):
        if os.path.isfile(path):
            
            raw_name = os.path.basename(path)

            clean_name = sanitize_filename(raw_name)
            
            ext = os.path.splitext(path)[1].lower() or 'no_ext'

            records.append({
                'Extension': ext,
                'Filename': clean_name,
                'Path': os.path.abspath(path),
                'Size_MB': round(os.path.getsize(path) / (1024 * 1024), 4)
            })
   
    if not records:
        print("No files found to document.")
        return None

    # Construct the DataFrame
    df = pd.DataFrame(records)
   
    # Logical sorting: Group by extension, then by filename
    df = df.sort_values(by=['Extension', 'Filename'], ascending=[True, True])
   
    # Export logic
    if output_filename.endswith('.csv'):
        df.to_csv(output_filename, index=False)
    elif output_filename.endswith('.xlsx'):
        df.to_excel(output_filename, index=False)
    elif output_filename.endswith('.md'):
        df.to_markdown(output_filename, index=False)
       
    print(f"Documentation complete: {output_filename}")
    return df


if __name__ == "__main__":
    # Target directory defaults to current working directory.
    target = r".\data\raw\extracted\2024_2025\5. Data Collection"
    file_data = list_all_file_types(target)
    #display_results(file_data)
    results_df = export_file_inventory(target, output_filename="file_report_24_25.csv")
