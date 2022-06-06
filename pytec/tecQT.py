from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph.parametertree.parameterTypes as pTypes
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import numpy as np
import pyqtgraph as pg
from pytec.client import Client

rec_len = 1000
refresh_period = 20

TECparams = [ [    
    {'tag': 'report', 'type': 'parent', 'children': [
        {'tag': 'pid_engaged', 'type': 'bool', 'value': False},
    ]},
    {'tag': 'pwm', 'type': 'parent', 'children': [
        {'tag': 'max_i_pos', 'type': 'float', 'value': 0},
        {'tag': 'max_i_neg', 'type': 'float', 'value': 0},
        {'tag': 'max_v', 'type': 'float', 'value': 0},
        {'tag': 'i_set', 'type': 'float', 'value': 0},
    ]},
    {'tag': 'pid', 'type': 'parent', 'children': [
        {'tag': 'kp', 'type': 'float', 'value': 0},
        {'tag': 'ki', 'type': 'float', 'value': 0},
        {'tag': 'kd', 'type': 'float', 'value': 0},
        {'tag': 'output_min', 'type': 'float', 'value': 0},
        {'tag': 'output_max', 'type': 'float', 'value': 0},
    ]},
    {'tag': 's-h', 'type': 'parent', 'children': [
        {'tag': 't0', 'type': 'float', 'value': 0},
        {'tag': 'r0', 'type': 'float', 'value': 0},
        {'tag': 'b', 'type': 'float', 'value': 0},
    ]},
    {'tag': 'PIDtarget', 'type': 'parent', 'children': [
        {'tag': 'target', 'type': 'float', 'value': 0},
    ]},
] for _ in range(2)]


GUIparams = [[
    {'name': 'Disable Output', 'type': 'action', 'tip': 'Disable Output'},
    {'name': 'Constant Current', 'type': 'group', 'children': [
        {'name': 'Set Current', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (-3, 3), 'siPrefix': True, 'suffix': 'A'},
    ]},    
    {'name': 'Temperature PID', 'type': 'bool', 'value': False, 'children': [
        {'name': 'Set Temperature', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-273, 300), 'siPrefix': True, 'suffix': 'C'},
    ]},    
    {'name': 'Output Config', 'expanded': False, 'type': 'group', 'children': [
        {'name': 'Max Current', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (0, 3), 'siPrefix': True, 'suffix': 'A'},
        {'name': 'Max Voltage', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (0, 5), 'siPrefix': True, 'suffix': 'V'},
    ]},
    {'name': 'Thermistor Config', 'expanded': False,  'type': 'group', 'children': [
        {'name': 'T0', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-100, 100), 'siPrefix': True, 'suffix': 'C'},
        {'name': 'R0', 'type': 'float', 'value': 10000, 'step': 1, 'siPrefix': True, 'suffix': 'Ohm'},
        {'name': 'Beta', 'type': 'float', 'value': 3950, 'step': 1},
    ]},
    {'name': 'PID Config', 'expanded': False,  'type': 'group', 'children': [
        {'name': 'kP', 'type': 'float', 'value': 0, 'step': 0.1},
        {'name': 'kI', 'type': 'float', 'value': 0, 'step': 0.1},
        {'name': 'kD', 'type': 'float', 'value': 0, 'step': 0.1},
    ]},
    {'name': 'Save', 'type': 'action', 'tip': 'Save'},
] for _ in range(2)]

## If anything changes in the tree, print a message
def change(param, changes, ch):
    print("tree changes:")
    for param, change, data in changes:
        path = paramList[ch].childPath(param)
        if path is not None:
            childName = '.'.join(path)
        else:
            childName = param.name()
        print('  parameter: %s'% childName)
        print('  change:    %s'% change)
        print('  data:      %s'% str(data))
        print('  ----------')

        if (childName == 'Disable Output'):
            tec.set_param('pwm', ch, 'i_set', 0)
            paramList[ch].child('Constant Current').child('Set Current').setValue(0) 
            paramList[ch].child('Temperature PID').setValue(False)          

        if (childName == 'Temperature PID'):
            if (data):
                tec.set_param("pwm", ch, "pid")
            else:
                tec.set_param('pwm', ch, 'i_set', paramList[ch].child('Constant Current').child('Set Current').value())  
        
        if (childName == 'Constant Current.Set Current'):
            tec.set_param('pwm', ch, 'i_set', data)
            paramList[ch].child('Temperature PID').setValue(False)  

        if (childName == 'Temperature PID.Set Temperature'):
            tec.set_param('pid', ch, 'target', data)

        if (childName == 'Output Config.Max Current'):
            tec.set_param('pwm', ch, 'max_i_pos', data)
            tec.set_param('pwm', ch, 'max_i_neg', data)
            tec.set_param('pid', ch, 'output_min', -data)
            tec.set_param('pid', ch, 'output_max', data)

        if (childName == 'Output Config.Max Voltage'):
            tec.set_param('pwm', ch, 'max_v', data)

        if (childName == 'Thermistor Config.T0'):
            tec.set_param('s-h', ch, 't0', data)

        if (childName == 'Thermistor Config.R0'):
            tec.set_param('s-h', ch, 'r0', data)

        if (childName == 'Thermistor Config.Beta'):
            tec.set_param('s-h', ch, 'b', data)

        if (childName == 'PID Config.kP'):
            tec.set_param('pid', ch, 'kp', data)

        if (childName == 'PID Config.kI'):
            tec.set_param('pid', ch, 'ki', data)

        if (childName == 'PID Config.kD'):
            tec.set_param('pid', ch, 'kd', data)

        if (childName == 'Save'):
            tec.save_config()
        
