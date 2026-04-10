import pandas as pd
import openpyxl

def build_audit_ledger(file_list, df_extracted, get_preamble_count):
    audit_log = []

    for filepath in file_list:
        raw_data_rows = 0

        try: 
            if filepath.endswith('csv'):
                #bypass pandaas to the the true OS-level line count

                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    
                    #count non-empty lines
                    total_lines = sum(1 for line in f if line.strip())
                    preamble_count = get_preamble_count(filepath)

                    #total lines - preamble lines - header line
                    raw_data_rows = total_lines - preamble_count - 1

            elif filepath.endswith(('.xlsx', '.xls')):
                #excel requires checkign all sheets

                wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
                for sheetname in wb.sheetnames:
                    ws = wb[sheetname]

                    preamble_count = get_preamble_count(filepath)
                    if ws.max_row > preamble_count:
                        raw_data_rows += (ws.max_row - preamble_count - 1)
                    
        except Exception as e: 
            print(f'Error reading {filepath}: {e}')

        #Count distinct interactions in the EAV table for this file
        #Assumes your df has 'source_file_path' and 'interaction_hash' columns
        # Using Entity_UUID as interaction hash for now 
        extracted_rows = df_extracted[df_extracted['source_file_path'] == filepath]['interaction_hash'].nunique()

        audit_log.append({
            'Source_File': filepath,
            'Raw_Expected': max(0, raw_data_rows),
            'Extracted_Actual': extracted_rows,
            'Variance': max(0, raw_data_rows) - extracted_rows

        })     

    return pd.DataFrame(audit_log)