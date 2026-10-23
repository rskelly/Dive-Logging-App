"""The main window: sidebar, pages and the toolbar actions."""

import gc
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..db import OldLogError
from ..export import export_all
from ..lookups import describe_error, instrument_label, update_lookups
from ..settings import DEFAULT_API_URL, Settings
from ..store import AlreadyOpenError, set_aside
from .forms import CruiseForm, DiveconfigForm, DiveForm, EquipconfigForm, TransectForm
from .pages import ChecksPage, LookupPage, TablePage, pilot_names


def _column(name, key=None):
    return name, (lambda r: r[key]) if key else None


class MainWindow(QMainWindow):
    def __init__(self, store, settings):
        super().__init__()
        self.store, self.settings = store, settings
        self.setWindowTitle(f'NDST Dive Logging App {__version__}')
        self.resize(1200, 760)

        self.nav = QListWidget()
        self.nav.setMaximumWidth(230)
        self.pages = QStackedWidget()
        for label, page in self._pages():
            self.nav.addItem(label)
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        splitter = QSplitter()
        splitter.addWidget(self.nav)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        toolbar = self.addToolBar('Actions')
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.update_action = self._action(toolbar, 'Update lookups', self.update_lookups,
                                          'Download people and instruments from the MSEA API')
        self._action(toolbar, 'Export', self.export, 'Export all tables as CSV')
        toolbar.addSeparator()
        self._action(toolbar, 'Open data folder', self.open_data_folder)
        self._action(toolbar, 'New survey...', self.new_survey, 'Set the current log aside and start a new one')
        self._action(toolbar, 'Settings...', self.edit_settings)

        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        store.changed.connect(self._show_status)
        self._show_status()

    def _action(self, toolbar, text, slot, tip=None):
        action = QAction(text, self)
        action.triggered.connect(slot)
        if tip:
            action.setToolTip(tip)
        toolbar.addAction(action)
        return action

    def _pages(self):
        store = self.store

        def pilots(r):
            names = {str(p['id']): f"{p['first_name']} {p['last_name']}" for p in store.lookups.people()}
            return pilot_names(r['pilot'], names)

        def instrument(r):
            names = {i['id']: instrument_label(i) for i in store.lookups.instruments()}
            return names.get(r['instrument_id'], f"Unknown (ID {r['instrument_id']})")

        c = _column
        return [
            ('Cruise', TablePage(store, 'Cruise', 'cruise', [
                c('Name', 'name'), c('Leg', 'leg'), c('Objective', 'objective'), c('Summary', 'summary'),
                c('Note', 'note')], CruiseForm)),
            ('Personnel', LookupPage(store, 'Personnel', 'people')),
            ('Instruments', LookupPage(store, 'Instruments', 'instruments')),
            ('Equipment configurations', TablePage(store, 'Instrument and platform configurations', 'equipconfig', [
                c('Name', 'name'), ('Instrument', instrument), c('Type', 'type'),
                c('Configuration', 'configuration'), c('Note', 'note')], EquipconfigForm)),
            ('Dive configurations', TablePage(store, 'Dive configurations', 'diveconfig', [
                c('Name', 'name'), c('Ship', 'ship_config'), c('Sub', 'sub_config'),
                c('Ship instruments', 'ship_instrument_configs'), c('Sub instruments', 'sub_instrument_configs'),
                c('Note', 'note')], DiveconfigForm)),
            ('Dives', TablePage(store, 'Dives', 'dives', [
                c('Cruise', 'cruise_name'), c('Leg', 'leg'), c('Name', 'name'), ('Pilot', pilots),
                c('Start time', 'start_time'), c('End time', 'end_time'), c('Site', 'site_name'),
                c('Dive config', 'dive_config'), c('Objective', 'objective'), c('Summary', 'summary'),
                c('Note', 'note')], DiveForm)),
            ('Transects', TablePage(store, 'Transects', 'transects', [
                c('Cruise', 'cruise_name'), c('Leg', 'leg'), c('Dive', 'dive_name'), c('Name', 'name'),
                c('Start time', 'start_time'), c('End time', 'end_time'), c('Objective', 'objective'),
                c('Summary', 'summary'), c('Note', 'note')], TransectForm)),
            ('Checks', ChecksPage(store)),
        ]

    def _show_status(self):
        info = self.store.lookups.info()
        lookups = f"lookups updated {info['updated_on']}" if info else 'no lookups yet'
        self.status.setText(f'Log: {self.store.log_path}  |  {lookups}')

    # Lookups

    def prompt_first_update(self):
        """The lookups start empty and must be updated before use."""
        if self.store.lookups.info() is None:
            answer = QMessageBox.information(
                self, 'Update lookups',
                'The people and instruments have not been downloaded yet. Update the lookups '
                'while connected to the network before logging dives.\n\nUpdate them now?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.update_lookups()

    def update_lookups(self):
        """Replace the people and instruments with the API's, in the background.
        On failure the lookups are left as they were."""
        progress = QProgressDialog('Downloading people and instruments...', None, 0, 0, self)
        progress.setWindowTitle('Update lookups')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        self.update_action.setEnabled(False)
        api_url, proxy = self.settings.api_url, self.settings.proxy
        worker = _Worker(lambda: update_lookups(self.store.lookups_path, api_url, proxy))
        # Python's cyclic garbage collector can run in any thread. If it ran in
        # the worker it could destroy unused Qt widgets there, which crashes Qt;
        # so collect now, on the GUI thread, and pause it until the worker is done.
        gc.collect()
        gc.disable()

        def done(counts, error):
            gc.enable()
            progress.close()
            progress.deleteLater()
            self.update_action.setEnabled(True)
            if error is not None:
                QMessageBox.warning(self, 'Lookups not updated',
                                    f'The people and instruments could not be downloaded from {api_url}. '
                                    f'The existing lookups have not been changed.\n\n{describe_error(error)}')
            else:
                self.store.notify()
                QMessageBox.information(self, 'Lookups updated', f"Lookups updated: {counts['people']} people, "
                                                                 f"{counts['instruments']} instruments.")
        worker.done.connect(done)
        progress.show()
        worker.start()
        self._worker = worker  # keep it alive until done

    # Files

    def export(self):
        try:
            folder = export_all(self.store.log, self.store.lookups, self.store.export_path)
        except OSError as e:
            QMessageBox.warning(self, 'Export failed', f'The tables could not be exported.\n\n{e}')
            return
        box = QMessageBox(QMessageBox.Icon.Information, 'Exported', f'All tables were exported to\n{folder}', parent=self)
        open_button = box.addButton('Open folder', QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        box.deleteLater()

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_path)))

    def new_survey(self):
        cruises = self.store.log.rows('cruise')
        cruise = cruises[0]['name'] if cruises else None
        answer = QMessageBox.question(
            self, 'New survey', 'Set the current log aside and start a new, empty one?\n\n'
            'The current log is renamed, not deleted. Export it first if you need the CSV files.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        path = self.store.log_path
        self.store.close(keep_lock=True)
        try:
            target = set_aside(path, cruise)
        except OSError as e:
            QMessageBox.warning(self, 'New survey', f'The log could not be renamed.\n\n{e}')
            target = None
        self.store.open(self.store.data_path)
        if target:
            QMessageBox.information(self, 'New survey', f'The previous log was saved as\n{target}')

    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        accepted = dialog.exec()
        new = dialog.values()
        dialog.deleteLater()
        if not accepted:
            return
        target = Path(new['data_dir']) if new['data_dir'] else Settings().data_path
        if target.resolve() != self.store.data_path.resolve():
            try:
                self.store.open(target)
            except AlreadyOpenError:
                QMessageBox.warning(self, 'Settings', f'Another copy of the app is using {target}.')
                return
            except (OldLogError, OSError) as e:
                QMessageBox.warning(self, 'Settings', f'The log in {target} could not be opened.\n\n{e}')
                return
        # The default folder is saved as '' so it follows DIVELOG_HOME
        self.settings.data_dir = '' if target.resolve() == Settings().data_path.resolve() else str(target)
        self.settings.api_url, self.settings.proxy = new['api_url'], new['proxy']
        self.settings.save()


class _Worker(QObject):
    """Run a function in a background thread; done(result, error) arrives in the GUI thread."""
    done = Signal(object, object)

    def __init__(self, function):
        super().__init__()
        self.function = function

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.done.emit(self.function(), None)
        except Exception as e:  # reported to the user
            self.done.emit(None, e)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(560)
        self.api_url = QLineEdit(settings.api_url)
        self.proxy = QLineEdit(settings.proxy)
        self.proxy.setPlaceholderText('Use the system settings')
        self.data_dir = QLineEdit(str(settings.data_path))
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._browse)
        folder = QWidget()
        row = QHBoxLayout(folder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.data_dir, 1)
        row.addWidget(browse)

        form = QFormLayout()
        form.addRow('MSEA API URL', self.api_url)
        form.addRow('Proxy', self.proxy)
        form.addRow('Data folder', folder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel('Lookups are downloaded from <API URL>/shared/people/ and /rov/instruments/.\n'
                                'The data folder holds the log, the lookups and the exports.'))
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, 'Data folder', self.data_dir.text())
        if folder:
            self.data_dir.setText(folder)

    def values(self):
        return {'api_url': self.api_url.text().strip().rstrip('/') or DEFAULT_API_URL,
                'proxy': self.proxy.text().strip(),
                'data_dir': self.data_dir.text().strip()}
