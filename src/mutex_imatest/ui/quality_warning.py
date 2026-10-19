"""One non-blocking sharpening warning per completed analysis/batch.

Call register only for a newly successful ``analyze`` job, never when opening
saved results. Call jobs_idle when the worker queue drains. Display changes and
channel switching therefore cannot create repeated warnings.
"""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox


def sharpening_evidence(result):
    """Return native halo / SFR evidence, excluding failed edge measurements."""
    summary = getattr(result, 'diagnostics_summary', {}).get('sharpening', {})
    halos = int(summary.get('halo_regions_ge_2pct', 0) or 0)
    halo_samples = int(summary.get('valid_halo_regions', 0) or 0)
    edges = [m for m in result.measurements if m.kind == 'edge' and m.valid and m.confidence > .05]
    boosted = sum('sharpening_or_ringing' in m.flags for m in edges)
    if not summary:
        from ..resolution import view_result
        rows = view_result(result, 'sharpening_halo_pct').measurements
        valid = [m for m in rows if m.valid and m.confidence > .05 and m.metric('sharpening_halo_pct') is not None]
        halo_samples = len(valid)
        halos = sum(m.metric('sharpening_halo_pct') >= 2 for m in valid)
    return {'detected': bool(halos or boosted), 'halo_regions': halos,
            'valid_halo_regions': halo_samples, 'sfr_regions': boosted,
            'supported': bool(halo_samples or edges)}


class SharpeningWarningController(QObject):
    warning_shown = Signal(object)

    def __init__(self, parent=None, language=None):
        super().__init__(parent)
        self.language = language
        self._seen = OrderedDict()
        self._pending = OrderedDict()
        self._shown = OrderedDict()
        self.dialog = None

    def register(self, result, uid, path=None):
        """Queue evidence for a successful new job; duplicate delivery is inert."""
        if not uid:
            return False
        path = str(path or result.image.original_path or result.image.path)
        identity = str(uid), path
        if identity in self._seen:
            return False
        self._seen[identity] = None
        if len(self._seen) > 2048:
            self._seen.popitem(last=False)
        evidence = sharpening_evidence(result)
        if not evidence['detected']:
            return False
        self._pending[identity] = {'path': path, **evidence}
        return True

    def discard_pending(self):
        """Explicitly cancelling a batch does not pop a completion warning."""
        self._pending.clear()

    def _english(self):
        if self.language is None:
            from .i18n import current_language
            language = current_language()
        else:
            language = self.language() if callable(self.language) else self.language
        return str(language).lower().startswith('en')

    def jobs_idle(self, *, _refresh=False):
        """Show one modeless summary once the current analysis batch finishes."""
        if _refresh:
            if self.dialog is None or not self._shown:return None
        else:
            if not self._pending:return None
            self._shown.update(self._pending)
            self._pending.clear()
        english = self._english()
        records = list(self._shown.values())
        filenames = list(dict.fromkeys(Path(item['path']).name for item in records))
        if self.dialog is None:
            box = QMessageBox(self.parent())
            box.setIcon(QMessageBox.Icon.Warning)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setWindowModality(Qt.WindowModality.NonModal)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.setTextFormat(Qt.TextFormat.PlainText)
            self.dialog = box

            def closed(_):
                self.dialog = None
                self._shown.clear()
            box.finished.connect(closed)
        box = self.dialog
        box.setWindowTitle('Sharpening / ringing detected' if english else '检测到锐化 / 振铃迹象')
        box.setText('Sharpening detected; measurement results may be unreliable.' if english
                    else '检测到锐化，测量结果可能不可靠。')
        if english:
            explanation = (f'{len(filenames)} image(s) contain measured halo or SFR-boost evidence. '
                           'These are signs of sharpening / ringing, not proof of processing history. '
                           'Inspect the halo map, native profiles and clipping flags before using resolution values.')
            detail = '\n'.join(f"{item['path']}\n  Halos ≥2%: {item['halo_regions']} / {item['valid_halo_regions']}; valid SFR boost regions: {item['sfr_regions']}"
                               for item in records)
        else:
            explanation = (f'{len(filenames)} 张图像检出实测光晕或 SFR 峰值增益。'
                           '这些是锐化 / 振铃迹象，不能证明图像的处理历史。'
                           '请结合光晕热力图、原像素剖面和剪切标志复核分辨率结果。')
            detail = '\n'.join(f"{item['path']}\n  ≥2% 光晕：{item['halo_regions']} / {item['valid_halo_regions']}；有效斜边峰值增益：{item['sfr_regions']}"
                               for item in records)
        box.setInformativeText(explanation)
        box.setDetailedText(detail)
        # QDialog.open() implicitly makes a dialog window-modal. show() keeps
        # this warning genuinely modeless, so image queues and tests continue.
        if not _refresh:
            box.show()
            box.raise_()
            self.warning_shown.emit(records)
        return box

    def retranslate(self):
        return self.jobs_idle(_refresh=True)

    flush = jobs_idle
