import pandas as pd
from pathlib import Path

#HARDCODES NOT WANTED --> 
def compress_schema_map(input_csv: str = '02_column_schema_map_03.csv', output_csv: str='03_global_dictionary_raw.csv'):
    '''Collapses the file-level schema map into a distinct column vocab'''

    if not Path(input_csv).exists():
        print(f'[ERROR] Could not find {input_csv}.')
        return
    
    print(f'[*] Reading {input_csv}...')
    df = pd.read_csv(input_csv)

    #group by the exact string of the raw column name
    compressed = df.groupby('column_name').agg(
        appearance_count=('source_file', 'count'),
        files_found_in=('source_file', lambda x: ' | '.join(x.unique())),
        avg_null_percentage=('null_percentage', 'mean'),
        dominant_type=('inferred_type', lambda x: x.mode()[0] if not x.mode().empty else 'UNKNOWN')
    ).reset_index()

    #sort by requency (most common col first) then by lowest null percentages
    compressed = compressed.sort_values(by=['appearance_count', 'avg_null_percentage'], ascending=[False, True])

    #append the blank target columns for human entry
    compressed['target_column_name'] = ''
    compressed['target_data_type'] = ''
    compressed['action_flag'] = 'KEEP' #default assumption, user changeable

    compressed.to_csv(output_csv, index=False)

    original_rows = len(df)
    new_rows = len(compressed)
    compression_ratio = round((1 - (new_rows/original_rows)) * 100, 2)

    print(f'[*] Consolidation Complete.')
    print(f' -> Original Rows: {original_rows}')
    print(f' -> Unique Columns: {new_rows} ({compression_ratio}% reduction)')
    print(f' -> Exported to: {output_csv}')

    #if __name__ == '__main__':
    #    compress_schema_map()

compress_schema_map()