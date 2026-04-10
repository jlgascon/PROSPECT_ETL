import pandas as pd 
import hashlib
import os
import glob
# import re
import argparse
import dtale
import time
import warnings

# suppress openpyxl data validation extension warnings
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Define the global homogonization dict
# Variants of headers to be cleaned before creating prospect_UUID hash

header_map = {
    'Email':'Core_Email',
    'Email ':'Core_Email',
    'Email Address':'Core_Email',
    'Email Address:':'Core_Email',
    'E-mail Address:':'Core_Email',
    'E-mail Address':'Core_Email',
    'First Name':'Core_First_Name',
    'First name':'Core_First_Name',
    'First Name:':'Core_First_Name',
    'First/Given Name':'Core_First_Name',
    'FirstName':'Core_First_Name',
    'Last Name':'Core_Last_Name',
    'Last name':'Core_Last_Name',
    'Last Name:':'Core_Last_Name',
    'Last/Family Name':'Core_Last_Name',
    'LastName':'Core_Last_Name',
    'Parent Email':'Core_Parent_Email',
    'Parent First Name':'Core_Parent_First_Name',
    'Parent Last Name':'Core_Parent_Last_Name',
}

# Generate the interaction and entity hashes

def generate_entity_uuid(row, email_col, fname_col, lname_col):

    #extract, cast to str, lowercase, and strip whitespace
    #email = str(row.get('core_email', '')).lower().strip()
    #f_name = str(row.get('first_name', '')).lower().strip()
    #l_name = str(row.get('last_name', '')).lower().strip()
    
    #refactored to get entity rather than just student stuff (parent emails etc)

    email = str(row.get(email_col, '')).lower().strip()
    f_name = str(row.get(fname_col, '')).lower().strip()
    l_name = str(row.get(lname_col, '')).lower().strip()


    #some aggrod regex to prevent hash collision from typos (trailing punctuation etc)
    #email = re.sub(r'[^a-zA-Z0-9@.+_-]','', email)
    allowed_chars = set('abcdefghijklmnopqrstuvwxyz0123456789@.+_-') # regex was finding \x incomplete escapes and broke down
    email = ''.join(c for c in email if c in allowed_chars)

    #core str concatenation
    #prioritizing email, then falling back to first + last name if email is missing

    if email and email != 'nan':
        raw_string = email
    elif f_name != 'nan' and l_name != 'nan' and f_name and l_name:
        raw_string = f'{f_name}{l_name}'
    else:
        #admin ghost, no usable entity data
        return None
    
    return hashlib.sha256(raw_string.encode('utf-8')).hexdigest()

