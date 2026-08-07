import os
import csv
import argparse
from datetime import datetime

def find_pet_folders(start_path):
    """
    Find all folders named 'pet' starting from the given path,
    and record their paths along with filenames inside them.
    
    Args:
        start_path (str): The path to start the search from
        
    Returns:
        list: List of dictionaries containing folder path and filenames
    """
    results = []
    
    # Walk through the directory tree
    for root, dirs, files in os.walk(start_path):
        # Check if the current directory's name is 'pet'
        if os.path.basename(root) == 'pet':
            # Record this folder
            folder_info = {
                'folder_path': root,
                'files': files
            }
            results.append(folder_info)
            
    return results

def save_to_csv(results, output_file=None):
    """
    Save the results to a CSV file.
    
    Args:
        results (list): List of dictionaries with folder paths and files
        output_file (str, optional): Output CSV filename
    """
    if output_file is None:
        # Generate a default filename with timestamp if none provided
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"pet_folders_{timestamp}.csv"
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['folder_path', 'filename']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        # Write each folder and its files to the CSV
        for folder_info in results:
            folder_path = folder_info['folder_path']
            
            if not folder_info['files']:
                # If folder is empty, write one row with empty filename
                writer.writerow({
                    'folder_path': folder_path,
                    'filename': ''
                })
            else:
                # Write a row for each file in the folder
                for filename in folder_info['files']:
                    writer.writerow({
                        'folder_path': folder_path,
                        'filename': filename
                    })
    
    print(f"Results saved to {output_file}")
    return output_file

def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Find all folders named "pet" and record their paths and filenames.')
    parser.add_argument('start_path', nargs='?', default=os.getcwd(),
                        help='The path to start searching from (default: current directory)')
    parser.add_argument('-o', '--output', help='Output CSV filename')
    
    args = parser.parse_args()
    
    # No message about starting the search
    print("Searching for 'pet' folders...")
    
    # Find pet folders
    results = find_pet_folders(args.start_path)
    
    # Count the total number of files (for internal use only)
    total_files = sum(len(folder_info['files']) for folder_info in results)
    
    # Save results to CSV if any found, silently exit otherwise
    if results:
        output_file = save_to_csv(results, args.output)
        print(f"Data saved to {output_file}")

if __name__ == "__main__":
    main()