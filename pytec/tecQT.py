from pyqtgraph.Qt import QtGui, QtCore
import numpy as np
import pyqtgraph as pg
from pytec.client import Client

tec = Client(host="192.168.1.26", port=23, timeout=None)

rec_len = 1000
refresh_period = 20

class Curves:
    def __init__(self, legend: str, key: str, channel: int, color: str, buffer_len: int, period: int):
        self.curveItem = pg.PlotCurveItem(pen=({'color': color, 'width': 1}))
        self.legendStr = legend
        self.keyStr = key
        self.channel = channel
        self.data_buf = np.zeros(buffer_len)
        self.time_stamp = np.zeros(buffer_len)
        self.buffLen = buffer_len
        self.period = period
    
    def update(self, tec_data, cnt):
        if cnt == 0:
            np.copyto(self.data_buf, np.full(self.buffLen, tec_data[self.channel][self.keyStr]))
        else: 
            self.data_buf[:-1] = self.data_buf[1:]
            self.data_buf[-1] = tec_data[self.channel][self.keyStr]
            self.time_stamp[:-1] = self.time_stamp[1:]
            self.time_stamp[-1] = cnt * self.period / 1000
            self.curveItem.setData(x = self.time_stamp, y = self.data_buf)

class Graph:
    def __init__(self, parent: pg.LayoutWidget, title: str, row: int, col: int, curves: list[Curves]):
        self.plotItem = pg.PlotWidget(title=title)
        self.legendItem = pg.LegendItem(offset=(75, 30), brush=(50,50,200,150))
        self.legendItem.setParentItem(self.plotItem.getPlotItem())
        parent.addWidget(self.plotItem, row, col)
        self.curves = curves
        for curve in self.curves:
            self.plotItem.addItem(curve.curveItem)
            self.legendItem.addItem(curve.curveItem, curve.legendStr)

    def update(self, tec_data, cnt):
        for curve in self.curves:
            curve.update(tec_data, cnt)
        self.plotItem.setRange(xRange=[(cnt - self.curves[0].buffLen) * self.curves[0].period / 1000, cnt * self.curves[0].period / 1000])

app = pg.mkQApp()
mw = QtGui.QMainWindow()
mw.setWindowTitle('Thermostat Control Panel')
mw.resize(1500,800)
cw = QtGui.QWidget()
mw.setCentralWidget(cw)
l = QtGui.QVBoxLayout()
layout = pg.LayoutWidget()
l.addWidget(layout)
cw.setLayout(l)

pg.setConfigOptions(antialias=True)

ch0tempGraph = Graph(layout, 'Channel 0 Temperature', 1, 2, [Curves('Feedback', 'temperature', 0, 'r', rec_len, refresh_period)])
ch1tempGraph = Graph(layout, 'Channel 1 Temperature', 2, 2, [Curves('Feedback', 'temperature', 1, 'r', rec_len, refresh_period)])
ch0currentGraph = Graph(layout, 'Channel 0 Current', 1, 3, [Curves('Feedback', 'tec_i', 0, 'r', rec_len, refresh_period),
                                                            Curves('Setpoint', 'i_set', 0, 'g', rec_len, refresh_period)])
ch1currentGraph = Graph(layout, 'Channel 1 Current', 2, 3, [Curves('Feedback', 'tec_i', 1, 'r', rec_len, refresh_period),
                                                            Curves('Setpoint', 'i_set', 1, 'g', rec_len, refresh_period)])
ch0voltGraph = Graph(layout, 'Channel 0 Voltage', 1, 4, [Curves('Feedback', 'tec_u_meas', 0, 'r', rec_len, refresh_period)])
ch1voltGraph = Graph(layout, 'Channel 1 Voltage', 2, 4, [Curves('Feedback', 'tec_u_meas', 1, 'r', rec_len, refresh_period)])

cnt = 0
def updateData():
    global cnt
    for data in tec.report_mode():

        ch0tempGraph.update(data, cnt)
        ch1tempGraph.update(data, cnt)
        ch0currentGraph.update(data, cnt)
        ch1currentGraph.update(data, cnt)
        ch0voltGraph.update(data, cnt)
        ch1voltGraph.update(data, cnt)
                
        if quit:
            break
    cnt += 1    
    
t = QtCore.QTimer()
t.timeout.connect(updateData)
t.start(refresh_period)

mw.show()

if __name__ == '__main__':
    pg.exec()