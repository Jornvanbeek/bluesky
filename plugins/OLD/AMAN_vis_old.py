# from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
# from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPalette
# from PyQt6.QtCore import Qt, QPointF, QTimer, QTime
# from datetime import datetime, timedelta
# import sys
#
# from bluesky import core, stack, network
# from bluesky.network.common import GROUPID_SIM
#
#
# def init_plugin():
#     aman_window = AMANWindow()
#
#     config = {
#         'plugin_name': 'AMANWINDOW_old',
#         'plugin_type': 'gui',
#     }
#     return config
#
#
# class AMANWindow(core.Entity):
#     """
#     Define the window for the AMAN plugin.
#
#     Attributes:
#         data (tuple): Tuple containing acids_allocated, ETAs, arrival_slots, ATAs.
#         airport (str): The selected airport.
#         runway (str): The selected runway.
#         app (QApplication): The main application instance.
#         main_window (MainWindow): The main window instance.
#     """
#
#     def __init__(self):
#         """Initialize the AMANWindow with default values."""
#         super().__init__()
#         self.data = 0, 0, 0, 0
#         self.airport = None
#         self.runway = None
#         self.app = None
#         self.main_window = None
#
#     def init_ui(self):
#         """Initialize the user interface and display the main window."""
#         acids, etas, arrival_slots, atas = self.data
#         data = {
#             'acids': acids[self.airport][self.runway],
#             'etas': etas[self.airport][self.runway],
#             'arrival_slots': arrival_slots[self.airport][self.runway],
#             'atas': atas[self.airport][self.runway],
#         }
#
#         self.app = QApplication.instance() or QApplication(sys.argv)
#         self.main_window = MainWindow(data)
#         self.main_window.show()
#
#     @network.subscriber(topic='AMANINFO', to_group=GROUPID_SIM)
#     def on_aman_info_received(self, acids_allocated, ETAs, arrival_slots, ATAs):
#         """
#         Receive AMAN information and update the data.
#
#         Parameters:
#             acids_allocated (dict): Allocated aircraft IDs.
#             ETAs (list): Estimated times of arrival.
#             arrival_slots (list): Arrival slots.
#             ATAs (list): Actual times of arrival.
#         """
#         self.data = acids_allocated, ETAs, arrival_slots, ATAs
#
#     @stack.command
#     def aman_show(self, airport, runway):
#         """
#         Command to show the AMAN visualization for a specific airport and runway.
#
#         Parameters:
#             airport (str): The airport code.
#             runway (str): The runway code.
#         """
#         if not airport or not runway:
#             stack.stack(f"ECHO No correct inputs have been given.")
#         else:
#             acids_allocated, ETAs, arrival_slots, atas = self.data
#             if isinstance(acids_allocated, dict) and isinstance(acids_allocated.get(airport.upper()), dict):
#                 if acids_allocated[airport.upper()][runway.upper()]:
#                     self.airport = airport.upper()
#                     self.runway = runway.upper()
#                     self.init_ui()
#             else:
#                 stack.stack(f"ECHO There is no relevant data to show.")
#
#
# class HeaderWidget(QWidget):
#     """
#     Define a header widget for the visualization.
#
#     Methods:
#         setupPalette(): Set up the color palette for the header.
#         paintEvent(event): Draw the header labels.
#     """
#
#     def __init__(self, parent=None):
#         """Initialize the HeaderWidget with default size and palette."""
#         super().__init__(parent)
#         self.setMinimumHeight(50)
#         self.setMinimumWidth(600)
#         self.setupPalette()
#
#     def setupPalette(self):
#         """Set up the color palette for the header."""
#         palette = QPalette()
#         palette.setColor(QPalette.ColorRole.Window, QColor(1, 71, 71, 255))
#         self.setPalette(palette)
#         self.setAutoFillBackground(True)
#
#     def paintEvent(self, event):
#         """Draw the header labels."""
#         painter = QPainter(self)
#         font = QFont("Arial", 12, QFont.Weight.Bold)
#         painter.setFont(font)
#         fm = QFontMetrics(font)
#
#         painter.setPen(QColor(255, 255, 255))
#         line_x_eta = 100
#         line_x_slot = 300
#         line_x_ata = 500
#         painter.drawText(QPointF(line_x_eta - fm.horizontalAdvance("ETA") / 2, 20), "ETA")
#         painter.drawText(QPointF(line_x_slot - fm.horizontalAdvance("SLOT") / 2, 20), "SLOT")
#         painter.drawText(QPointF(line_x_ata - fm.horizontalAdvance("ATA") / 2, 20), "ATA")
#
#
# class FlightTimelineWidget(QWidget):
#     """
#     Define a widget to display the flight timelines.
#
#     Attributes:
#         flights (dict): Dictionary containing flight timings.
#         data (dict): Data for flights: acids, etas, arrival_slots, atas.
#         grid_interval (int): Interval for grid lines in minutes.
#         vertical_scale (int): Pixels per minute of grid interval.
#         earliest_time (datetime): The earliest ETA time for scaling the timeline.
#
#     Methods:
#         load_flight_data(): Load flight data into the widget.
#         setupPalette(): Set up the color palette for the timeline widget.
#         updateMinimumHeight(): Update the minimum height of the widget based on flight data.
#         paintEvent(event): Draw the flight timelines.
#     """
#
#     def __init__(self, data, parent=None):
#         """Initialize the FlightTimelineWidget with data and default settings."""
#         super().__init__(parent)
#         self.flights = {}
#         self.data = data
#         self.setMinimumSize(1000, 3000)  # Extended height to demonstrate scrolling
#         self.grid_interval = 5
#         self.vertical_scale = 10  # Pixels per minute of grid interval
#         self.setupPalette()
#         self.load_flight_data()
#         self.updateMinimumHeight()
#
#     def load_flight_data(self):
#         """Load flight data into the widget."""
#         acids = self.data['acids']
#         etas = self.data['etas']
#         arrival_slots = self.data['arrival_slots']
#         atas = self.data['atas']
#
#         earliest_time = None
#
#         for i in range(len(acids)):
#             acid = acids[i]
#             eta = etas[i]
#             slot = arrival_slots[i]
#             ata = atas[i]
#             dt_eta = datetime.utcfromtimestamp(eta)
#             dt_slot = datetime.utcfromtimestamp(slot)
#             dt_ata = datetime.utcfromtimestamp(ata)
#
#             if earliest_time is None or dt_eta < earliest_time:
#                 earliest_time = dt_eta
#
#             if acid not in self.flights and eta > 0:
#                 self.flights[acid] = {'ETA': dt_eta, 'ATA': dt_ata, 'Slot': dt_slot}
#
#         self.earliest_time = earliest_time
#         print(f"Earliest Time: {self.earliest_time}")
#         self.updateMinimumHeight()
#         self.update()
#
#     def setupPalette(self):
#         """Set up the color palette for the timeline widget."""
#         palette = QPalette()
#         palette.setColor(QPalette.ColorRole.Window, QColor(1, 71, 71, 255))
#         self.setPalette(palette)
#
#     def updateMinimumHeight(self):
#         """Update the minimum height of the widget based on flight data."""
#         if not self.flights:
#             self.setMinimumHeight(500)
#             return
#
#         max_minute = 0
#         for timings in self.flights.values():
#             for dt in timings.values():
#                 if dt:
#                     minutes = (dt - self.earliest_time).total_seconds() / 60
#                     print(f"Flight Time: {dt}, Minutes Since Earliest: {minutes}")
#                     if minutes > max_minute:
#                         max_minute = minutes
#
#         min_height = int((max_minute * self.vertical_scale) / self.grid_interval + 100)
#         # print(f"Calculated Minimum Height: {min_height}")
#         self.setMinimumHeight(min_height)
#
#     def paintEvent(self, event):
#         """Draw the flight timelines."""
#         painter = QPainter(self)
#         painter.setRenderHint(QPainter.RenderHint.Antialiasing)
#         font = QFont("Arial", 12, QFont.Weight.Bold)
#         painter.setFont(font)
#         fm = QFontMetrics(font)
#
#         line_x_eta = 100
#         line_x_slot = 300
#         line_x_ata = 500
#
#         painter.setPen(QPen(Qt.GlobalColor.green, 1))
#         painter.drawLine(QPointF(line_x_eta, 0), QPointF(line_x_eta, self.height()))
#         painter.drawLine(QPointF(line_x_slot, 0), QPointF(line_x_slot, self.height()))
#         painter.drawLine(QPointF(line_x_ata, 0), QPointF(line_x_ata, self.height()))
#
#         top_margin = fm.height()
#
#         # Drawing thin white horizontal grid lines and centering the time labels
#         for i in range(0, int(self.height() / self.vertical_scale), self.grid_interval):
#             y = top_margin + i * self.vertical_scale
#             time_label = (self.earliest_time + timedelta(minutes=i * self.grid_interval)).strftime("%H:%M")
#             text_y = int(y - (fm.height() / 2) + fm.ascent())  # Adjust text position to be fully visible
#             painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
#             painter.drawLine(0, y, self.width(), y)
#             painter.setPen(Qt.GlobalColor.white)
#             painter.drawText(5, text_y, time_label)
#
#         for acid, timings in self.flights.items():
#             y_eta = top_margin + ((timings['ETA'] - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#             y_slot = top_margin + ((timings['Slot'] - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#             y_ata = top_margin + ((timings['ATA'] - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#
#             #print(f"Plotting: {acid} ETA: {y_eta}, SLOT: {y_slot}, ATA: {y_ata}")
#
#             painter.setPen(QPen(Qt.GlobalColor.green, 8))
#             painter.drawPoint(QPointF(line_x_eta, y_eta))
#             painter.drawPoint(QPointF(line_x_slot, y_slot))
#             painter.drawPoint(QPointF(line_x_ata, y_ata))
#
#             painter.setPen(QPen(Qt.GlobalColor.green, 1))
#             painter.drawLine(QPointF(line_x_eta, y_eta), QPointF(line_x_slot, y_slot))
#             painter.drawLine(QPointF(line_x_slot, y_slot), QPointF(line_x_ata, y_ata))
#
#             painter.setPen(QColor(255, 255, 255))
#             acid_text_y = y_ata + 5
#             acid_text_x = line_x_ata + 10
#             painter.drawText(QPointF(acid_text_x, acid_text_y), acid)
#
#
# class MainWindow(QWidget):
#     """
#     Main window for the AMAN Viewer.
#
#     Attributes:
#         data (dict): Contains aircraft identifiers, estimated times of arrival, arrival slots, and actual times of arrival.
#         header_widget (HeaderWidget): Widget displaying the header with labels.
#         scroll_area (QScrollArea): Scrollable area for the flight timeline.
#         timeline_widget (FlightTimelineWidget): Widget displaying the flight timeline.
#         timer (QTimer): Timer to update the scroll position.
#     """
#
#     def __init__(self, data):
#         """
#         Initialize the main window.
#
#         Args:
#             data (dict): Data for initializing the flight timeline.
#         """
#         super().__init__()
#         self.setWindowTitle("AMAN Viewer")  # Set the window title
#         self.setGeometry(0, 0, 500, 750)  # Set the geometry of the window
#
#         # Set up the main layout with no margins
#         layout = QVBoxLayout()
#         layout.setContentsMargins(0, 0, 0, 0)
#
#         # Initialize and add the header widget to the layout
#         self.header_widget = HeaderWidget(self)
#         layout.addWidget(self.header_widget)
#
#         # Initialize the scrollable timeline area
#         self.scroll_area = QScrollArea()
#         self.scroll_area.setWidgetResizable(True)
#
#         # Initialize and add the flight timeline widget to the scroll area
#         self.timeline_widget = FlightTimelineWidget(data)
#         self.scroll_area.setWidget(self.timeline_widget)
#         layout.addWidget(self.scroll_area)
#
#         # Set the main layout to the window
#         self.setLayout(layout)