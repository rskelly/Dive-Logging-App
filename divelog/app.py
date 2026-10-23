"""Start the app: python -m divelog [--smoke-test]"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .db import OldLogError
from .settings import Settings, home_dir
from .store import AlreadyOpenError, Store, set_aside
from .ui.main_window import MainWindow


def open_store(settings):
    """Open the data folder, offering to set aside an old-format log. None if the user gives up."""
    path = settings.data_path
    while True:
        try:
            return Store(path)
        except AlreadyOpenError:
            QMessageBox.warning(None, 'Dive Logging', f'The Dive Logging App is already running with the data in\n{path}')
            return None
        except OldLogError as e:
            answer = QMessageBox.question(
                None, 'Dive Logging', f'{e}\n\nRename it and start a new, empty log? The old file is kept.')
            if answer != QMessageBox.StandardButton.Yes:
                return None
            set_aside(path / 'divelogging-db.sqlite', 'old-format')


def main(argv=None):
    argv = sys.argv if argv is None else argv
    smoke_test = '--smoke-test' in argv
    app = QApplication(argv)
    app.setApplicationName('Dive Logging')
    app.setOrganizationName('DFO MSEA')

    settings = Settings.load()
    store = open_store(settings)
    if store is None:
        return 1
    window = MainWindow(store, settings)
    window.show()

    if smoke_test:
        # Used by the launcher tests: start, then report and quit
        def report():
            (home_dir() / 'smoke-test.txt').write_text(f'ok {store.log_path}\n', encoding='utf-8')
            app.quit()
        QTimer.singleShot(1500, report)
    else:
        QTimer.singleShot(0, window.prompt_first_update)

    code = app.exec()
    store.close()
    return code
