#
#
# from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
# from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPalette
# from PyQt6.QtCore import Qt, QPointF, QTimer, QTime, QLine
# from datetime import datetime, timedelta
# import sys
# import math
#
# from bluesky import core, stack, network
# from bluesky.network.common import GROUPID_SIM
#
#
# def init_plugin():
#     aman_window = AMANWindow()
#
#     config = {
#         'plugin_name': 'AMANWINDOW',
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
#
#         super().__init__()
#
#         self.data = 0, 0, 0, 0, 0
#
#         self.airport = None
#         self.runway = None
#
#         self.app = None
#         self.main_window = None
#
#     def init_ui(self):
#         """Initialize the user interface and display the main window."""
#
#         acids, etas, arrival_slots, atas, delta_ts = self.data
#         print(acids, atas)
#         data = {
#             'acids': acids[self.airport][self.runway],
#             'etas': etas[self.airport][self.runway],
#             'arrival_slots': arrival_slots[self.airport][self.runway],
#             'atas': atas[self.airport][self.runway],
#             'delta_ts': delta_ts[self.airport][self.runway]
#         }
#         #print("data: ",data)
#         self.app = QApplication.instance() or QApplication(sys.argv)
#         self.main_window = MainWindow(data, self.airport, self.runway)
#         self.main_window.show()
#
#     @network.subscriber(topic='AMANINFO', to_group=GROUPID_SIM)
#     def on_aman_info_received(self, acids_allocated, ETAs, arrival_slots, ATAs, delta_ts):
#         """
#         Receive AMAN information and update the data.
#
#         Parameters:
#             acids_allocated (dict): Allocated aircraft IDs.
#             ETAs (list): Estimated times of arrival.
#             arrival_slots (list): Arrival slots.
#             ATAs (list): Actual times of arrival.
#         """
#         self.data = acids_allocated, ETAs, arrival_slots, ATAs, delta_ts
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
#             acids_allocated, ETAs, arrival_slots, atas, delta_ts = self.data
#
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
#     def __init__(self, parent=None):
#         """Initialize the HeaderWidget with default size and palette."""
#         super().__init__(parent)
#         self.setMinimumHeight(50)
#         self.setMinimumWidth(650)
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
#         line_x_delta_t = 575
#
#         # painter.drawText(QPointF(line_x_slot - fm.horizontalAdvance("SLOT"), 20),
#         #                f'{AMANWindow.airport}:{AMANWindow.runway}')
#
#
#         painter.drawText(QPointF(line_x_eta - fm.horizontalAdvance("ETA") / 2, 45), "ETA")
#         painter.drawText(QPointF(line_x_slot - fm.horizontalAdvance("SLOT") / 2, 45), "SLOT")
#         painter.drawText(QPointF(line_x_ata - fm.horizontalAdvance("ATA") / 2, 45), "ATA")
#         painter.drawText(QPointF(line_x_delta_t - 10, 20), "Delta T")
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
#         delta_ts = self.data['delta_ts']
#
#         earliest_time = None
#
#         latest_time = None
#
#         for i in range(len(acids)):
#             acid = acids[i]
#             eta = [value for key, value in etas.items()][i]
#             slot = arrival_slots[i]
#             ata = atas[i]
#
#             delta_t = delta_ts[acid]
#             dt_eta = datetime.fromtimestamp(eta, tz=None)
#             dt_slot = datetime.fromtimestamp(slot, tz=None)
#             dt_ata = datetime.fromtimestamp(ata, tz=None)
#
#             if earliest_time is None or dt_eta < earliest_time:
#                 earliest_time = dt_eta
#
#             if latest_time is None or dt_ata > latest_time:
#                 latest_time = dt_ata
#
#             if acid not in self.flights and eta > 0:
#                 self.flights[acid] = {'ETA': dt_eta,
#                                       'ATA': dt_ata,
#                                       'Slot': dt_slot,
#                                       'delta_t': delta_t}
#
#         self.earliest_time = earliest_time
#         self.latest_time = latest_time
#
#         #(f"Earliest Time: {self.earliest_time}")
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
#         min_height = self.findMaximumHeight() + 100
#         self.setMinimumHeight(min_height)
#
#     def findMaximumHeight(self):
#         max_time = None
#         for key, times in self.flights.items():
#             for time_key, time_value in times.items():
#                 if time_key != 'delta_t':
#                     if max_time is None or time_value > max_time:
#                         max_time = time_value
#
#         max_height = ((max_time - self.earliest_time).total_seconds() / 60)*self.vertical_scale
#         return int(max_height)
#
#     def paintEvent(self, event):
#         """Draw the flight timelines."""
#         painter = QPainter(self)
#         painter.setRenderHint(QPainter.RenderHint.Antialiasing)
#         font = QFont("Arial", 10, QFont.Weight.Light)
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
#
#         bottom_margin = self.findMaximumHeight() + 40
#         upper_value = math.ceil(self.findMaximumHeight() / self.vertical_scale / self.grid_interval) * self.grid_interval
#         index_list = list(range(0, upper_value + self.grid_interval, self.grid_interval))
#
#         for i in index_list:
#             y = bottom_margin - i * self.vertical_scale
#             time_label = (self.earliest_time + timedelta(minutes=i)).strftime("%H:%M")
#             delta_t_label = ''
#             # text_y = int(y - (fm.height() / 2) + fm.ascent())  # Adjust text position to be fully visible
#             text_y = int(y + (fm.height())//2 -2)
#             painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
#             painter.drawLine(0, y, self.width(), y)
#             painter.setPen(Qt.GlobalColor.white)
#             painter.drawText(5, text_y, time_label)
#             #print(f"y: {y}, text y: {text_y}, time_label: {time_label}, minheight: {self.minimumHeight()}")
#
#         for acid, timings in self.flights.items():
#             #print("Earliest Time: ", self.earliest_time)
#             eta = timings['ETA']
#             ata = timings['ATA']
#             slot = timings['Slot']
#
#             if ata == datetime.fromtimestamp(1, tz=None):
#                 use_dashed = True
#                 ata = slot
#             else:
#                 use_dashed = False
#
#             diff_test = (eta - ata).total_seconds()
#             # print(f"ACID: {acid}, eta: {eta},  ata: {ata},  diff: {diff_test}")
#             y_eta = bottom_margin - ((eta - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#             y_slot = bottom_margin - ((slot - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#             y_ata = bottom_margin - ((ata - self.earliest_time).total_seconds() / 60) * self.vertical_scale
#
#             print(f"eta: {y_eta}, slot: {y_slot}, ata: {y_ata}")
#
#             # Plotting the 3 times with a short line at their respective location
#             painter.setPen(QPen(Qt.GlobalColor.green, 3))
#             painter.drawLine(QPointF(line_x_eta - 4.0, y_eta), QPointF(line_x_eta + 4.0, y_eta))
#             painter.drawLine(QPointF(line_x_slot - 4.0, y_slot), QPointF(line_x_slot + 4.0, y_slot))
#
#             if use_dashed:
#                 painter.setPen(QPen(Qt.GlobalColor.gray, 3))
#             painter.drawLine(QPointF(line_x_ata - 4.0, y_ata), QPointF(line_x_ata + 4.0, y_ata))
#
#             # Plotting the 2 sets of connecting lines between eta and slot and then slot and ata
#             painter.setPen(QPen(Qt.GlobalColor.green, 1))
#             painter.drawLine(QPointF(line_x_eta, y_eta), QPointF(line_x_slot, y_slot))
#
#             # If the aircraft has not reached the dest yet, ATA does not exist yet, so use a dashed line
#             if use_dashed:
#                 painter.setPen(QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DashLine))
#
#             painter.drawLine(QPointF(line_x_slot, y_slot), QPointF(line_x_ata, y_ata))
#
#             # Adding the acids next to the plotted points
#             painter.setPen(QColor(255, 255, 255))
#             acid_text_x = line_x_ata + 10
#             acid_text_y = y_ata + fm.height()//2 - 2
#             painter.drawText(QPointF(acid_text_x, acid_text_y), acid)
#
#             delta_t_text_x = acid_text_x + 65
#             delta_t_text_y = acid_text_y
#             delta_t_text = str(int(timings['delta_t']))
#
#             if delta_t_text == "0":
#                 delta_t_text = ""
#
#             painter.setPen(QColor(128, 128, 128))
#             painter.drawText(QPointF(delta_t_text_x, delta_t_text_y), delta_t_text)
#
# class MainWindow(QWidget):
#     def __init__(self, data, airport, runway):
#         super().__init__()
#         self.setWindowTitle(F"AMAN:{airport}-{runway}")
#         self.setGeometry(0, 0, 600, 750)
#         layout = QVBoxLayout()
#         layout.setContentsMargins(0, 0, 0, 0)
#
#         # Header
#         self.header_widget = HeaderWidget(self)
#         layout.addWidget(self.header_widget)
#
#         # Scrollable timeline
#         self.scroll_area = QScrollArea()
#         self.scroll_area.setWidgetResizable(True)
#         self.timeline_widget = FlightTimelineWidget(data)
#         self.scroll_area.setWidget(self.timeline_widget)
#         layout.addWidget(self.scroll_area)
#
#         self.setLayout(layout)
