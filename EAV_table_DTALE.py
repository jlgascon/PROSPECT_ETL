import pandas as pd 
import hashlib
import os
import glob
import re
import argparse
import dtale
import time


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

# define the hash fxn

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
    email = re.sub(r'[^a-zA-Z0-9@.+_-]','', email)

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
    Handles encoding cascades, preamble sniffing, and structural cleaning
    prior to returning a dataframe for EAV processing.
    """
    encodings = ['utf-8', 'latin1', 'cp1252', 'utf-8-sig']
    sample_df = None
    successful_enc = None
   
    # 1. Encoding Cascade & Header Sniffing
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
        return pd.DataFrame()

    # Locate the header: The row with the maximum number of populated columns
    valid_counts = sample_df.notna().sum(axis=1)
    header_idx = int(valid_counts.idxmax())
   
    if header_idx > 0:
        print(f" -> {os.path.basename(file_path)}: Preamble detected. Shifting header to row {header_idx}.")

    # 2. Structural Extraction
    try:
        df = pd.read_csv(file_path, header=header_idx, low_memory=False, on_bad_lines='skip', encoding=successful_enc)
    except Exception as e:
        print(f"[!] {os.path.basename(file_path)} failed full read on {successful_enc}: {e}")
        return pd.DataFrame()

    # 3. Purging Delimiter Artifacts
    # Convert invisible whitespace to NaN
    df.replace(r'^\s*$', pd.NA, regex=True, inplace=True)
    # Drop completely empty rows
    df.dropna(how='all', inplace=True)
   
    # Clean up trailing comma phantom columns
    clean_headers = [col for col in df.columns if not str(col).startswith('Unnamed:')]
    df = df[clean_headers]
   
    return df
# Batch processor

def build_eav_pipeline(directory_path):
    all_files = glob.glob(os.path.join(directory_path, "**", "*.csv"), recursive=True)
    master_eav_frames = []
    master_edges = [] # We now need a ledger for our graph edges
    
    print(f'[*] Commencing pipeline execution on {len(all_files)} files...')

    for file_path in all_files:
        
        file_name = os.path.basename(file_path)
        print(f'\n[>] Ingesting: {file_name}')

        try:
            df = robust_ingest(file_path) 

            if df.empty:
                print(f'    [!] File is empty or failed ingestion. Skipping.')
                continue 

            # Prevent spreadsheets from turning filenames starting with operation chars into #NAME? errors
            if file_name.startswith(('-', '=', '+', '@')):
                df['Source_File'] = f"'{file_name}"
            else:
                df['Source_File'] = file_name
                
            inital_rows = len(df)
           
            # 1. Taxonomic Homogenization
            df.columns = df.columns.str.strip()

            df = df.rename(columns=header_map)
            df = df.groupby(df.columns, axis=1).first()
           
            # 2. Entity Resolution (Dual-Core Generation)
            df['Student_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Email', 'Core_First_Name', 'Core_Last_Name'), axis=1)
               
            df['Parent_UUID'] = df.apply(lambda row: generate_entity_uuid(
                row, 'Core_Parent_Email', 'Core_Parent_First_Name', 'Core_Parent_Last_Name'), axis=1)
           
            # Purge absolute ghosts (rows where BOTH entities failed to generate)
            df = df.dropna(subset=['Student_UUID', 'Parent_UUID'], how='all')
            retained_rows = len(df)

            if df.empty:
                print(f'   [-] Zero valid entities resolved from {initial_rows} rows. Skipping melt.')
                continue
            
            print(f'  [+] Resolved entities: Retained {retained_rows}/{inital_rows} rows.')


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
            core_system_cols = ['Student_UUID', 'Parent_UUID', 'Source_File']
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
                # Lock the student_core_cols into the bedrock alongside the UUID
                student_id_vars = ['Student_UUID', 'Source_File'] + student_core_cols
               
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
                parent_id_vars = ['Parent_UUID', 'Source_File'] + parent_core_cols
               
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
   
    if not final_eav.empty:
        # Purge the void and standardize
        final_eav = final_eav.dropna(subset=['Value'])
        final_eav = final_eav[~final_eav['Value'].astype(str).str.strip().isin(['', 'nan', 'NaN', 'None'])]
        final_eav['Attribute'] = final_eav['Attribute'].astype(str).str.strip().str.lower().str.replace(' ', '_')
       
    return final_eav, final_edges

if __name__ == '__main__':
    #1 configure the cli parser
    parser = argparse.ArgumentParser(description="Ingest, homogoenize, and pivot prospect CSV schemas into an EAV database")
    parser.add_argument(
        '-d', '--dir',
        type=str,
        required=True,
        help='Target directory path containing the raw csv files'

    )

    args = parser.parse_args()

    # trigger the pipeline 
    target_directory = args.dir

    if not os.path.isdir(target_directory):
        print(f'[!] FATAL: Directory {target_directory} does not exist.')
        exit(1)

    master_eav, master_edges = build_eav_pipeline(target_directory)

    # DTale visualization & Server suspension

    if not master_eav.empty or not master_edges.empty:
        print(f'\n[*] Initializing DTale diagnostic servers...')

        if not master_eav.empty:

            #getting a more definitive instantiation: space instead of underscore in name attr, forced IPv4, static port

            d_eav = dtale.show(master_eav, name='EAV Ledger', host='localhost', port=8000)
            #print(f'   [>] EAV Table loaded at: {d_eav.main_url()}')
            print(f'   [>] EAV Table loaded at: http:127.0.0.1:8000')
            print(f'\n[*] Server is live, script execution suspended')
            print(f'[*] Press CTRL + C to kill server and exit')

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print(f'\n[*] Keyboard interrupt detected. Terminating server')
                exit(0)
