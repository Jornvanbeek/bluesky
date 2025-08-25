import pandas as pd
from datetime import datetime, timedelta

# Load CSV file (update filename accordingly)
filename = "b2b_flights_with_airspeed.csv"
df = pd.read_csv(filename)

# Dictionary to store generated waypoints { (lat, lon): wpt_name }
waypoint_registry = {}

# Dataframe to store relevant actual flight times which will be compared to the expected
waypoint_time_data = []


# Function to create a unique waypoint name
def get_or_create_waypoint_name(lat, lon, index, existing_name):
    """
    This function returns the waypoint name and the boolean reuse which returns true if the waypoint name has been used
    before and thus defined.

    :float lat: latitude
    :float lon: longitude
    :int index: index of waypoint in database
    :str existing_name: name if it is defined in database
    :return: str waypoint_name, boolean reuse
    """

    if (lat, lon) in waypoint_registry:
        return waypoint_registry[(lat, lon)], True  # Reuse existing name
    else:
        new_wpt_name = existing_name if existing_name else f"Waypoint_name_{index}" # Generate a new name
        waypoint_registry[(lat, lon)] = new_wpt_name
        return new_wpt_name, False


# Function to convert time to BlueSky format
def convert_to_bluesky_time(reference_time, current_time):
    fmt = "%Y-%m-%d %H:%M:%S%z"
    ref_time = datetime.strptime(reference_time, fmt)
    cur_time = datetime.strptime(current_time, fmt)

    delta = cur_time - ref_time
    total_seconds = delta.total_seconds()

    # Convert to HH:MM:SS.sss format
    sim_time = str(timedelta(seconds=total_seconds))  # Gives HH:MM:SS
    if "." not in sim_time:
        sim_time += ".00"  # Ensure milliseconds
    return sim_time


# Function to convert time to BlueSky format
def convert_to_bluesky_time(reference_time, current_time):
    fmt = "%Y-%m-%d %H:%M:%S%z"
    ref_time = datetime.strptime(reference_time, fmt)
    cur_time = datetime.strptime(current_time, fmt)

    delta = cur_time - ref_time
    total_seconds = delta.total_seconds()

    # Convert total seconds to HH:MM:SS.sss format
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Format properly with milliseconds
    sim_time = f"{int(hours):02}:{int(minutes):02}:{seconds:06.2f}"

    return sim_time


def convert_to_seconds(time_str):
    """Converts a time string (HH:MM:SSS.SS) into total seconds as an integer."""
    if not isinstance(time_str, str) or time_str.strip() == "":
        return None  # Handle empty or invalid inputs

    # Split into hours, minutes, and milliseconds
    parts = time_str.split(":")

    if len(parts) != 3:
        return None  # Handle incorrect formats

    hours = int(parts[0])
    minutes = int(parts[1])

    # Split seconds and milliseconds
    seconds_parts = parts[2].split(".")
    seconds = int(seconds_parts[0])  # Ignore milliseconds

    # Convert to total seconds
    total_seconds = (hours * 3600) + (minutes * 60) + seconds
    return total_seconds

# Function to create BlueSky scenario lines for each flight
def create_bluesky_scenario(df):
    scenario_lines = []
    reference_time = None
    for _, row in df.iterrows():
        # print(row)
        message = row['Message ID']
        aircraft_id = row["Aircraft ID"]
        aircraft_type = row["Aircraft Type"]
        departure = row["ADEP"]
        destination = "EHAM"  # Fixed arrival airport: Amsterdam Schiphol
        waypoints = []

        # Find the first waypoint that has an airspeed
        start_index = None
        i = 1
        while f"Waypoint_{i}" in row:
            # print(f"Waypoint_{i}")
            if pd.notna(row[f"Airspeed_{i} (kt)"]):
                start_index = i
                break
            i += 1
        # print('start_index', start_index)
        if start_index is None:
            continue  # Skip this flight if no valid starting waypoint is found

        # Get reference time (first valid waypoint time)
        if not reference_time:
            reference_time = row.get(f"Time Over Waypoint_{start_index}", None)

        # First reference time for each aircraft
        local_reference_time = row.get(f"Time Over Waypoint_{start_index}", None)

        # Extract waypoints starting from the first one with an airspeed
        i = start_index

        # Row
        row_new = {
            "Message ID": message,
            "Aircraft ID": aircraft_id
        }

        while f"Waypoint_{i}" in row and pd.notna(row[f"Airspeed_{i} (kt)"]):
            lat = row[f"Latitude_{i}"]
            lon = row[f"Longitude_{i}"]
            existing_wpt_name = row[f"Waypoint_{i}"] if pd.notna(row[f"Waypoint_{i}"]) else None
            wpt_name, reuse = get_or_create_waypoint_name(lat, lon, i, existing_wpt_name)
            alt = row[f"Flight Level_{i}"].replace("F", "FL")  # Convert "F350" to "FL350"
            airspeed = row[f"Airspeed_{i} (kt)"] if pd.notna(row[f"Airspeed_{i} (kt)"]) else None

            sim_time = convert_to_bluesky_time(reference_time, local_reference_time)
            waypoints.append((wpt_name, lat, lon, alt, sim_time, airspeed))

            time_over = convert_to_bluesky_time(reference_time, row[f"Time Over Waypoint_{i}"])

            row_new[f"Waypoint_{i}"] = wpt_name
            row_new[f"Actual Time Waypoint_{i}"] = convert_to_seconds(time_over)
            row_new[f"BlueSky Time Waypoint_{i}"] = None

            # Define waypoints at first use
            if not reuse:
                scenario_lines.append(
                    f"{sim_time}>defwpt {wpt_name} {lat},{lon}")  # Define only once before first use

            i += 1

        waypoint_time_data.append(row_new)

        # Create aircraft at first valid waypoint
        first_wpt = waypoints[0]
        scenario_lines.append(
            f"{first_wpt[4]}>CRE {aircraft_id},{aircraft_type},{first_wpt[1]},{first_wpt[2]},90,{first_wpt[3]},{first_wpt[5]}")

        # Specify the departure and destination of the aircraft
        scenario_lines.append(f"{first_wpt[4]}>{aircraft_id} ORIG {departure}")
        scenario_lines.append(f"{first_wpt[4]}>{aircraft_id} DEST {destination}")

        # Delete aircraft when arrived at destination
        scenario_lines.append(f'{first_wpt[4]}>{aircraft_id} AT {destination} DO DEL {aircraft_id}')

        # Add waypoints with correct time
        for wpt in waypoints[1:]:
            if wpt[5]:  # If airspeed is present
                scenario_lines.append(f"{wpt[4]}>{aircraft_id} addwpt {wpt[0]},{wpt[3]},{wpt[5]}")

        # Turn on LNAV and VNAV
        scenario_lines.append(f"{first_wpt[4]}>LNAV {aircraft_id} ON")
        scenario_lines.append(f"{first_wpt[4]}>VNAV {aircraft_id} ON")

    return scenario_lines


# Generate scenario
scenario = create_bluesky_scenario(df)

# Save to file
with open("translantic_scenario.scn", "w") as f:
    f.write("\n".join(scenario))


print("BlueSky scenario file created: translantic_scenario.scn")