def robust_ingest(file_path):
    """
    Handles encoding cascades, excel multi sheet extraction, header preamble sniffing, and structural cleaning
    prior to returning a cleaned dataframe for EAV processing and the raw expected row counts.
    """
    ext = os.path.splitext(file_path)[1].lower()
    df = pd.DataFrame()
    raw_expected_rows = 0

    # --- 1. EXCEL EXTRACTION (.xlsx, .xls) ---

    if ext in ['.xlsx','.xls']:
        try:
            #sheet_name = None reads all sheets; header = None allows manual preamble sniffing
            xls_dict = pd.read_excel(file_path, sheet_name=None, header=None)
            combined_sheets = []

            for sheet_name, sheet_df in xls_dict.items():
                sheet_df.dropna(how='all', inplace=True) #drop entirely empty formatting rows
                sheet_df.reset_index(drop=True, inplace=True)

                if sheet_df.empty: continue

                valid_counts = sheet_df.notna().sum(axis=1)
                header_idx = int(valid_counts.idxmax()) if not valid_counts.empty else 0

                #tally up the expected rows (total lines - header index - 1 for the header itself)
                raw_expected_rows += max(0, len(sheet_df) - header_idx -1)

                sheet_df.columns = sheet_df.iloc[header_idx]
                sheet_df = sheet_df.iloc[header_idx+1:].copy()
                sheet_df['Source_Sheet'] = sheet_name #tracks sub sheets from the workbook
                combined_sheets.append(sheet_df)

            if combined_sheets:
                df = pd.concat(combined_sheets, ignore_index=True)

        except Exception as e:
            print(f'    [!] Excel read failed for {os.path.basename(file_path)}: {e}')
            return pd.DataFrame(), 0
        

    # --- 2. CSV EXTRACTION (.csv) ---
    elif ext == '.csv':
        try:
            #get the true OS level line count to catch ragged lines pd might ghost drop
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                total_lines = sum(1 for line in f if line.strip())

        except:
            total_lines = 0

  
        encodings = ['utf-8', 'latin1', 'cp1252', 'utf-8-sig']
        sample_df, successful_enc = None, None
   
        # Encoding Cascade & Header Sniffing
        for enc in encodings:
            try:
                # Read top 30 rows raw to find the structural start
                sample_df = pd.read_csv(file_path, nrows=30, header=None, low_memory=False, on_bad_lines='skip', encoding=enc)
                successful_enc = enc
                break
            except UnicodeDecodeError:
                continue
           
        if sample_df is None or sample_df.empty:
            print(f"[!] {os.path.basename(file_path)} is empty or completely unreadable.")
            return pd.DataFrame(), 0

        # Locate the header: The row with the maximum number of populated columns
        valid_counts = sample_df.notna().sum(axis=1)
        header_idx = int(valid_counts.idxmax())

        raw_expected_rows = max(0, total_lines - header_idx - 1)
    
        if header_idx > 0:
            print(f" -> {os.path.basename(file_path)}: Preamble detected. Shifting header to row {header_idx}.")

        # Structural Extraction
        try:
            df = pd.read_csv(file_path, header=header_idx, low_memory=False, on_bad_lines='skip', encoding=successful_enc)
        except UnicodeDecodeError:
                
            #If the special character was hiding past row 30, fallback to Windows encoding for the full read
            print(f"    [*] {os.path.basename(file_path)}: UTF-8 passed preamble but failed full read. Falling back to cp1252.")

            try:
                df = pd.read_csv(file_path, header=header_idx, low_memory=False, on_bad_lines='skip', encoding='cp1252')
            except Exception as e_fallback:
                print(f"[!] {os.path.basename(file_path)} failed fallback read: {e_fallback}")
                return pd.DataFrame(), raw_expected_rows
        except Exception as e:
            print(f"[!] {os.path.basename(file_path)} failed full read on {successful_enc}: {e}")
            return pd.DataFrame(), raw_expected_rows

    # --- 3. SHARED STRUCTURAL CLEANUPS ---
    if not df.empty:
        #convert whitespace to NaN
        #df.replace(r'^\x*$', pd.NA, regex=True, inplace=True) #removed cause of regex \x fatal error 

        # Regex free - map pure whitespace cells to pd.Na using an apply lambda 
        # which bypasses the regex engine, corrupted '\x' bytes are treated as text and ignored 

        for col in df.columns:
            if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
                df[col] = df[col].apply(lambda x: pd.NA if isinstance(x, str) and not x.strip() else x)

        #excel relies heavily on this to purge the phantom formatting columns
        df.dropna(axis=1, how='all', inplace=True)
        #drop completely empty rows
        df.dropna(how='all', inplace=True)

        # Clean up trailing comma phantom columns
        clean_headers = [col for col in df.columns if pd.notna(col) and not str(col).startswith('Unnamed:')]
        df = df[clean_headers]
    
    return df, raw_expected_rows

# BATCH PROCESSOR PIPELINE, TABLE BUILDS, EDGE BUILDS

