#!/usr/bin/env python3
"""
Interactive Scan Finder Script

This script provides an interactive way to search for T1w and PET scan files.
"""

from scan_finder import (
    DEFAULT_ADRC_ROOT,
    find_t1w_scan,
    find_pet_scan,
    list_available_dates,
    convert_date_format,
)


def interactive_scan_finder():
    """
    Interactive function to help users find scan files.
    """
    print("=== Interactive Scan Finder ===")
    print("This tool helps you find T1w and PET scan files.")
    print("Date format: MM/DD/YYYY (e.g., 01/15/2020)")
    print()

    # Dataset root: taken from $ADRC_ROOT if set, otherwise asked for once.
    base_path = DEFAULT_ADRC_ROOT
    if base_path:
        print(f"Dataset root (from $ADRC_ROOT): {base_path}")
    else:
        base_path = input("Enter the dataset root (e.g. /data/ADRC): ").strip()
    if not base_path:
        print("No dataset root given. Exiting.")
        return

    while True:
        print("\nOptions:")
        print("1. Find T1w scan")
        print("2. Find PET scan")
        print("3. List available dates for a patient")
        print("4. Convert date format")
        print("5. Exit")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == "1":
            patient_id = input("Enter patient ID: ").strip()
            scan_date = input("Enter scan date (MM/DD/YYYY): ").strip()
            
            result = find_t1w_scan(patient_id, scan_date, base_path)
            if result:
                print(f"\n✅ T1w scan found: {result}")
            else:
                print("\n❌ T1w scan not found.")
                
        elif choice == "2":
            patient_id = input("Enter patient ID: ").strip()
            scan_date = input("Enter scan date (MM/DD/YYYY): ").strip()
            
            result = find_pet_scan(patient_id, scan_date, base_path)
            if result:
                print(f"\n✅ PET scan found: {result}")
            else:
                print("\n❌ PET scan not found.")
                
        elif choice == "3":
            patient_id = input("Enter patient ID: ").strip()
            dates = list_available_dates(patient_id, base_path)
            
            if dates:
                print(f"\n📅 Available scan dates for patient {patient_id}:")
                for i, date in enumerate(dates, 1):
                    print(f"   {i}. {date}")
            else:
                print(f"\n❌ No scan dates found for patient {patient_id}")
                
        elif choice == "4":
            date_input = input("Enter date to convert (MM/DD/YYYY): ").strip()
            try:
                converted = convert_date_format(date_input)
                print(f"\n🔄 {date_input} → {converted}")
            except ValueError as e:
                print(f"\n❌ Error: {e}")
                
        elif choice == "5":
            print("\nGoodbye! 👋")
            break
            
        else:
            print("\n❌ Invalid choice. Please enter 1-5.")


if __name__ == "__main__":
    interactive_scan_finder()