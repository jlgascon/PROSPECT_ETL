import pandas as pd
import sweetviz as sv
from pathlib import Path

def generate_sweetviz_reports(input_directory, output_directory, skip_existing=True):
    """
    Finds all CSVs in nested folders of the input directory and generates 
    Sweetviz HTML reports in the output directory.
    """
    
    # Define paths
    input_dir = Path(input_directory)
    output_dir = Path(output_directory)
    
    # Check if input directory exists
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Error: The input directory '{input_dir}' does not exist.")
        return

    # Find all .csv files recursively
    csv_files = list(input_dir.rglob("*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in '{input_dir}' or its subdirectories.")
        return
        
    print(f"Found {len(csv_files)} CSV file(s). Starting Sweetviz report generation...\n")

    for file_path in csv_files:
        try:
            # Determine relative path to replicate folder structure
            relative_path = file_path.relative_to(input_dir)
            report_dir = output_dir / relative_path.parent
            report_filename = report_dir / f"{file_path.stem}_report.html"
            
            # Check if we should skip existing files
            if skip_existing and report_filename.exists():
                print(f"Skipping: '{file_path.name}' -> Report already exists.")
                continue
                
            print(f"Processing: {file_path}")
            
            # Create the corresponding output directory structure
            report_dir.mkdir(parents=True, exist_ok=True)
            
            # Read the CSV
            df = pd.read_csv(file_path)
            
            # Skip completely empty dataframes
            if df.empty:
                print(f"  -> Skipped: '{file_path.name}' is empty.\n")
                continue

            # Generate the Sweetviz report
            report = sv.analyze(df)
            
            # Save the report (open_browser=False prevents 50 tabs from opening at once)
            report.show_html(filepath=str(report_filename), open_browser=False)
            
            print(f"  -> Successfully generated: {report_filename}\n")
            
        except pd.errors.EmptyDataError:
            print(f"  -> Skipped: '{file_path.name}' contains no columns/data to parse.\n")
        except Exception as e:
            print(f"  -> Error processing '{file_path}': {e}\n")

    print("All tasks completed.")

# --- Configuration ---
if __name__ == "__main__":
    # Change these paths to match your actual folder locations
    SOURCE_FOLDER = r'data\raw\extracted\2025_2026'
    DESTINATION_FOLDER = r'data\processed\EDA_exports'
    
    # Run the function
    generate_sweetviz_reports(SOURCE_FOLDER, DESTINATION_FOLDER, skip_existing=True)