def build_eav_pipeline(directory_path):

    #GLOB which grabs csv, xlsx, and xls

    all_files = []
    for ext in ('*.csv','*.xlsx','*.xls'):
        all_files.extend(glob.glob(os.path.join(directory_path, "**", ext), recursive=True))

    master_eav_frames = []
    master_edges = [] # We now need a ledger for our graph edges
    master_audit = [] # Audit ledger
    
    print(f'[*] Commencing pipeline execution on {len(all_files)} files...')

    for file_path in all_files:
        
        file_name = os.path.basename(file_path)
        print(f'\n[>] Ingesting: {file_name}')

        try:
            # extract data and get raw expected row counts
            df, raw_expected = robust_ingest(file_path)
            pandas_parsed_rows = len(df) 

            if df.empty:
                print(f'    [!] File is empty or failed ingestion. Skipping.')
                master_audit.append({'Source_File': file_name, '1_Raw_Expected': raw_expected, '2_Pandas_Parsed':0, '3_Entities_Retained':0})
                continue
            
            # Prevent spreadsheets from turning filenames starting with operation chars into #NAME? errors
            df['Source_File'] = f"'{file_name}" if file_name.startswith(('-', '=', '+', '@')) else file_name

            #initial_rows = len(df)
           
            # A. Taxonomic Homogenization
            df.columns = df.columns.astype(str).str.strip()
            df = df.rename(columns=header_map)
            df = df.groupby(df.columns, axis=1).first()
           
            # B. Entity Resolution (Dual-Core Generation)
            df['Student_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Email', 'Core_First_Name', 'Core_Last_Name'), axis=1)
               
            df['Parent_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Parent_Email', 'Core_Parent_First_Name', 'Core_Parent_Last_Name'), axis=1)
            

            # --- THE AUDIT --- (Calculated before the melt multiplies the rows)

            # Purge absolute ghosts (rows where BOTH entities failed to generate)
            df = df.dropna(subset=['Student_UUID', 'Parent_UUID'], how='all')
            retained_rows = len(df)

            master_audit.append({
                'Source_File': file_name,
                '1_Raw_Expected': raw_expected,
                '2_Pandas_Parsed': pandas_parsed_rows,
                '3_Entities_Retained': retained_rows, 
                'Parse_Variance': max(0, raw_expected - pandas_parsed_rows),
                'Ghosts_dropped': max(0, pandas_parsed_rows - retained_rows)
            })

            if df.empty:
                print(f'   [-] Zero valid entities resolved. Skipping melt.')
                continue
            
            print(f'  [+] Resolved entities: Retained {retained_rows}/{pandas_parsed_rows} parsed rows.')


            # 3. Extract the Relational Edges (The Graph Foundation)
            # Find the rows where we successfully generated BOTH a student and a parent
            mask_both = df['Student_UUID'].notna() & df['Parent_UUID'].notna()
            if mask_both.any():
                file_edges = df.loc[mask_both, ['Student_UUID', 'Parent_UUID', 'Source_File']].copy()
                file_edges['Relationship'] = 'HAS_PARENT'
                master_edges.append(file_edges)
                print(f'   [+] Extracted {len(file_edges)} HAS_PARENT edges')
               
           # 4. Attribute Triage (Who owns what?)
            all_columns = df.columns.tolist()
            core_system_cols = ['Student_UUID', 'Parent_UUID', 'Source_File', 'Source_Sheet']
            core_data_cols = [c for c in all_columns if c.startswith('Core_')]
           
            # --- THE HYBRID EAV FIX: Splitting the Core Data ---
            # We route the un-meltable identity columns to the correct entity
            parent_core_cols = [c for c in core_data_cols if 'parent' in c.lower() or 'guardian' in c.lower()]
            student_core_cols = [c for c in core_data_cols if c not in parent_core_cols]

            # Check if this file is explicitly a Parent-only extraction type
            #is_parent_file = 'parent' in file_name.lower()

            # If the file generated Parent UUIDs but zero Student UUIDs, it's a parent file.
            is_parent_file = ('parent' in file_name.lower()) or (df['Student_UUID'].isna().all() and not df['Parent_UUID'].isna().all())
           
            if is_parent_file:
                #if it is a parent file, ALL non-core attributes belong to the parent
                parent_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols]
                student_value_vars = []

            else: 
                # Standard heuristic routing for the variable data (The columns that WILL melt)
                parent_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols and ('parent' in c.lower() or 'guardian' in c.lower())]
                student_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols and c not in parent_value_vars]
           
            # 5A. Melt the Student Attributes (Fat EAV)
            student_df = df.dropna(subset=['Student_UUID'])
            if not student_df.empty and student_value_vars:
                # Lock the student_core_cols into the bedrock alongside the UUID and dynamically include Source_Sheet if it exists
                student_id_vars = [c for c in ['Student_UUID', 'Source_File', 'Source_Sheet'] + student_core_cols if c in student_df.columns]
               
                student_eav = pd.melt(
                    student_df,
                    id_vars=student_id_vars,
                    value_vars=student_value_vars,
                    var_name='Attribute',
                    value_name='Value'
                )
                student_eav = student_eav.rename(columns={'Student_UUID': 'Entity_UUID'})
                student_eav['Entity_Type'] = 'Student'
                master_eav_frames.append(student_eav)
               
            # 5B. Melt the Parent Attributes (Fat EAV)
            parent_df = df.dropna(subset=['Parent_UUID'])
            if not parent_df.empty and parent_value_vars:
                # Lock the parent_core_cols into the bedrock alongside the UUID
                parent_id_vars = [c for c in ['Parent_UUID', 'Source_File', 'Source_Sheet'] + parent_core_cols if c in parent_df.columns]
               
                parent_eav = pd.melt(
                    parent_df,
                    id_vars=parent_id_vars,
                    value_vars=parent_value_vars,
                    var_name='Attribute',
                    value_name='Value'
                )
                parent_eav = parent_eav.rename(columns={'Parent_UUID': 'Entity_UUID'})
                parent_eav['Entity_Type'] = 'Parent'
                master_eav_frames.append(parent_eav)
               
        except Exception as e:
            # Note: I cleaned up this print statement. file_name is already defined earlier in your loop.
            print(f"    [!] FATAL ERROR processing {file_name}: {e}")
           
    # 6. Final Concatenation and Null Purge
    final_eav = pd.concat(master_eav_frames, ignore_index=True) if master_eav_frames else pd.DataFrame()
    final_edges = pd.concat(master_edges, ignore_index=True) if master_edges else pd.DataFrame()
    final_audit = pd.DataFrame(master_audit) # create the ledger df
   
    if not final_eav.empty:
        # Purge the void and standardize
        final_eav = final_eav.dropna(subset=['Value'])
        final_eav = final_eav[~final_eav['Value'].astype(str).str.strip().isin(['', 'nan', 'NaN', 'None'])]
        final_eav['Attribute'] = final_eav['Attribute'].astype(str).str.strip().str.lower().str.replace(' ', '_')
       
    return final_eav, final_edges, final_audit

