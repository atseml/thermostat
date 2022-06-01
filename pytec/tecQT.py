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
    'temp_set': np.zeros(rec_len),
} for _ in range(2)]

tec = Client()

app = pg.mkQApp()
mw = QtGui.QMainWindow()
mw.setWindowTitle('Thermostat Control Panel')
mw.resize(800,800)
cw = QtGui.QWidget()
mw.setCentralWidget(cw)
l = QtGui.QVBoxLayout()
cw.setLayout(l)

pg.setConfigOptions(antialias=True)

pw0= pg.PlotWidget(name='Channel 0')
l.addWidget(pw0)
pw1 = pg.PlotWidget(name='Channel 1')
l.addWidget(pw1)

curve0 = pw0.plot()
curve1 = pw1.plot()

cnt = 0
time_stamp = np.zeros(rec_len)
def update(n):
    global cnt
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
    pw0.setRange(xRange=[cnt * refresh_period / 1000 - 20.0, cnt * refresh_period / 1000])
    pw1.setRange(xRange=[cnt * refresh_period / 1000 - 20.0, cnt * refresh_period / 1000])    
    curve0.setData(x = time_stamp, y = channel_data[0]['temperature'])
    curve1.setData(x = time_stamp, y = channel_data[1]['temperature'])
    

## Start a timer to rapidly update the plot in pw
t = QtCore.QTimer()
t.timeout.connect(updateData)
t.start(refresh_period)

mw.show()

if __name__ == '__main__':
    pg.exec()