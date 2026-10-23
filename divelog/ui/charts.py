"""Small charts for the Checks page, drawn with QPainter so the app needs no
plotting library (only PySide6-Essentials)."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

DIVE_COLOR = QColor('#605CA8')
TRANSECT_COLOR = QColor('#00A65A')
PILOT_COLOR = QColor('#3C8DBC')
ROW_HEIGHT = 26


def nice_ticks(maximum, count=5):
    """Round tick values from 0 to at least maximum."""
    if maximum <= 0:
        return [0, 1]
    raw = maximum / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    return [i * step for i in range(math.ceil(maximum / step - 1e-9) + 1)]


def _tick_label(value):
    return f'{value:g}'


class _Chart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _rows(self):
        return 0

    def _set_height(self):
        # One row per item, plus room for the axis
        self.setFixedHeight(max(120, self._rows() * ROW_HEIGHT + 50))
        self.update()

    def _text_color(self):
        return self.palette().text().color()

    def _empty(self, painter):
        painter.setPen(self._text_color())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'No data')


class BarChart(_Chart):
    """Horizontal bars: one per (label, value)."""

    def __init__(self, x_label, color, parent=None):
        super().__init__(parent)
        self.x_label = x_label
        self.color = color
        self.items = []
        self._set_height()

    def _rows(self):
        return len(self.items)

    def set_data(self, items):
        self.items = [(label, value) for label, value in items if value is not None]
        self._set_height()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.items:
            return self._empty(painter)
        fm = painter.fontMetrics()
        text = self._text_color()
        grid = QColor(text)
        grid.setAlpha(40)

        label_w = min(max(fm.horizontalAdvance(label) for label, _ in self.items) + 10, self.width() * 0.4)
        plot = QRectF(label_w, 8, self.width() - label_w - 16, len(self.items) * ROW_HEIGHT)
        ticks = nice_ticks(max(max(v for _, v in self.items), 0))
        scale = plot.width() / ticks[-1]

        for t in ticks:
            x = plot.left() + t * scale
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(text)
            painter.drawText(QRectF(x - 40, plot.bottom() + 2, 80, fm.height()), Qt.AlignmentFlag.AlignHCenter, _tick_label(t))
        painter.drawText(QRectF(plot.left(), plot.bottom() + fm.height() + 4, plot.width(), fm.height()),
                         Qt.AlignmentFlag.AlignHCenter, self.x_label)

        for i, (label, value) in enumerate(self.items):
            y = plot.top() + i * ROW_HEIGHT
            painter.setPen(text)
            painter.drawText(QRectF(0, y, label_w - 8, ROW_HEIGHT),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             fm.elidedText(label, Qt.TextElideMode.ElideRight, int(label_w - 8)))
            painter.fillRect(QRectF(plot.left(), y + 4, max(value, 0) * scale, ROW_HEIGHT - 8), self.color)


class TimelineChart(_Chart):
    """One row per dive, each on its own time scale: the dive as a bar, its
    transects' starts (down triangles) and ends (up triangles) as markers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dives = []
        self._set_height()

    def _rows(self):
        return len(self.dives)

    def set_data(self, dives):
        """dives: [(name, start, end, [(transect start, transect end)])] with datetimes."""
        self.dives = [d for d in dives if d[1] and d[2]]
        self._set_height()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.dives:
            return self._empty(painter)
        fm = painter.fontMetrics()
        text = self._text_color()
        time_w = fm.horizontalAdvance('00:00') + 6
        label_w = min(max(fm.horizontalAdvance(d[0]) for d in self.dives) + 10, self.width() * 0.35)
        left, right = label_w + time_w, self.width() - time_w - 8

        for i, (name, start, end, transects) in enumerate(self.dives):
            y = 8 + i * ROW_HEIGHT
            mid = y + ROW_HEIGHT / 2
            times = [start, end] + [t for pair in transects for t in pair if t]
            t0, t1 = min(times), max(times)
            span = (t1 - t0).total_seconds() or 1

            def x(t, t0=t0, span=span):
                return left + (t - t0).total_seconds() / span * (right - left)

            painter.setPen(text)
            painter.drawText(QRectF(0, y, label_w - 8, ROW_HEIGHT),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             fm.elidedText(name, Qt.TextElideMode.ElideRight, int(label_w - 8)))
            painter.drawText(QRectF(label_w, y, time_w - 4, ROW_HEIGHT),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, t0.strftime('%H:%M'))
            painter.drawText(QRectF(right + 4, y, time_w, ROW_HEIGHT),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t1.strftime('%H:%M'))
            painter.fillRect(QRectF(x(start), mid - 2, max(x(end) - x(start), 1), 4), DIVE_COLOR)

            painter.setPen(QPen(text, 1))
            painter.setBrush(TRANSECT_COLOR)
            for t_start, t_end in transects:
                if t_start:
                    px = x(t_start)
                    painter.drawPolygon(QPolygonF([QPointF(px - 5, mid - 11), QPointF(px + 5, mid - 11), QPointF(px, mid - 3)]))
                if t_end:
                    px = x(t_end)
                    painter.drawPolygon(QPolygonF([QPointF(px - 5, mid + 11), QPointF(px + 5, mid + 11), QPointF(px, mid + 3)]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
