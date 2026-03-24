import pandas as pd
from pathlib import Path
import os

def profile_crm_dump(target_directory: str, output_dir: str = '.'):
    '''crawls a directory for csvs and extracts file level header lists and granular column level metadata'''
    target_path = Path(target_directory)

    if not target_path.exists() or not target_path.is_dir():
        print(f'[FATAL] Directory not found: {target_directory}')
        return
    
    print(f'[*] Initatiating metadata extraction in: {target_path.resolve()}')

    file_inventory = []
    column_schema = []

    #recursively hunt down the csvs files in target folder and sub directories

    csv_files = list(target_path.rglob('*.csv'))

    print(f'[*] Found {len(csv_files)} CSV files. Commencing evals')

    for file_path in csv_files:
        file_name = file_path.name
        rel_path = file_path.relative_to(target_path)

        print(f' -> Profiling: {file_name}')

        try:
           
            #Phase 1 header sniffing 
            try:
                #read top 20 rows raw without header assumptions
                sample_df = pd.read_csv(file_path, nrows=20, header=None, low_memory=False, on_bad_lines='skip', encoding='utf-8')
            
            #crm exports often have encoding dissonance; fallback to utf-8 to latin1 if necessary
            except UnicodeDecodeError:
                sample_df = pd.read_csv(file_path, nrows=20, header=None, low_memory=False, on_bad_lines='skip', encoding='latin1')
            
            if sample_df.empty:
                print(f' [!] File is empty. Skipping.')
                continue
            
            valid_counts = sample_df.notna().sum(axis=1)
            header_idx = int(valid_counts.idxmax())

            if header_idx > 0: 
                print(f'Preamble detected. Shifting header to row {header_idx}.')


            #Phase 2 structural extractions 

            try:
                df = pd.read_csv(file_path, header=header_idx, low_memory=False, on_bad_lines='skip')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, header=header_idx, low_memory=False, on_bad_lines='skip', encoding='latin1')

            total_rows = len(df)
            headers = list(df.columns)

            #Clean up default pd unnamed columns that might still sneak in from trailing commas
            clean_headers = [str(col) for col in headers if not str(col).startswith('Unnamed:')]

            #1 Append to file level inventory
            file_inventory.append({
                'file_name': file_name,
                'relative_path': str(rel_path),
                'row_count' : total_rows,
                'column_count': len(clean_headers),
                'declared_headers': " | ".join(clean_headers) #delim string for easy scanning
            })

            #2 Append to column level schema map

            for col in headers:

                if str(col).startswith('Unnamed:'):
                    continue #ignored the phantom columns in the detailed map 

                null_count = df[col].isna().sum()
                null_percentage = round((null_count / total_rows) * 100, 2) if total_rows > 0 else 100
                cardinality = df[col].nunique()
                inferred_type = str(df[col].dtype)  #sniff out the most dominant data type in the colum

                column_schema.append({
                    'source_file': file_name,
                    'column_name': col,
                    'inferred_type': inferred_type,
                    'total_rows': total_rows,
                    'null_count': null_count,
                    'null_percentage' : null_percentage, 
                    'cardinality' : cardinality
                })

        except Exception as e:
            print(f'[ERROR] Failed to process {file_name}: {str(e)}')

    #construct dataframes and export
    df_inventory = pd.DataFrame(file_inventory)
    df_schema = pd.DataFrame(column_schema)

    inventory_out = Path(output_dir) / '01_file_inventory.csv'
    schema_out = Path(output_dir) / '02_column_schema_map.csv'

    df_inventory.to_csv(inventory_out, index=False)
    df_schema.to_csv(schema_out, index=False)

    print('\n[*] Extraction Complete')
    print(f' -> File inventory saved to: {inventory_out}')
    print(f' -> Schema map saved to {schema_out}')

#Excecutioon block
if __name__ == '__main__':
    #target folder
    TARGET_FOLDER = r'data\raw\extracted\2025_2026'

    profile_crm_dump(TARGET_FOLDER)