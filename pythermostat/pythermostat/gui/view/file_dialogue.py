from PyQt6 import QtWidgets
from PyQt6.QtCore import QTimer
from qasync import asyncSlot
from functools import wraps
import asyncio


class FileDialogue(QtWidgets.QFileDialog):
    def __init__(self):
        super().__init__()
    
    @asyncSlot(str, str, str)
    async def display_file_dialogue(self, title, default_path, suffix, file_mode=QtWidgets.QFileDialog.FileMode.ExistingFile, accept_mode=QtWidgets.QFileDialog.AcceptMode.AcceptOpen):
        self.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        self.setWindowTitle(title)
        self.setDirectory(default_path)
        self.setFileMode(file_mode)
        self.setAcceptMode(accept_mode)
        self.setNameFilter(suffix)

        future = asyncio.Future() # implemetation from qasync.asyncWrap
        def helper():
            try:
                if self.exec():
                    result = self.selectedFiles()[0]
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
        QTimer.singleShot(0, helper)

        return await future

