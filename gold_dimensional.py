
import pandas as pd
import os
import dtale
import time

def flatten_silver_to_wide(eav_path='data/silver/silver_eav.parquet', output_dir='data/gold'):
    if not os.path.exists(eav_path):
        print(f"[!] FATAL: Could not find {eav_path}. Please check your path.")
        return None, None

    os.makedirs(output_dir, exist_ok=True)
    
    print(f"[*] Loading EAV Parquet from {eav_path}...")
    df_eav = pd.read_parquet(eav_path)
    
    print(f"[*] Found {len(df_eav)} vertical attributes. Commencing Dimensional Flattening...")

    # Define our bedrock identity columns (these remain as columns, not attributes)
    index_cols = ['Interaction_Hash', 'Entity_UUID', 'Entity_Type', 'Source_File']
    if 'Source_Sheet' in df_eav.columns:
        index_cols.append('Source_Sheet')
        #Fill NaN values in Source_Sheet so pivot_table doesn't drop CSV rows
        df_eav['Source_Sheet'] = df_eav['Source_Sheet'].fillna('N/A')

    # ==========================================
    # 1. CREATE THE "EVENT" TIMELINE (Wide Format)
    # ==========================================
    print(" [>] Pivoting to Wide Format (1 Row per Interaction)...")
    
    # Pivot computationally transitions rows to columns
    df_events = df_eav.pivot_table(
        index=index_cols, 
        columns='Attribute', 
        values='Value',
        aggfunc='first' # If a form duplicated a field, just take the first one
    ).reset_index()
    
    df_events.columns.name = None # Clean up pandas index naming

    # ==========================================
    # 2. CREATE THE "GOLDEN RECORD" (1 Row per Person)
    # ==========================================
    print(" [>] Compressing into Golden Records (1 Row per Entity)...")
    
    # We drop ephemeral columns (like Interaction_Hash or Source_File) 
    # because a single human profile might span many different files over time.
    demographic_cols = [c for c in df_events.columns if c not in ['Interaction_Hash', 'Source_File', 'Source_Sheet']]
    df_golden = df_events[demographic_cols].copy()
    
    # SURVIVORSHIP RULE: Group by the UUID. 
    # Using .first() in Pandas automatically takes the first NON-NULL value for each column.
    # This magically collapses multiple sparse forms into a single, highly populated profile row!
    df_golden = df_golden.groupby(['Entity_UUID', 'Entity_Type']).first().reset_index()

    # ==========================================
    # 3. EXPORT FOR EXCEL / TABLEAU
    # ==========================================
    events_csv = os.path.join(output_dir, 'Fact_Events_Wide.csv')
    golden_csv = os.path.join(output_dir, 'Dim_Golden_Records.csv')
    
    df_events.to_csv(events_csv, index=False)
    df_golden.to_csv(golden_csv, index=False)
    
    print(f"\n[+] Flattening Complete!")
    print(f" -> Exported Event Timeline ({len(df_events)} rows) to: {events_csv}")
    print(f" -> Exported Golden Records ({len(df_golden)} rows) to: {golden_csv}")

    return df_events, df_golden

if __name__ == '__main__':
    df_events, df_golden = flatten_silver_to_wide()

    # ==========================================
    # 4. LAUNCH D-TALE FOR EXPLORATION
    # ==========================================
    if df_events is not None and not df_events.empty:
        print(f'\n[*] Initializing DTale diagnostic servers...')
        
        # Load the Event View on port 8000
        dtale.show(df_events, name='EventTimeline', host='127.0.0.1', port=8000)
        
        # Load the Golden Record View as an instance on the EXACT SAME server
        dtale.show(df_golden, name='GoldenProfiles', host='127.0.0.1', port=8000)

        print(f' [>] D-Tale loaded at: http://127.0.0.1:8000')
        print(f' [!] Click the top-left menu -> "Instances" to swap between Events and Golden Profiles')
        print(f'\n[*] Server is live. Press CTRL + C to kill server and exit')
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f'\n[*] Terminating server')
            exit(0)
