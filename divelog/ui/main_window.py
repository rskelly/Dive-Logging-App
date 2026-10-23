"""The main window: sidebar, pages and the toolbar actions."""

import gc
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..export import export_all
from ..lookups import describe_error, instrument_label, platform_label, update_lookups
from ..settings import DEFAULT_API_URL, Settings
from .cruises import CruisesPage
from .forms import DiveconfigForm, DiveForm, EquipconfigForm, TransectForm
from .pages import ChecksPage, LookupPage, TablePage, pilot_names

# Pages that show the current cruise's log, disabled while none is open
LOG_PAGES = {'Equipment configurations', 'Dive configurations', 'Dives', 'Transects', 'Checks'}


def _column(name, key=None):
    return name, (lambda r: r[key]) if key else None


class MainWindow(QMainWindow):
    def __init__(self, store, settings):
        super().__init__()
        self.store, self.settings = store, settings
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
                                          'Download people, instruments and platforms from the MSEA API')
        self.export_action = self._action(toolbar, 'Export', self.export, "Export the cruise's tables as CSV")
        toolbar.addSeparator()
        self._action(toolbar, 'Open log folder', self.open_log_folder)
        self._action(toolbar, 'Settings...', self.edit_settings)

        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        store.changed.connect(self._show_cruise)
        self._show_cruise()

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

        def equipment(r):
            if r['type'] == 'platform':
                names = {p['id']: platform_label(p) for p in store.lookups.platforms()}
                key = r['platform_id']
            else:
                names = {i['id']: instrument_label(i) for i in store.lookups.instruments()}
                key = r['instrument_id']
            return names.get(key, f'Unknown (ID {key})')

        c = _column
        return [
            ('Cruises', CruisesPage(store)),
            ('Personnel', LookupPage(store, 'Personnel', 'people')),
            ('Instruments', LookupPage(store, 'Instruments', 'instruments')),
            ('Platforms', LookupPage(store, 'Platforms', 'platforms')),
            ('Equipment configurations', TablePage(store, 'Instrument and platform configurations', 'equipconfig', [
                c('Name', 'name'), ('Equipment', equipment), c('Type', 'type'),
                c('Configuration', 'configuration'), c('Note', 'note')], EquipconfigForm)),
            ('Dive configurations', TablePage(store, 'Dive configurations', 'diveconfig', [
                c('Name', 'name'), c('Sub', 'sub_config'), c('Ship instruments', 'ship_instrument_configs'),
                c('Sub instruments', 'sub_instrument_configs'), c('Note', 'note')], DiveconfigForm)),
            ('Dives', TablePage(store, 'Dives', 'dives', [
                c('Name', 'name'), ('Pilot', pilots), c('Start time', 'start_time'), c('End time', 'end_time'),
                c('Site', 'site_name'), c('Dive config', 'dive_config'), c('Objective', 'objective'),
                c('Summary', 'summary'), c('Note', 'note')], DiveForm)),
            ('Transects', TablePage(store, 'Transects', 'transects', [
                c('Dive', 'dive_name'), c('Name', 'name'), c('Start time', 'start_time'), c('End time', 'end_time'),
                c('Objective', 'objective'), c('Summary', 'summary'), c('Note', 'note')], TransectForm)),
            ('Checks', ChecksPage(store)),
        ]

    def _show_cruise(self):
        """The current cruise in the title and status bar; log pages only while one is open."""
        cruise = self.store.cruise
        name = f"{cruise['name']} leg {cruise['leg']}" if cruise else None
        self.setWindowTitle(f'{name} - NDST Dive Logging App' if name else f'NDST Dive Logging App {__version__}')
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            enabled = cruise is not None or item.text() not in LOG_PAGES
            flags = item.flags()
            item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled if enabled else flags & ~Qt.ItemFlag.ItemIsEnabled)
        if cruise is None and self.nav.currentItem() and self.nav.currentItem().text() in LOG_PAGES:
            self.nav.setCurrentRow(0)
        self.export_action.setEnabled(cruise is not None)
        info = self.store.lookups.info()
        lookups = f"lookups updated {info['updated_on']}" if info else 'no lookups yet'
        where = f'{name}: {self.store.log.path}' if cruise else 'No cruise selected: create or select one in Cruises'
        self.status.setText(f'{where}  |  {lookups}')

    def show_page(self, label):
        for i in range(self.nav.count()):
            if self.nav.item(i).text() == label:
                self.nav.setCurrentRow(i)

    def reopen_last_cruise(self):
        """Open the cruise that was open when the app was last closed, and show its dives."""
        entry = self.settings.cruise(self.settings.current)
        if entry is not None and self.pages.widget(0).open(entry):
            self.show_page('Dives')

    # Lookups

    def prompt_first_update(self):
        """The lookups start empty and must be updated before use."""
        if self.store.lookups.info() is None:
            answer = QMessageBox.information(
                self, 'Update lookups',
                'The people, instruments and platforms have not been downloaded yet. Update the lookups '
                'while connected to the network before creating a cruise.\n\nUpdate them now?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.update_lookups()

    def update_lookups(self):
        """Replace the lookups with the API's, in the background. On failure the
        lookups are left as they were."""
        progress = QProgressDialog('Downloading people, instruments and platforms...', None, 0, 0, self)
        progress.setWindowTitle('Update lookups')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        self.update_action.setEnabled(False)
        api_url, proxy = self.settings.api_url, self.settings.proxy
        worker = _Worker(lambda: update_lookups(self.settings.lookups_path, api_url, proxy))
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
                                    f'The lookups could not be downloaded from {api_url}. '
                                    f'The existing lookups have not been changed.\n\n{describe_error(error)}')
            else:
                self.store.notify()
                QMessageBox.information(self, 'Lookups updated', f"Lookups updated: {counts['people']} people, "
                                        f"{counts['instruments']} instruments, {counts['platforms']} platforms.")
        worker.done.connect(done)
        progress.show()
        worker.start()
        self._worker = worker  # keep it alive until done

    # Files

    def export(self):
        if self.store.log is None:
            return
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

    def open_log_folder(self):
        """The current cruise's log folder, or the default log folder."""
        folder = self.store.log.path.parent if self.store.log else self.settings.logs_path
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        accepted = dialog.exec()
        new = dialog.values()
        dialog.deleteLater()
        if not accepted:
            return
        self.settings.api_url, self.settings.proxy = new['api_url'], new['proxy']
        # The default folder is saved as '' so it follows DIVELOG_HOME
        self.settings.logs_dir = '' if new['logs_dir'] in ('', str(Settings().logs_path)) else new['logs_dir']
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
        self.logs_dir = QLineEdit(str(settings.logs_path))
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._browse)
        folder = QWidget()
        row = QHBoxLayout(folder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.logs_dir, 1)
        row.addWidget(browse)

        form = QFormLayout()
        form.addRow('MSEA API URL', self.api_url)
        form.addRow('Proxy', self.proxy)
        form.addRow('Default log folder', folder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        note = QLabel('Lookups are downloaded from <API URL>/shared/people/, /rov/instruments/ and /rov/platforms/.\n'
                      'New cruises get their log in the default log folder. Existing logs stay where they are; '
                      'to move one, edit its cruise.')
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, 'Default log folder', self.logs_dir.text())
        if folder:
            self.logs_dir.setText(folder)

    def values(self):
        return {'api_url': self.api_url.text().strip().rstrip('/') or DEFAULT_API_URL,
                'proxy': self.proxy.text().strip(),
                'logs_dir': self.logs_dir.text().strip()}
