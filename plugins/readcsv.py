import pandas as pd

# Display all columns and rows for debugging
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)


def parse_csv(file_path):
    # Read CSV file into DataFrame
    df = pd.read_csv(file_path)

    # Fill NaN values with empty strings if needed
    df = df.fillna("")
    return df


def get_all_aircraft_performance_data(df):
    data_entries = []

    # Iterate over each row in the DataFrame
    for _, row in df.iterrows():
        # Extract data for aircraft type and airline (if present)
        aircraft_type = row['type']
        airline = row['performance_name'] if row['performance_name'] else 'default'

        # Create dictionary for the performance data, starting with 'type' and 'airline'
        performance_data = {
            'type': aircraft_type,
            'airline': airline
        }

        # Loop over each column except 'type' and 'performance_name'
        for col in df.columns:
            if col not in ['type', 'performance_name']:
                try:
                    # Convert value to float if possible, otherwise keep as is
                    performance_data[col] = float(row[col]) if row[col] != "" else None
                except ValueError:
                    performance_data[col] = row[col]

        data_entries.append(performance_data)

    return data_entries


def perf_dataframe(file_path):
    df = parse_csv(file_path)
    all_data = get_all_aircraft_performance_data(df)

    # Convert list of dictionaries to DataFrame
    return pd.DataFrame(all_data)

# Usage example
# df = perf_dataframe('AircraftDB.csv')
# print(df)
# print(df['type'].value_counts())
# print(df[df['airline'] == 'SAS'])