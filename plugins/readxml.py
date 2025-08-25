import xml.etree.ElementTree as ET
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 250)

def parse_xml(file_path):
    tree = ET.parse(file_path)
    return tree.getroot()





def get_all_aircraft_performance_data(root):
    data_entries = []

    # Iterate through each aircraft in the XML
    for aircraft in root.findall('.//aircraft'):
        aircraft_type = aircraft.get('type')

        # Retrieve default performance metrics (no performance name)
        default_performance_data = {}
        for performance in aircraft.findall('.//performance'):
            if performance.get('name') is None or performance.get('name') == "":
                for child in performance:
                    # Special handling for 'tas' tags with an 'id' attribute
                    if child.tag == "tas":
                        tas_id = child.get("id")
                        tas_key = f"tas_{tas_id}" if tas_id else "tas"
                        default_performance_data[tas_key] = float(child.text) if child.text is not None else None
                    else:
                        default_performance_data[child.tag] = float(child.text) if child.text is not None else None

                # Reorder keys to have 'type' and 'airline' first
                ordered_data = {
                    'type': aircraft_type,
                    'airline': 'default',
                    **default_performance_data
                }
                data_entries.append(ordered_data)

        # Retrieve and append airline-specific performance metrics
        for performance in aircraft.findall('.//performance'):
            if performance.get('name'):
                airline_performance_data = {}
                for child in performance:
                    if child.tag == "tas":
                        tas_id = child.get("id")
                        tas_key = f"tas_{tas_id}" if tas_id else "tas"
                        airline_performance_data[tas_key] = float(child.text) if child.text is not None else None
                    else:
                        airline_performance_data[child.tag] = float(child.text) if child.text is not None else None

                # Reorder keys to have 'type' and 'airline' first
                ordered_data = {
                    'type': aircraft_type,
                    'airline': performance.get('name'),
                    **airline_performance_data
                }
                data_entries.append(ordered_data)

    return data_entries




def perf_dataframe(file_path):
    root = parse_xml(file_path)
    all_data = get_all_aircraft_performance_data(root)

    # Convert the list of dictionaries to a DataFrame
    df = pd.DataFrame(all_data)
    return df



#
# # Usage
# df = create_dataframe('AircraftDB.xml')
# print(df)
# print(df['aircraft_type'].value_counts())
# print(df[df['airline']=='KLM'])
