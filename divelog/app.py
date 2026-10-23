"""Start the app: python -m divelog [--smoke-test]"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .settings import Settings, home_dir
from .store import AlreadyOpenError, Store
from .ui.main_window import MainWindow


def main(argv=None):
    argv = sys.argv if argv is None else argv
    smoke_test = '--smoke-test' in argv
    app = QApplication(argv)
    app.setApplicationName('Dive Logging')
    app.setOrganizationName('DFO MSEA')

    settings = Settings.load()
    try:
        store = Store(settings)
    except AlreadyOpenError:
        QMessageBox.warning(None, 'Dive Logging', 'The Dive Logging App is already running.')
        return 1
    window = MainWindow(store, settings)
    window.show()

    if not smoke_test:
        QTimer.singleShot(0, window.reopen_last_cruise)

    if smoke_test:
        # Used by the launcher tests: start, then report and quit
        def report():
            (home_dir() / 'smoke-test.txt').write_text(f'ok {settings.logs_path}\n', encoding='utf-8')
            app.quit()
        QTimer.singleShot(1500, report)
    else:
        QTimer.singleShot(0, window.prompt_first_update)

    code = app.exec()
    store.close()
    return code