if __name__ == '__main__':
    #1 configure the cli parser
    parser = argparse.ArgumentParser(description="Ingest, homogoenize, and pivot prospect CSV schemas into an EAV database")
    parser.add_argument(
        '-d', '--dir',
        type=str,
        required=True,
        help='Target directory path containing the raw files'

    )

    args = parser.parse_args()

    # trigger the pipeline 
    #target_directory = args.dir

    if not os.path.isdir(args.dir):
        print(f'[!] FATAL: Directory {args.dir} does not exist.')
        exit(1)

    #pipeline returns the 3 variables
    master_eav, master_edges, master_audit = build_eav_pipeline(args.dir)

    #Save the audit for records
    if not master_audit.empty:
        audit_path = 'extraction_audit_ledger.csv'
        master_audit.to_csv(audit_path, index=False)
        print(f'\n[+] Audit Ledger saved permanently to: {audit_path}')

    # DTale visualization & Server suspension

    if not master_eav.empty or not master_edges.empty:
        print(f'\n[*] Initializing DTale diagnostic servers...')

        # load the EAV df (data instance 1)
        if not master_eav.empty:

            #getting a more definitive instantiation: space instead of underscore in name attr, forced IPv4, static port

            dtale.show(master_eav, name='EAV Ledger', host='localhost', port=8000)

        # load the Audit df (data instance 2)
        if not master_audit.empty:

            dtale.show(master_audit, name='Audit Ledger', host='localhost', port=8000)

        print(f'   [>] EAV Table loaded at: http:127.0.0.1:8000')
        print(f'[+] Click the top left menu in Dtale and select instances to swap between EAV and Audit Ledgers')
        print(f'\n[*] Server is live, script execution suspended')
        print(f'[*] Press CTRL + C to kill server and exit')

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f'\n[*] Keyboard interrupt detected. Terminating server')
            exit(0)
