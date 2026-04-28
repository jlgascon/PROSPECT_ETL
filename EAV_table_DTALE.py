import pandas as pd 
import hashlib
import os
import glob
# import re
import argparse
import dtale
import time
import warnings
import uuid

# suppress openpyxl data validation extension warnings
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Define the global homogonization dict
# Variants of headers to be cleaned before creating prospect_UUID hash
# can move to json or xml or something later, dict is fine for now
# adding new polymorphic discriminators just discovered, will double check for overlaps between Discriminator and Parent/Student Core 

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
    'I am':'Role_Discriminator', #no Core_ prefix to allow EAV table to melt without loss
    'I am a':'Role_Discriminator',
    'I am a(n)':'Role_Discriminator',
    'Parent or Student':'Role_Discriminator',
    'Relationship to Student':'Role_Discriminator',
    'Type of Inquiry':'Role_Discriminator'

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

    # handle 'nan' strings and empty values
    email = '' if email == 'nan' else email
    f_name = '' if f_name == 'nan' else f_name
    l_name = '' if l_name == 'nan' else l_name

    #ensure sufficient data to actually identify someone
    if not (email or (f_name and l_name)):
        return None
    
    # use a pipe-delimited compound string to prevent collisions
    # example 'john.doe@gmail.com|john|doe'
    # (Jo+Hndoe vs John+Doe)
    raw_string = f'{email}|{f_name}|{l_name}'

    #some aggrod regex to prevent hash collision from typos (trailing punctuation etc)
    #email = re.sub(r'[^a-zA-Z0-9@.+_-]','', email)
    #allowed_chars = set('abcdefghijklmnopqrstuvwxyz0123456789@.+_-') # regex was finding \x incomplete escapes and broke down
    #email = ''.join(c for c in email if c in allowed_chars)

    #core str concatenation
    #prioritizing email, then falling back to first + last name if email is missing

    #if email and email != 'nan':
    #    raw_string = email
    #elif f_name != 'nan' and l_name != 'nan' and f_name and l_name:
    #    raw_string = f'{f_name}{l_name}'
    #else:
        #admin ghost, no usable entity data
    #    return None
    
    #return hashlib.sha256(raw_string.encode('utf-8')).hexdigest()

    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_string))

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

            # --- INTERACTION HASH GENERATION ---
            #cryptographic footprint of the raw data before moving to taxonomy shifts
            row_strings = df.fillna('').astype(str).agg(''.join, axis=1)
            df['Interaction_Hash'] = [hashlib.sha256(f'{file_name}_{i}_{val}'.encode('utf-8')).hexdigest() for i, val in enumerate(row_strings)]
           
            # --- BASELINE EVENT INJECTION ---
            # ensures purely demographic lists (name, email only) dont dissapear during the melt and we have at least one attr value
            df['raw_unmapped_baseline_interaction'] = True


            # Taxonomic Homogenization & Header Standardization
            df.columns = df.columns.astype(str).str.strip()
            new_columns = []
            
            #df = df.rename(columns=header_map)

            # --- HORIZONTAL COMPLETENESS (UNMAPPED TAGGING) --- 

            for col in df.columns:
                if col in ['Source_File','Source_Sheet', 'Interaction_Hash', 'raw_unmapped_baseline_interaction']:
                    new_columns.append(col)
                elif col in header_map:
                    new_columns.append(header_map[col])
                else:
                    #regex free string cleaning of to be named col
                    clean_col = ''.join(char for char in col.replace(' ', '_').lower() if char.isalnum() or char == '_')
                    if not clean_col.startswith('raw_unmapped_'):
                        new_columns.append(f'raw_unmapped_{clean_col}')
                    else: 
                        new_columns.append(clean_col)

            df.columns = new_columns
            df = df.groupby(df.columns, axis=1).first()

            #-----------------------------------------------
            #---1. HYGEINE LAYER ---
            #--------------------------------------------------
            for col in df.columns:
                if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
                    mask = df[col].notna()
                    df.loc[mask, col] = df.loc[mask, col].astype(str).str.strip() #strip spaces

                    if 'email' in col.lower():
                        df.loc[mask, col] = df.loc[mask, col].str.lower()
                    elif 'name' in col.lower() and 'file' not in col.lower() and 'sheet' not in col.lower():
                        df.loc[mask, col] = df.loc[mask, col].str.title()
            
            #standardize empty strings into pd NA
            df = df.replace({'nan': pd.NA, 'None':pd.NA, '':pd.NA, '<NA>':pd.NA})

            #------------------------------------------------------------------------------------------
            # --- 2. POLYMORPHIC ROUTER (Triple Track | Student --> Parent --> Influencer) ---
            # defaults to student entity type unless finds parent or other disciminators (teachers, agents, etc)

            #check if the filename implies a parent file, or if the discriminator col triggered
            is_parent_file = 'parent' in file_name.lower()
            is_influencer_file = any(word in file_name.lower() for word in ['counsellor', 'teacher', 'agent', 'educator', 'guidance'])
            
            if 'Role_Discriminator' in df.columns or is_parent_file or is_influencer_file:
                #defaults to the column if it exists, otherwise uses filename for clues
                if 'Role_Discriminator' in df.columns:
                    roles = df['Role_Discriminator'].astype(str).str.lower().str.strip()
                elif is_parent_file:
                    roles = pd.Series('parent', index = df.index) #sim column for parent files 
                else:
                    roles = pd.Series('counsellor', index=df.index)

                
                # defined taxonomies (can put into a side loader later)
                parent_terms = ['parent','mother','father','guardian','mom','dad']
                influencer_terms = ['counsellor', 'counselor', 'teacher', 'agent', 'educator', 'guidance', 'principal']

                parent_mask = roles.str.contains('|'.join(parent_terms), na=False)
                influencer_mask = roles.str.contains('|'.join(influencer_terms), na=False)

                # --- DYNAMIC CORE FIELD DISCOVERY --- 
                # THE SWEEP - finds ALL generic demographic columns, looks for CORE_ to grab them all and exclude any columns that already have a specific entity prefix
                generic_core_columns = [c for c in df.columns if str(c).startswith('Core_') and 'parent' not in str(c).lower() and 'influencer' not in str(c).lower()]

                # TRACK 1: ROUTE PARENTS
                if parent_mask.any():
                    for core_col in generic_core_columns:
                        parent_col = core_col.replace('Core_', 'Core_Parent_') #dynamic creation of target col
                        if parent_col not in df.columns: df[parent_col] = pd.NA

                        shift_mask = parent_mask & df[parent_col].isna()

                        df.loc[shift_mask, parent_col] = df.loc[shift_mask, core_col]
                        df.loc[shift_mask, core_col] = pd.NA

                # TRACK 2: ROUTE INFLUENCER
                if influencer_mask.any():
                    for core_col in generic_core_columns:
                        inf_col = core_col.replace('Core_', 'Core_Influencer_') #dynamic creation of target col ie Core_Influencer_Email

                        if inf_col not in df.columns: df[inf_col] = pd.NA

                        shift_mask = influencer_mask & df[inf_col].isna()

                        df.loc[shift_mask, inf_col] = df.loc[shift_mask, core_col]
                        df.loc[shift_mask, core_col] = pd.NA

            #---------------------------------------------------------------------
            # 3. Entity Resolution (Tri-Core Generation)
            #---------------------------------------------------------------------
            df['Student_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Email', 'Core_First_Name', 'Core_Last_Name'), axis=1)
               
            df['Parent_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Parent_Email', 'Core_Parent_First_Name', 'Core_Parent_Last_Name'), axis=1)
            
            if 'Core_Influencer_Email' in df.columns or 'Core_Influencer_First_Name' in df.columns:
                df['Influencer_UUID'] = df.apply(lambda row: generate_entity_uuid(
                    row, 'Core_Influencer_Email', 'Core_Influencer_First_Name', 'Core_Influencer_Last_Name'), axis =1)
            else: 
                df['Influencer_UUID'] = None
            
            # --- LOSSLESS ORPHAN CATCHER (zerodropna) --- 
            #if a row fails to generate any UUID, tag it unresolved and anchor it to its hash
            df['Unresolved_UUID'] = df.apply(lambda row: row['Interaction_Hash'] if pd.isna(row['Student_UUID']) and pd.isna(row['Parent_UUID']) and  pd.isna(row['Influencer_UUID']) else None, axis =1)
            
            count_unresolved = df['Unresolved_UUID'].notna().sum()
            count_unresolved_rows = pandas_parsed_rows - count_unresolved
         
            # Purge absolute ghosts (rows where BOTH entities failed to generate)
            #df = df.dropna(subset=['Student_UUID', 'Parent_UUID'], how='all')
            #retained_rows = len(df)

            #---------------------------------------------------------------------
            # --- THE AUDIT --- (Calculated before the melt multiplies the rows)
            #---------------------------------------------------------------------

            master_audit.append({
                'Source_File': file_name,
                '1_Raw_Expected': raw_expected,
                '2_Pandas_Parsed': pandas_parsed_rows,
                '3_Entities_Retained': count_unresolved_rows,
                '4_Unresolved_Ghosts':count_unresolved, 
                'Parse_Variance': max(0, raw_expected - pandas_parsed_rows)
            })

            if df.empty:
                print(f'   [-] Zero valid entities resolved. Skipping melt.')
                continue
            
            print(f'  [+] Parsed {pandas_parsed_rows} rows: {count_unresolved_rows} Resolved Entities | {count_unresolved} Unresolved Ghosts')
            
            # ==========================================
            # 4. NETWORK EDGE GENERATION
            # ==========================================
            for uuid_col, entity_type in [('Student_UUID', 'Student'), ('Parent_UUID', 'Parent'), ('Influencer_UUID', 'Influencer')]:
                if uuid_col in df.columns:
                    mask = df[uuid_col].notna()
                    if mask.any():
                        edges = df.loc[mask, [uuid_col, 'Source_File', 'Interaction_Hash']].copy()
                        edges.rename(columns={uuid_col: 'Source', 'Source_File': 'Target'}, inplace=True)
                        edges['Relationship'] = 'INTERACTED_WITH'
                        edges['Entity_Type'] = entity_type
                        master_edges.append(edges)

            if 'Student_UUID' in df.columns and 'Parent_UUID' in df.columns:
                mask_parent = df['Student_UUID'].notna() & df['Parent_UUID'].notna()
                if mask_parent.any():
                    sp_edges = df.loc[mask_parent, ['Student_UUID', 'Parent_UUID', 'Interaction_Hash', 'Source_File']].copy()
                    sp_edges.rename(columns={'Student_UUID': 'Source', 'Parent_UUID': 'Target'}, inplace=True)
                    sp_edges['Relationship'] = 'HAS_PARENT'
                    sp_edges['Entity_Type'] = 'Social'
                    master_edges.append(sp_edges)

            if 'Student_UUID' in df.columns and 'Influencer_UUID' in df.columns:
                mask_inf = df['Student_UUID'].notna() & df['Influencer_UUID'].notna()
                if mask_inf.any():
                    si_edges = df.loc[mask_inf, ['Student_UUID', 'Influencer_UUID', 'Interaction_Hash', 'Source_File']].copy()
                    si_edges.rename(columns={'Student_UUID': 'Source', 'Influencer_UUID': 'Target'}, inplace=True)
                    si_edges['Relationship'] = 'COUNSELLED_BY'
                    si_edges['Entity_Type'] = 'Social'
                    master_edges.append(si_edges)

            # ==========================================
            # 5. ATTRIBUTE TRIAGE
            # ==========================================
            all_columns = df.columns.tolist()
            core_system_cols = ['Student_UUID', 'Parent_UUID', 'Influencer_UUID', 'Unresolved_UUID', 'Interaction_Hash', 'Source_File', 'Source_Sheet']
            core_data_cols = [c for c in all_columns if str(c).startswith('Core_')]
           
            explicit_parent_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols and ('parent' in str(c).lower() or 'guardian' in str(c).lower())]
            explicit_inf_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols and any(x in str(c).lower() for x in ['teacher', 'counsel', 'influencer', 'agent'])]
            generic_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols and c not in explicit_parent_vars and c not in explicit_inf_vars]

            parent_value_vars = explicit_parent_vars + generic_value_vars
            influencer_value_vars = explicit_inf_vars + generic_value_vars
            student_value_vars = generic_value_vars  

            if is_parent_file:
                parent_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols]
                student_value_vars, influencer_value_vars = [], []
            elif is_influencer_file:
                influencer_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols]
                student_value_vars, parent_value_vars = [], []

            global_attributes = ['Role_Discriminator', 'raw_unmapped_baseline_interaction']
            for attr in global_attributes:
                if attr in all_columns:
                    for var_list in [parent_value_vars, influencer_value_vars, student_value_vars]:
                        if attr not in var_list:
                            var_list.append(attr)

            # ==========================================
            # 6. EAV MELTING 
            # ==========================================
            student_core_cols = [c for c in df.columns if str(c).startswith('Core_') and 'parent' not in str(c).lower() and 'influencer' not in str(c).lower()]
            parent_core_cols = [c for c in df.columns if str(c).startswith('Core_Parent_')]
            influencer_core_cols = [c for c in df.columns if str(c).startswith('Core_Influencer_')]

            student_df = df.dropna(subset=['Student_UUID'])
            if not student_df.empty and student_value_vars:
                student_id_vars = [c for c in ['Student_UUID', 'Interaction_Hash', 'Source_File', 'Source_Sheet'] + student_core_cols if c in student_df.columns]
                student_eav = pd.melt(student_df, id_vars=student_id_vars, value_vars=student_value_vars, var_name='Attribute', value_name='Value')
                student_eav = student_eav.rename(columns={'Student_UUID': 'Entity_UUID'})
                student_eav['Entity_Type'] = 'Student'
                master_eav_frames.append(student_eav)
               
            parent_df = df.dropna(subset=['Parent_UUID'])
            if not parent_df.empty and parent_value_vars:
                parent_id_vars = [c for c in ['Parent_UUID', 'Interaction_Hash', 'Source_File', 'Source_Sheet'] + parent_core_cols if c in parent_df.columns]
                parent_eav = pd.melt(parent_df, id_vars=parent_id_vars, value_vars=parent_value_vars, var_name='Attribute', value_name='Value')
                parent_eav = parent_eav.rename(columns={'Parent_UUID': 'Entity_UUID'})
                parent_eav['Entity_Type'] = 'Parent'
                master_eav_frames.append(parent_eav)

            influencer_df = df.dropna(subset=['Influencer_UUID'])
            if not influencer_df.empty and influencer_value_vars:
                inf_id_vars = [c for c in ['Influencer_UUID', 'Interaction_Hash', 'Source_File', 'Source_Sheet'] + influencer_core_cols if c in influencer_df.columns]
                inf_eav = pd.melt(influencer_df, id_vars=inf_id_vars, value_vars=influencer_value_vars, var_name='Attribute', value_name='Value')
                inf_eav = inf_eav.rename(columns={'Influencer_UUID': 'Entity_UUID'})
                inf_eav['Entity_Type'] = 'Influencer'
                master_eav_frames.append(inf_eav)

            unresolved_df = df.dropna(subset=['Unresolved_UUID'])
            if not unresolved_df.empty:
                unresolved_id_vars = [c for c in ['Unresolved_UUID', 'Interaction_Hash', 'Source_File', 'Source_Sheet'] + core_data_cols if c in unresolved_df.columns]
                unresolved_value_vars = [c for c in all_columns if c not in core_system_cols and c not in core_data_cols]
                unresolved_eav = pd.melt(unresolved_df, id_vars=unresolved_id_vars, value_vars=unresolved_value_vars, var_name='Attribute', value_name='Value')
                unresolved_eav = unresolved_eav.rename(columns={'Unresolved_UUID': 'Entity_UUID'})
                unresolved_eav['Entity_Type'] = 'Unresolved'
                master_eav_frames.append(unresolved_eav)

        except Exception as e:
            import traceback
            print(f"    [!] FATAL ERROR processing {file_name}: {e}")
            traceback.print_exc()
           
    final_eav = pd.concat(master_eav_frames, ignore_index=True) if master_eav_frames else pd.DataFrame()
    final_edges = pd.concat(master_edges, ignore_index=True) if master_edges else pd.DataFrame()
    final_audit = pd.DataFrame(master_audit) 
   
    if not final_eav.empty:
        final_eav = final_eav.dropna(subset=['Value'])
        final_eav = final_eav[~final_eav['Value'].astype(str).str.strip().isin(['', 'nan', 'NaN', 'None', '<NA>'])]
        final_eav['Attribute'] = final_eav['Attribute'].astype(str).str.strip().str.lower().str.replace(' ', '_', regex=False)
       
    return final_eav, final_edges, final_audit

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Ingest prospect schemas into an EAV database")
    parser.add_argument('-d', '--dir', type=str, required=True, help='Target directory path')
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f'[!] FATAL: Directory {args.dir} does not exist.')
        exit(1)

    master_eav, master_edges, master_audit = build_eav_pipeline(args.dir)

    # --- SAVE AUDIT LEDGER ---
    if not master_audit.empty:
        audit_path = 'extraction_audit_ledger.csv'
        master_audit.to_csv(audit_path, index=False)
        print(f'\n[+] Audit Ledger saved permanently to: {audit_path}')

    # --- SAVE THE SILVER LAYER (PARQUET HANDOFF) ---
    os.makedirs('data/silver', exist_ok=True)
    if not master_eav.empty:
        master_eav.to_parquet('data/silver/silver_eav.parquet', index=False)
        print('[+] Silver EAV exported to: data/silver/silver_eav.parquet')
        
    if not master_edges.empty:
        master_edges.to_parquet('data/silver/silver_edges.parquet', index=False)
        print('[+] Silver Edges exported to: data/silver/silver_edges.parquet')

    # --- DTALE VISUALIZATION & SERVER SUSPENSION ---
    if not master_eav.empty or not master_edges.empty:
        print(f'\n[*] Initializing DTale diagnostic servers...')
        if not master_eav.empty:
            dtale.show(master_eav, name='EAV Ledger', host='127.0.0.1', port=8000)
            
        if not master_edges.empty:
            # attaches as second instance
            dtale.show(master_edges, name='Graph Edges', host='127.0.0.1', port=8000)

        print(f'   [>] D-Tale Hub loaded at: http://127.0.0.1:8000')

        print(f'\n[*] Server is live, script execution suspended')
        print(f'[*] Press CTRL + C to kill server and exit')
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f'\n[*] Keyboard interrupt detected. Terminating server')
            exit(0)