def change0(param, changes):
    change(param, changes, 0)

def change1(param, changes):
    change(param, changes, 1)

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

def TECsync():
    global TECparams
    for channel in range(2):
        for parents in TECparams[channel]:
            if parents['tag'] == 'report':
                for data in tec.report_mode():
                    for children in parents['children']:
                        children['value'] = data[channel][children['tag']]
                    if quit:
                        break
            if parents['tag'] == 'pwm':
                for children in parents['children']:
                    children['value'] = tec.get_pwm()[channel][children['tag']]['value']
            if parents['tag'] == 'pid':
                for children in parents['children']:
                    children['value'] = tec.get_pid()[channel]['parameters'][children['tag']]
            if parents['tag'] == 's-h':
                for children in parents['children']:
                    children['value'] = tec.get_steinhart_hart()[channel]['params'][children['tag']]
            if parents['tag'] == 'PIDtarget':
                for children in parents['children']:
                    children['value'] = tec.get_pid()[channel]['target']
    
def refreshTreeParam(tempTree:dict, channel:int) -> dict:
    # tempTree['children']['Constant Current']['value'] = not TECparams[channel][0]['children'][0]['value']
    tempTree['children']['Constant Current']['children']['Set Current']['value'] = TECparams[channel][1]['children'][3]['value']
    tempTree['children']['Temperature PID']['value'] = TECparams[channel][0]['children'][0]['value']
    tempTree['children']['Temperature PID']['children']['Set Temperature']['value'] = TECparams[channel][4]['children'][0]['value']
    tempTree['children']['Output Config']['children']['Max Current']['value'] = TECparams[channel][1]['children'][0]['value']
    tempTree['children']['Output Config']['children']['Max Voltage']['value'] = TECparams[channel][1]['children'][2]['value']
    tempTree['children']['Thermistor Config']['children']['T0']['value'] = TECparams[channel][3]['children'][0]['value'] - 273.15
    tempTree['children']['Thermistor Config']['children']['R0']['value'] = TECparams[channel][3]['children'][1]['value']
    tempTree['children']['Thermistor Config']['children']['Beta']['value'] = TECparams[channel][3]['children'][2]['value']
    tempTree['children']['PID Config']['children']['kP']['value'] = TECparams[channel][2]['children'][0]['value']
    tempTree['children']['PID Config']['children']['kI']['value'] = TECparams[channel][2]['children'][1]['value']
    tempTree['children']['PID Config']['children']['kD']['value'] = TECparams[channel][2]['children'][2]['value']
    return tempTree

cnt = 0
def updateData():
    global cnt
    for data in tec.report_mode():

        ch0tempGraph.update(data, cnt)
        ch1tempGraph.update(data, cnt)
        ch0currentGraph.update(data, cnt)
        ch1currentGraph.update(data, cnt)
                
        if quit:
            break
    cnt += 1    
    

if __name__ == '__main__':
    tec = Client(host="192.168.1.26", port=23, timeout=None)

    app = pg.mkQApp()
    pg.setConfigOptions(antialias=True)
    mw = QtGui.QMainWindow()
    mw.setWindowTitle('Thermostat Control Panel')
    mw.resize(1920,1200)
    cw = QtGui.QWidget()
    mw.setCentralWidget(cw)
    l = QtGui.QVBoxLayout()
    layout = pg.LayoutWidget()
    l.addWidget(layout)
    cw.setLayout(l)

    ## Create tree of Parameter objects
    paramList = [Parameter.create(name='GUIparams', type='group', children=GUIparams[0]),
                 Parameter.create(name='GUIparams', type='group', children=GUIparams[1])]

    paramList[0].sigTreeStateChanged.connect(change0)
    print(paramList[0].children())
    ch0Tree = ParameterTree()
    ch0Tree.setParameters(paramList[0], showTop=False)

    paramList[1].sigTreeStateChanged.connect(change1)
    ch1Tree = ParameterTree()
    ch1Tree.setParameters(paramList[1], showTop=False)

    TECsync()
    paramList[0].restoreState(refreshTreeParam(paramList[0].saveState(), 0))
    paramList[1].restoreState(refreshTreeParam(paramList[1].saveState(), 1))

    layout.addWidget(ch0Tree, 1, 1, 1, 1)
    layout.addWidget(ch1Tree, 2, 1, 1, 1)

    ch0tempGraph = Graph(layout, 'Channel 0 Temperature', 1, 2, [Curves('Feedback', 'temperature', 0, 'r', rec_len, refresh_period)])
    ch1tempGraph = Graph(layout, 'Channel 1 Temperature', 2, 2, [Curves('Feedback', 'temperature', 1, 'r', rec_len, refresh_period)])
    ch0currentGraph = Graph(layout, 'Channel 0 Current', 1, 3, [Curves('Feedback', 'tec_i', 0, 'r', rec_len, refresh_period),
                                                                Curves('Setpoint', 'i_set', 0, 'g', rec_len, refresh_period)])
    ch1currentGraph = Graph(layout, 'Channel 1 Current', 2, 3, [Curves('Feedback', 'tec_i', 1, 'r', rec_len, refresh_period),
                                                                Curves('Setpoint', 'i_set', 1, 'g', rec_len, refresh_period)])

    t = QtCore.QTimer()
    t.timeout.connect(updateData)
    t.start(refresh_period)

    mw.show()

    pg.exec()