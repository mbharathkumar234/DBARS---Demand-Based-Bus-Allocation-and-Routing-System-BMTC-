import os
import json
import csv

FARES_DIR = r"c:\Users\bhara\Desktop\Bharath's\bmtc\dataset\fares"
OUTPUT_FILE = r"c:\Users\bhara\Desktop\Bharath's\bmtc\dataset\fares.csv"

def aggregate_fares():
    print("Starting fare aggregation...")
    
    if not os.path.exists(FARES_DIR):
        print(f"Error: Directory {FARES_DIR} not found.")
        return

    csv_data = []
    
    # List all json files
    for filename in os.listdir(FARES_DIR):
        if not filename.endswith('.json'):
            continue
            
        # Parse source and destination from filename: Source_Destination.json
        name_part = filename[:-5]
        if '_' not in name_part:
            continue
            
        parts = name_part.split('_')
        source = parts[0]
        destination = '_'.join(parts[1:]) # Just in case destination has an underscore
        
        filepath = os.path.join(FARES_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if data.get('Issuccess') and data.get('data'):
                fares_list = data['data']
                for fare_info in fares_list:
                    service_type = fare_info.get('servicetype', '')
                    fare = fare_info.get('fare', '')
                    csv_data.append([source, destination, service_type, fare])
        except Exception as e:
            pass # Ignore read errors to keep the console clean

    # Write to CSV
    print(f"Writing {len(csv_data)} rows to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['source', 'destination', 'service_type', 'fare'])
        writer.writerows(csv_data)
        
    print("Aggregation complete!")

if __name__ == '__main__':
    aggregate_fares()
