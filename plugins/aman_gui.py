# import tkinter as tk
# from datetime import datetime, timedelta
# import pandas as pd
# import random
# import math  # for math.isnan()
#
# # --- CONSTANTS FOR DYNAMIC TIMELINE ---
# PIXELS_PER_MINUTE = 25  # Fixed pixel distance between each minute
# MARGIN = 30  # Top and bottom margin
#
#
# # --- HELPER FUNCTIONS ---
# def format_time(seconds):
#     """Format seconds as HH:MM:SS; return '--' if seconds is NaN."""
#     try:
#         if math.isnan(seconds):
#             return "--"
#     except TypeError:
#         pass
#     seconds = int(seconds)
#     hours = seconds // 3600
#     minutes = (seconds % 3600) // 60
#     secs = seconds % 60
#     return f"{hours:02d}:{minutes:02d}:{secs:02d}"
#
#
# def format_duration(seconds):
#     """Format seconds as MM:SS; return '--' if seconds is NaN."""
#     try:
#         if math.isnan(seconds):
#             return "--"
#     except TypeError:
#         pass
#     seconds = int(seconds)
#     minutes = seconds // 60
#     secs = seconds % 60
#     return f"{minutes:02d}:{secs:02d}"
#
#
# def parse_time_str(time_str):
#     """Parse a HH:MM:SS string to seconds since midnight."""
#     try:
#         h, m, s = map(int, time_str.split(":"))
#         return h * 3600 + m * 60 + s
#     except Exception:
#         return None
#
#
# # Global variables for timeline bounds and dynamic canvas height.
# earliest_slottime = 0
# latest_slottime = 0
# CANVAS_HEIGHT = 0  # Will be computed dynamically
#
#
# def time_to_y(t):
#     """
#     Map a time t (in seconds) to a y-coordinate.
#     The distance between slottimes is fixed: PIXELS_PER_MINUTE per minute.
#     """
#     minutes_since_start = (t - earliest_slottime) / 60
#     return MARGIN + minutes_since_start * PIXELS_PER_MINUTE
#
#
# def reversed_y(t):
#     """Reverse the y mapping so that later times appear at the top."""
#     return CANVAS_HEIGHT - time_to_y(t)
#
#
# # --- SCROLLABLE FRAME CLASS ---
# class ScrollableFrame(tk.Frame):
#     def __init__(self, container, *args, **kwargs):
#         super().__init__(container, *args, **kwargs)
#         self.config(bg="#001B4F")
#         self.canvas = tk.Canvas(self, bg="#001B4F", highlightthickness=0)
#         self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
#         self.scrollable_frame = tk.Frame(self.canvas, bg="#001B4F")
#         self.scrollable_frame.bind(
#             "<Configure>",
#             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
#         )
#         self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
#         self.canvas.configure(yscrollcommand=self.scrollbar.set)
#         self.canvas.pack(side="left", fill="both", expand=True)
#         self.scrollbar.pack(side="right", fill="y")
#         self.canvas.bind("<Enter>", lambda e: self._bind_mousewheel())
#         self.canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())
#
#     def _bind_mousewheel(self):
#         self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
#         self.canvas.bind_all("<Button-4>", self._on_mousewheel)
#         self.canvas.bind_all("<Button-5>", self._on_mousewheel)
#
#     def _unbind_mousewheel(self):
#         self.canvas.unbind_all("<MouseWheel>")
#         self.canvas.unbind_all("<Button-4>")
#         self.canvas.unbind_all("<Button-5>")
#
#     def _on_mousewheel(self, event):
#         if event.num == 4 or event.delta > 0:
#             self.canvas.yview_scroll(-1, "units")
#         elif event.num == 5 or event.delta < 0:
#             self.canvas.yview_scroll(1, "units")
#
#
# # --- MAIN GUI CLASS ---
# class ArrivalManagerGUI(tk.Tk):
#     def __init__(self):
#         super().__init__()
#         self.title("Arrival Manager GUI")
#         self.config(bg="#001B4F")
#
#         # --- CONTROL PANEL ---
#         self.control_frame = tk.Frame(self, bg="#001B4F")
#         self.control_frame.pack(side="top", fill="x", padx=5, pady=5)
#
#         tk.Label(self.control_frame, text="Now (HH:MM:SS):", bg="#001B4F", fg="lime",
#                  font=("Helvetica", 12, "bold")).pack(side="left", padx=5)
#         self.now_entry = tk.Entry(self.control_frame, width=10)
#         self.now_entry.pack(side="left", padx=5)
#         # Default to machine's UTC time.
#         self.now_entry.insert(0, datetime.now().strftime("%H:%M:%S"))
#
#         tk.Label(self.control_frame, text="Window (minutes, empty for all):", bg="#001B4F", fg="lime",
#                  font=("Helvetica", 12, "bold")).pack(side="left", padx=5)
#         self.window_entry = tk.Entry(self.control_frame, width=5)
#         self.window_entry.pack(side="left", padx=5)
#
#         tk.Button(self.control_frame, text="Refresh", command=self.refresh_display,
#                   font=("Helvetica", 12, "bold")).pack(side="left", padx=5)
#
#         # --- SCROLLABLE FRAME FOR CONTENT ---
#         self.scroll_frame = ScrollableFrame(self)
#         self.scroll_frame.pack(side="top", fill="both", expand=True)
#
#         self.runway_order = []
#         self.runway_frames = {}  # Keyed by runway name
#         self.timeline_frames = {}  # Keyed by runway name for adjacent timelines
#
#         self.main_frame = tk.Frame(self.scroll_frame.scrollable_frame, bg="#001B4F")
#         self.main_frame.pack(side="top", fill="both", expand=True)
#
#         self.all_flights = None  # Store the full DataFrame
#
#     def create_runway_frame(self, parent, runway_name):
#         """Create a runway frame with title and canvas for flight info."""
#         frame = tk.Frame(parent, bg="#001B4F", highlightbackground="red", highlightthickness=2)
#         label = tk.Label(frame, text=runway_name, bg="#001B4F", fg="lime",
#                          font=("Helvetica", 12, "bold"))
#         label.pack(side="top", pady=2)
#         # Use dynamic CANVAS_HEIGHT computed in update_gui
#         canvas = tk.Canvas(frame, width=430, height=CANVAS_HEIGHT, bg="#001B4F", highlightthickness=0)
#         canvas.pack(side="top", fill="both", expand=True)
#         frame.canvas = canvas
#         return frame
#
#     def create_timeline_frame(self, parent):
#         """Create a timeline frame for drawing slot markers."""
#         frame = tk.Frame(parent, bg="#001B4F", highlightbackground="red", highlightthickness=2)
#         label = tk.Label(frame, text="Slot Timeline", bg="#001B4F", fg="lime",
#                          font=("Helvetica", 12, "bold"))
#         label.pack(side="top", pady=2)
#         canvas = tk.Canvas(frame, width=80, height=CANVAS_HEIGHT, bg="#001B4F", highlightthickness=0)
#         canvas.pack(side="top", fill="both", expand=True)
#         frame.canvas = canvas
#         return frame
#
#     def draw_timeline(self, timeline_frame):
#         """Draw dotted lines for every minute with a label every 5 minutes."""
#         canvas = timeline_frame.canvas
#         t = earliest_slottime
#         while t <= latest_slottime:
#             y = reversed_y(t)
#             canvas.create_line(0, y, 80, y, fill="gray", dash=(1, 2))
#             # Adjusted: Label every 5 minutes relative to earliest_slottime.
#             if (t - earliest_slottime) % 300 == 0:
#                 label_text = format_time(t)[:-3]
#                 canvas.create_text(40, y, text=label_text, fill="lime", font=("Courier", 12, "bold"))
#             t += 60
#
#     def update_gui(self, flights_df):
#         """
#         Update the GUI using the provided DataFrame flights_df.
#         Recalculate timeline bounds, compute a dynamic canvas height based on a fixed
#         pixel distance between slottimes, rebuild runway columns, and redraw flights.
#         """
#         global earliest_slottime, latest_slottime, CANVAS_HEIGHT
#         if flights_df.empty:
#             for widget in self.main_frame.winfo_children():
#                 widget.destroy()
#             return
#
#         # earliest_slottime = flights_df['slot'].min()
#         latest_slottime = flights_df['slot'].max()
#
#         # Compute dynamic canvas height based on timeline length:
#         total_minutes = (latest_slottime - earliest_slottime) / 60
#         if total_minutes < 1:
#             total_minutes = 1
#         CANVAS_HEIGHT = int(2 * MARGIN + total_minutes * PIXELS_PER_MINUTE)
#
#         self.runway_order = list(flights_df['runway'].unique())
#
#         # Clear any existing frames.
#         for widget in self.main_frame.winfo_children():
#             widget.destroy()
#         self.runway_frames.clear()
#         self.timeline_frames.clear()
#
#         # Rebuild columns.
#         for i, runway in enumerate(self.runway_order):
#             runway_frame = self.create_runway_frame(self.main_frame, runway)
#             runway_frame.pack(side="left", padx=5, pady=5)
#             self.runway_frames[runway] = runway_frame
#             if i < len(self.runway_order) - 1:
#                 timeline_frame = self.create_timeline_frame(self.main_frame)
#                 timeline_frame.pack(side="left", padx=5, pady=5)
#                 self.timeline_frames[runway] = timeline_frame
#
#         # Draw flights and timeline markers.
#         for i in range(len(self.runway_order)):
#             runway = self.runway_order[i]
#             previous_runway = self.runway_order[i - 1] if i > 0 else None
#
#             flights_for_runway = (
#                 flights_df[flights_df['runway'] == runway]
#                 .dropna(subset=['slot'])
#                 .reset_index()
#                 .rename(columns={'index': 'ACID'})
#                 .to_dict('records')
#             )
#             self.draw_flights(self.runway_frames[runway], flights_for_runway)
#             if runway in self.timeline_frames or (previous_runway and previous_runway in self.timeline_frames):
#                 if previous_runway:
#                     self.draw_flight_markers(self.timeline_frames[previous_runway], flights_for_runway, 80, 65)
#                 else:
#                     self.timeline_frames[runway].canvas.delete("all")
#                     self.draw_timeline(self.timeline_frames[runway])
#                     self.draw_flight_markers(self.timeline_frames[runway], flights_for_runway, 0, 15)
#
#     def draw_flights(self, runway_frame, flights):
#         """
#         For each flight, place it on the runway canvas based on its 'slot'
#         and display flight info.
#         """
#         canvas = runway_frame.canvas
#         for flight in flights:
#             if pd.isna(flight.get("slot")):
#                 continue
#             y = reversed_y(flight["slot"])
#             info = (
#                 f"{flight.get('ACID', 'N/A'):<8} "
#                 f"{flight.get('type', 'N/A'):<6} "
#                 f"{flight.get('IAF', 'N/A'):<8} "
#                 f"{format_time(flight.get('ETA', 0)):<11} "
#                 f"{format_time(flight.get('EAT', 0)):<11} "
#                 f"{format_duration(flight.get('ttlg', 0)):<6}"
#             )
#             canvas.create_text(10, y, text=info, fill="lime",
#                                font=("Courier", 12, "bold"), anchor="w", width=430 - 20)
#
#     def draw_flight_markers(self, timeline_frame, flights, start=80, stop=70):
#         """
#         On the timeline canvas, draw a horizontal green line at each flight's slot.
#         """
#         canvas = timeline_frame.canvas
#         for flight in flights:
#             if pd.isna(flight.get("slot")):
#                 continue
#             y = reversed_y(flight["slot"])
#             canvas.create_line(start, y, stop, y, fill="green", width=2)
#
#     def refresh_display(self, now_ts=None):
#         """
#         Refresh the display:
#         - If a now_ts timestamp (in seconds since midnight) is provided, use it.
#         - Otherwise, try to read from the GUI's now_entry, falling back to machine's UTC time.
#         Also applies the window filter if provided.
#         """
#         if now_ts is not None:
#             custom_now = now_ts
#         else:
#             custom_now_str = self.now_entry.get()
#             custom_now = parse_time_str(custom_now_str)
#             if custom_now is None:
#                 now = datetime.now()
#                 custom_now = now.hour * 3600 + now.minute * 60 + now.second
#
#         window_val = self.window_entry.get().strip()
#         if window_val:
#             try:
#                 window_minutes = int(window_val)
#             except ValueError:
#                 window_minutes = None
#         else:
#             window_minutes = None
#
#         if self.all_flights is not None and window_minutes is not None and window_minutes > 0:
#             window_end = custom_now + window_minutes * 60
#             filtered = self.all_flights[
#                 (self.all_flights['slot'] >= custom_now) &
#                 (self.all_flights['slot'] <= window_end)
#                 ]
#         else:
#             filtered = self.all_flights if self.all_flights is not None else pd.DataFrame()
#
#         self.update_gui(filtered)
#
#     def set_data(self, flights_df, now_ts=None):
#         """Store the full flights DataFrame and refresh the display using an optional now timestamp."""
#         self.all_flights = flights_df
#         self.refresh_display(now_ts=now_ts)
#
#
# # Create a global instance of the GUI.
# _gui_instance = ArrivalManagerGUI()
#
#
# def run_gui():
#     """Start the Tkinter mainloop."""
#     _gui_instance.mainloop()
#
#
# # Example: Load flights data and set it in the GUI.
# new_flights = pd.read_pickle('/Users/jornvanbeek/Documents/Thesis/amanbluesky/main/flights.pkl')
# # Optionally, provide a now timestamp (in seconds since midnight) here.
# _gui_instance.set_data(new_flights)
#
# # Start the GUI.
# run_gui()