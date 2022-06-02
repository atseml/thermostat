from pyqtgraph.Qt import QtGui, QtCore
import numpy as np
import pyqtgraph as pg
from pytec.client import Client

rec_len = 1000
refresh_period = 20

channel_data = [{
    'adc': np.zeros(rec_len),
    'sens': np.zeros(rec_len),
    'temperature': np.zeros(rec_len),
    'i_set': np.zeros(rec_len),
    'pid_output': np.zeros(rec_len),
    'vref': np.zeros(rec_len),
    'dac_value': np.zeros(rec_len),
    'dac_feedback': np.zeros(rec_len),
    'i_tec': np.zeros(rec_len),
    'tec_i': np.zeros(rec_len),
    'tec_u_meas': np.zeros(rec_len),
    'interval': np.zeros(rec_len),
} for _ in range(2)]

tec = Client()

app = pg.mkQApp()
mw = QtGui.QMainWindow()
mw.setWindowTitle('Thermostat Control Panel')
mw.resize(800,800)
cw = QtGui.QWidget()
mw.setCentralWidget(cw)
l = QtGui.QVBoxLayout()
layout = pg.LayoutWidget()
l.addWidget(layout)
cw.setLayout(l)

pg.setConfigOptions(antialias=True)

temp0plot= pg.PlotWidget(title='Channel 0 Temperature')
layout.addWidget(temp0plot, 1, 1)
temp1plot = pg.PlotWidget(title='Channel 1 Temperature')
layout.addWidget(temp1plot, 2, 1)
current0plot = pg.PlotWidget(title='Channel 0 Current')
layout.addWidget(current0plot, 1, 2)
current1plot = pg.PlotWidget(title='Channel 1 Current')
layout.addWidget(current1plot, 2, 2)

temp0curve = pg.PlotCurveItem(pen=({'color': 'r', 'width': 1}))
temp1curve = pg.PlotCurveItem(pen=({'color': 'r', 'width': 1}))
tecI0curve = pg.PlotCurveItem(pen=({'color': 'r', 'width': 1}))
tecI1curve = pg.PlotCurveItem(pen=({'color': 'r', 'width': 1}))
Iset0curve = pg.PlotCurveItem(pen=({'color': 'g', 'width': 1}))
Iset1curve = pg.PlotCurveItem(pen=({'color': 'g', 'width': 1}))
temp0plot.addItem(temp0curve)
temp1plot.addItem(temp1curve)
current0plot.addItem(tecI0curve)
current0plot.addItem(Iset0curve)
current1plot.addItem(tecI1curve)
current1plot.addItem(Iset1curve)


cnt = 0
time_stamp = np.zeros(rec_len)
def update(n):
    for data in tec.report_mode():
        ch = data[n]        
        for tag, seq in channel_data[n].items():
            if tag in ch:
                v = ch[tag]
                if type(v) is float:
                    if cnt == 0:
                        np.copyto(seq, np.full(rec_len, v))
                    else:
                        seq[:-1] = seq[1:]        
                        seq[-1] = v        
        if quit:
            break
    return

def updateData():
    global cnt
    update(0)
    update(1)
    cnt += 1
    time_stamp[:-1] = time_stamp[1:]
    time_stamp[-1] = cnt * refresh_period / 1000
    temp0plot.setRange(xRange=[(cnt - rec_len) * refresh_period / 1000, cnt * refresh_period / 1000])
    temp1plot.setRange(xRange=[(cnt - rec_len) * refresh_period / 1000, cnt * refresh_period / 1000])  
    current0plot.setRange(xRange=[(cnt - rec_len) * refresh_period / 1000, cnt * refresh_period / 1000])
    current1plot.setRange(xRange=[(cnt - rec_len) * refresh_period / 1000, cnt * refresh_period / 1000])   
    temp0curve.setData(x = time_stamp, y = channel_data[0]['temperature'])
    temp1curve.setData(x = time_stamp, y = channel_data[1]['temperature'])
    tecI0curve.setData(x = time_stamp, y = channel_data[0]['tec_i'])
    tecI1curve.setData(x = time_stamp, y = channel_data[1]['tec_i'])
    Iset0curve.setData(x = time_stamp, y = channel_data[0]['i_set'])
    Iset1curve.setData(x = time_stamp, y = channel_data[1]['i_set'])
    

## Start a timer to rapidly update the plot in pw
t = QtCore.QTimer()
t.timeout.connect(updateData)
t.start(refresh_period)

mw.show()

if __name__ == '__main__':
    pg.exec()