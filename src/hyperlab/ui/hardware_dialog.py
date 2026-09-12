"""Small explicit setup check; opening this dialog never opens hardware."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W

from hyperlab.connection_diagnostics import hardware_check
from hyperlab.paths import load_config, save_config


class HardwareSetupDialog(W.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Camera setup')
        self.resize(780, 560)
        self.future = None
        self.report = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        layout = W.QVBoxLayout(self)
        intro = W.QLabel('Install Balluff Impact Acquire x64 with USB3 Vision support on each computer. '
            'Connect camera uses the imaging USB interface; a controller COM port is not required for preview.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = W.QHBoxLayout()
        self.cti = W.QLineEdit(load_config().get('camera_cti', ''))
        self.cti.setObjectName('camera_cti')
        self.cti.setPlaceholderText('Automatic runtime discovery (leave empty)')
        row.addWidget(self.cti, 1)
        self.browse = W.QPushButton('Browse CTI…')
        self.browse.clicked.connect(self.choose_cti)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.check = W.QPushButton('Check this computer')
        self.check.setObjectName('check_hardware')
        self.check.clicked.connect(self.run_check)
        layout.addWidget(self.check)
        self.text = W.QPlainTextEdit('This check reads device properties and runtime signatures. '
            'It does not open a camera or serial port.\n\nChoose Check this computer to save a local diagnostic report.')
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        link = W.QLabel('<a href="https://assets.balluff.com/documents/DRF_957356_AA_000/Troubleshooting_Windows_USB3VisionDeviceIsNotShownOrCannotBeUsed.html">Official USB3 Vision driver setup</a>'
            ' · <a href="https://www.balluff.com/en-de/downloads/software">Balluff software downloads</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        buttons = W.QHBoxLayout()
        self.open_report = W.QPushButton('Open report folder')
        self.open_report.setEnabled(False)
        self.open_report.clicked.connect(self.show_report)
        buttons.addWidget(self.open_report)
        buttons.addStretch()
        self.close_button = W.QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def choose_cti(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Select installed Balluff x64 producer',
            self.cti.text(), 'GenTL producer (mvGenTLProducer.cti)')
        if path:
            self.cti.setText(path)

    def run_check(self):
        if self.future:
            return
        configured = self.cti.text().strip().strip('"')
        try:
            config = load_config()
            config['camera_cti'] = configured
            save_config(config)
        except Exception as error:
            self.text.setPlainText(f'Cannot save local runtime choice: {error}')
            return
        for widget in (self.cti, self.browse, self.check, self.close_button):
            widget.setEnabled(False)
        self.text.setPlainText('Checking current Windows devices, installed runtime and signatures…')
        self.future = self.executor.submit(hardware_check, cti=configured)
        self.timer.start()

    def poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            self.report = self.future.result()
            self.text.setPlainText(self.report['summary'])
            self.open_report.setEnabled(True)
        except Exception as error:
            self.text.setPlainText(f'Check failed: {type(error).__name__}: {error}')
        finally:
            self.future = None
            for widget in (self.cti, self.browse, self.check, self.close_button):
                widget.setEnabled(True)

    def show_report(self):
        if self.report:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(self.report['report_path']).parent)))

    def reject(self):
        if self.future:
            return
        self.executor.shutdown(wait=False)
        super().reject()
