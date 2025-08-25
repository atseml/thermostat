from PyQt6 import QtWidgets
from PyQt6.QtCore import pyqtSlot, QTimer
from qasync import asyncSlot
from functools import wraps
import asyncio

class InfoBox(QtWidgets.QMessageBox):
    def __init__(self):
        super().__init__()
        self.setIcon(QtWidgets.QMessageBox.Icon.Information)

    @pyqtSlot(str, str)
    def display_info_box(self, title, text):
        self.setWindowTitle(title)
        self.setText(text)
        self.show()


class QuestionBox(QtWidgets.QMessageBox): #TODO: Make Generic
    def __init__(self):
        super().__init__()
        self.setIcon(QtWidgets.QMessageBox.Icon.Question)

    @asyncSlot(str, str)
    async def display_question_box(self, title, text):
        self.setWindowTitle(title)
        self.setText(text)
        self.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        self.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)

        future = asyncio.Future() # implemetation from qasync.asyncWrap
        def helper():
            try:
                result = self.exec()
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
        QTimer.singleShot(0, helper)

        return (await future == QtWidgets.QMessageBox.StandardButton.Yes)


class WarningBox(QtWidgets.QMessageBox):
    def __init__(self):
        super().__init__()
        self.setIcon(QtWidgets.QMessageBox.Icon.Warning)

    @pyqtSlot(str, str)
    def display_warning_box(self, title, text, detail_text):
        self.setWindowTitle(title)
        self.setText(text)
        self.setDetailedText(detail_text)
        self.show()