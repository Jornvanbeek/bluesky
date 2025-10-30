@stack.command
def htmlflights(self):
    if self.aman_parent_id:
        return

    # Save as HTML with fixed headers
    Flights_hhmmss = self.Flights.copy()
    columns_to_transform = ['ETA', 'ETO IAF', 'EAT', 'slot', 'LAS']
    for col in columns_to_transform:
        Flights_hhmmss[col] = Flights_hhmmss[col].apply(
            lambda x: None if pd.isna(x) else f"{int(x // 3600):02}:{int((x % 3600) // 60):02}:{int(x % 60):02}")

    # Save as HTML with fixed headers and index included
    html = Flights_hhmmss.to_html(classes='table table-bordered', index=True)
    html_with_style = f"""
       <html>
       <head>
       <style>
           .table {{
               border-collapse: collapse;
               width: 100%;
           }}
           .table th {{
               position: sticky;
               top: 0;
               background: #f1f1f1;
           }}
           .table th, .table td {{
               border: 1px solid black;
               padding: 8px;
               text-align: left;
           }}
       </style>
       </head>
       <body>
       {html}
       </body>
       </html>
       """
    output_path = "output.html"

    # Write to file
    with open(output_path, "w") as f:
        f.write(html_with_style)

    # Automatically open in the browser
    webbrowser.open(f"file://{os.path.abspath(output_path)}")



    @stack.command
    def AMANwptcross(self, acid: str, wpt: str):
        """Handles aircraft waypoint crossing, updating the actual time of arrival (ATA)."""
        # TODO: This function is still not used and can be used to calculate the ATA

        if self.aman_parent_id:
            return

        ata_timestamp = sim.utc.timestamp()
        ata_datetime = datetime.fromtimestamp(ata_timestamp, tz=None)