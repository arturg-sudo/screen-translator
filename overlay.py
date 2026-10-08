import sys
from typing import List, Optional, Tuple
from PyQt6.QtCore import Qt, QRect, QPoint, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
)
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QFont,
    QFontMetrics,
    QCursor,
    QImage,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QKeySequence,
)
from PIL import Image

from ocr_engine import run_ocr, OcrBlock
from translator import translate_texts
from language_palette import LanguagePalette


class TranslatedItem:
    def __init__(
        self,
        block: OcrBlock,
        translated_text: str,
        rect_logical: QRect,
        card_rect: QRect,
        font: QFont,
        bg_color: QColor,
        fg_color: QColor,
    ):
        self.block = block
        self.translated_text = translated_text
        self.rect_logical = rect_logical
        self.card_rect = card_rect
        self.font = font
        self.bg_color = bg_color
        self.fg_color = fg_color


class WorkerThread(QThread):
    finished_data = pyqtSignal(list, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, pil_image: Image.Image, sel_rect: QRect, dpr: float, source_lang: str, target_lang: str):
        super().__init__()
        self.pil_image = pil_image
        self.sel_rect = sel_rect
        self.dpr = dpr
        self.source_lang = source_lang
        self.target_lang = target_lang

    def run(self):
        try:
            # 1. OCR with cluster line merging
            blocks = run_ocr(self.pil_image, source_lang=self.source_lang)
            if not blocks:
                self.finished_data.emit([], "")
                return

            # 2. Batch translate whole sentences
            orig_texts = [b.original_text for b in blocks]
            translations = translate_texts(orig_texts, target_lang=self.target_lang, source_lang=self.source_lang)

            items = []
            for b, trans in zip(blocks, translations):
                # Map physical box coordinates inside crop to logical widget coordinates
                lx = int(self.sel_rect.x() + b.x / self.dpr)
                ly = int(self.sel_rect.y() + b.y / self.dpr)
                lw = int(b.width / self.dpr)
                lh = int(b.height / self.dpr)
                rect_logical = QRect(lx, ly, lw, lh)

                # Determine readable font size & calculate needed width
                target_h = lh
                fsize = max(8, int(target_h * 0.72))
                font = QFont("Segoe UI", fsize, QFont.Weight.Medium)
                fm = QFontMetrics(font)

                # Fit font size to original width if possible
                while fsize > 7 and fm.horizontalAdvance(trans) > (lw - 4):
                    fsize -= 1
                    font.setPointSize(fsize)
                    fm = QFontMetrics(font)

                # Calculate card width & height (padded)
                text_w = fm.horizontalAdvance(trans)
                card_w = max(lw + 4, text_w + 10)
                card_h = max(lh + 2, fm.height() + 4)

                # Keep card aligned with original line
                cx = rect_logical.center().x()
                cy = rect_logical.center().y()
                card_rect = QRect(cx - card_w // 2, cy - card_h // 2, card_w, card_h)

                bg_color = QColor(b.bg_color[0], b.bg_color[1], b.bg_color[2])
                fg_color = QColor(b.text_color[0], b.text_color[1], b.text_color[2])

                item = TranslatedItem(
                    block=b,
                    translated_text=trans,
                    rect_logical=rect_logical,
                    card_rect=card_rect,
                    font=font,
                    bg_color=bg_color,
                    fg_color=fg_color,
                )
                items.append(item)

            full_text = "\n".join(translations)
            self.finished_data.emit(items, full_text)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ReTranslateWorker(QThread):
    finished_translations = pyqtSignal(list)

    def __init__(self, texts: List[str], target_lang: str, source_lang: str = "auto"):
        super().__init__()
        self.texts = texts
        self.target_lang = target_lang
        self.source_lang = source_lang

    def run(self):
        try:
            res = translate_texts(self.texts, target_lang=self.target_lang, source_lang=self.source_lang)
            self.finished_translations.emit(res)
        except Exception:
            self.finished_translations.emit([])


class ScreenTranslatorOverlay(QWidget):
    closed = pyqtSignal()

    STATE_IDLE = 0
    STATE_DRAGGING = 1
    STATE_PROCESSING = 2
    STATE_RESULT = 3

    def __init__(self, target_lang: str = "ru", source_lang: str = "auto"):
        super().__init__()
        self.target_lang = target_lang
        self.source_lang = source_lang

        # Detect active screen & grab full screenshot
        cursor_pos = QCursor.pos()
        self.screen_obj = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        self.dpr = self.screen_obj.devicePixelRatio()
        self.screen_geo = self.screen_obj.geometry()
        self.pixmap = self.screen_obj.grabWindow(0)

        # Window properties
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setGeometry(self.screen_geo)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Interaction state
        self.state = self.STATE_IDLE
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self.selected_rect = QRect()

        self.translated_items: List[TranslatedItem] = []
        self.show_original = False
        self.toast_message = ""
        self.toast_timer = QTimer(self)
        self.toast_timer.timeout.connect(self._hide_toast)

        self.worker: Optional[WorkerThread] = None
        self.retranslate_worker: Optional[ReTranslateWorker] = None

        # Text selection state across multiple lines
        self.sel_start_line = -1
        self.sel_start_char = -1
        self.sel_end_line = -1
        self.sel_end_char = -1
        self.is_selecting_text = False

        # Language Palette Modal
        self.lang_palette = LanguagePalette(current_source=self.source_lang, current_target=self.target_lang, parent=self)
        self.lang_palette.language_selected.connect(self.on_language_selected)
        self.lang_palette.hide()

    def toggle_language_menu(self):
        if self.lang_palette.isVisible():
            self.lang_palette.hide()
        else:
            pw = self.lang_palette.width()
            px = (self.width() - pw) // 2
            py = max(50, self.height() // 4)
            self.lang_palette.move(px, py)
            self.lang_palette.show()
            self.lang_palette.raise_()

    def on_language_selected(self, source_lang: str, target_lang: str):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.lang_palette.hide()
        self.show_toast(f"Язык: {source_lang.upper()} ➔ {target_lang.upper()}")

        if self.state == self.STATE_RESULT and self.translated_items:
            orig_texts = [item.block.original_text for item in self.translated_items]
            self.retranslate_worker = ReTranslateWorker(
                texts=orig_texts,
                target_lang=self.target_lang,
                source_lang=self.source_lang,
            )
            self.retranslate_worker.finished_translations.connect(self.on_retranslated)
            self.retranslate_worker.start()
        self.update()

    def on_retranslated(self, new_translations: List[str]):
        if not new_translations or len(new_translations) != len(self.translated_items):
            return

        for item, trans in zip(self.translated_items, new_translations):
            item.translated_text = trans
            fsize = max(8, int(item.rect_logical.height() * 0.72))
            font = QFont("Segoe UI", fsize, QFont.Weight.Medium)
            fm = QFontMetrics(font)
            while fsize > 7 and fm.horizontalAdvance(trans) > (item.card_rect.width() - 8):
                fsize -= 1
                font.setPointSize(fsize)
                fm = QFontMetrics(font)
            item.font = font

        self.clear_selection()
        self.update()

    def toggle_original(self):
        if self.state != self.STATE_RESULT or not self.translated_items:
            return

        self.show_original = not self.show_original
        status = "Оригинал" if self.show_original else "Перевод"
        self.show_toast(f"Режим: {status}")

        for item in self.translated_items:
            text = item.block.original_text if self.show_original else item.translated_text
            fsize = max(8, int(item.rect_logical.height() * 0.72))
            font = QFont("Segoe UI", fsize, QFont.Weight.Medium)
            fm = QFontMetrics(font)
            while fsize > 7 and fm.horizontalAdvance(text) > (item.card_rect.width() - 8):
                fsize -= 1
                font.setPointSize(fsize)
                fm = QFontMetrics(font)
            item.font = font

        self.clear_selection()
        self.update()

    def show_toast(self, message: str):
        pass

    def _hide_toast(self):
        pass

    def close_overlay(self):
        self.clear_selection()
        self.close()
        self.closed.emit()

    def clear_selection(self):
        self.sel_start_line = -1
        self.sel_start_char = -1
        self.sel_end_line = -1
        self.sel_end_char = -1
        self.is_selecting_text = False

    def _find_line_at_point(self, pt: QPoint) -> Optional[int]:
        if not self.translated_items:
            return None
        # Check direct containment with vertical padding
        for i, item in enumerate(self.translated_items):
            hit = item.card_rect.adjusted(-20, -5, 20, 5)
            if hit.contains(pt):
                return i
        # If inside the overall selected_rect, find closest line vertically
        if self.selected_rect.contains(pt):
            closest_i = 0
            min_dist = float("inf")
            for i, item in enumerate(self.translated_items):
                dist = abs(item.card_rect.center().y() - pt.y())
                if dist < min_dist:
                    min_dist = dist
                    closest_i = i
            if min_dist < 40:
                return closest_i
        return None

    def _get_char_index_at_x(self, item: TranslatedItem, mouse_x: int) -> int:
        text = item.block.original_text if self.show_original else item.translated_text
        if not text:
            return 0
        fm = QFontMetrics(item.font)
        rel_x = mouse_x - (item.card_rect.left() + 4)
        if rel_x <= 0:
            return 0
        for i in range(len(text)):
            w_prev = fm.horizontalAdvance(text[:i])
            w_curr = fm.horizontalAdvance(text[: i + 1])
            if rel_x < (w_prev + w_curr) / 2:
                return i
        return len(text)

    def _get_normalized_selection(self) -> Optional[Tuple[int, int, int, int]]:
        if self.sel_start_line == -1 or self.sel_end_line == -1:
            return None
        l1, c1 = self.sel_start_line, self.sel_start_char
        l2, c2 = self.sel_end_line, self.sel_end_char
        if l1 > l2 or (l1 == l2 and c1 > c2):
            l1, l2 = l2, l1
            c1, c2 = c2, c1
        return l1, c1, l2, c2

    def _get_selected_text(self) -> str:
        norm = self._get_normalized_selection()
        if not norm:
            return ""
        l1, c1, l2, c2 = norm
        if l1 == l2 and c1 == c2:
            return ""
        lines_out = []
        for i in range(l1, l2 + 1):
            if i >= len(self.translated_items):
                continue
            item = self.translated_items[i]
            text = item.block.original_text if self.show_original else item.translated_text
            if l1 == l2:
                lines_out.append(text[c1:c2])
            elif i == l1:
                lines_out.append(text[c1:])
            elif i == l2:
                lines_out.append(text[:c2])
            else:
                lines_out.append(text)
        return "\n".join(lines_out)

    def _select_all(self):
        if not self.translated_items:
            return
        self.sel_start_line = 0
        self.sel_start_char = 0
        self.sel_end_line = len(self.translated_items) - 1
        last_item = self.translated_items[-1]
        last_text = last_item.block.original_text if self.show_original else last_item.translated_text
        self.sel_end_char = len(last_text)
        self.update()

    def copy_to_clipboard(self):
        text = self._get_selected_text()
        if not text:
            # If nothing highlighted, copy all translated lines
            text = "\n".join(
                item.block.original_text if self.show_original else item.translated_text
                for item in self.translated_items
            )
        if text:
            QApplication.clipboard().setText(text)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()

        if self.lang_palette.isVisible():
            if key == Qt.Key.Key_Escape or key == Qt.Key.Key_F4:
                self.lang_palette.hide()
                return
            text = event.text()
            if text in "123456789":
                if self.lang_palette.select_by_number(text):
                    return

        if key == Qt.Key.Key_Escape:
            self.close_overlay()
        elif key == Qt.Key.Key_Tab:
            self.toggle_original()
        elif key == Qt.Key.Key_F4:
            self.toggle_language_menu()
        elif (event.matches(QKeySequence.StandardKey.Copy) or (
            key == Qt.Key.Key_C and (mods & Qt.KeyboardModifier.ControlModifier)
        )) and self.state == self.STATE_RESULT:
            self.copy_to_clipboard()
        elif (key == Qt.Key.Key_A and (mods & Qt.KeyboardModifier.ControlModifier)) and self.state == self.STATE_RESULT:
            self._select_all()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        pt = event.pos()

        if self.lang_palette.isVisible():
            if not self.lang_palette.geometry().contains(pt):
                self.lang_palette.hide()
                return

        if event.button() == Qt.MouseButton.RightButton:
            self.close_overlay()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == self.STATE_RESULT:
                if not self.selected_rect.contains(pt):
                    # Clicked outside -> close
                    self.close_overlay()
                    return

                # Clicked inside -> handle multi-line text selection
                line_idx = self._find_line_at_point(pt)
                if line_idx is not None:
                    item = self.translated_items[line_idx]
                    char_idx = self._get_char_index_at_x(item, pt.x())
                    self.sel_start_line = line_idx
                    self.sel_start_char = char_idx
                    self.sel_end_line = line_idx
                    self.sel_end_char = char_idx
                    self.is_selecting_text = True
                else:
                    self.clear_selection()
                self.update()
                return

            # STATE_IDLE -> start dragging selection rectangle
            self.state = self.STATE_DRAGGING
            self.start_pos = pt
            self.end_pos = pt
            self.selected_rect = QRect()
            self.translated_items = []
            self.show_original = False
            self.clear_selection()
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pt = event.pos()
        if self.state == self.STATE_DRAGGING:
            self.end_pos = pt
            self.selected_rect = QRect(self.start_pos, self.end_pos).normalized()
            self.update()
        elif self.state == self.STATE_RESULT:
            if self.is_selecting_text:
                line_idx = self._find_line_at_point(pt)
                if line_idx is not None:
                    item = self.translated_items[line_idx]
                    char_idx = self._get_char_index_at_x(item, pt.x())
                    self.sel_end_line = line_idx
                    self.sel_end_char = char_idx
                    self.update()
            else:
                line_idx = self._find_line_at_point(pt)
                if line_idx is not None:
                    self.setCursor(Qt.CursorShape.IBeamCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == self.STATE_RESULT:
                if self.is_selecting_text:
                    self.is_selecting_text = False
                    norm = self._get_normalized_selection()
                    if norm and norm[0] == norm[2] and norm[1] == norm[3]:
                        # Click with 0 drag length: clear selection
                        self.clear_selection()
                    self.update()
                return

            if self.state == self.STATE_DRAGGING:
                self.end_pos = event.pos()
                self.selected_rect = QRect(self.start_pos, self.end_pos).normalized()

                if self.selected_rect.width() < 15 or self.selected_rect.height() < 15:
                    self.state = self.STATE_IDLE
                    self.selected_rect = QRect()
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.update()
                    return

                self.state = self.STATE_PROCESSING
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()
                self.start_processing()

    def _find_word_bounds(self, text: str, idx: int) -> Tuple[int, int]:
        if not text:
            return 0, 0
        idx = max(0, min(len(text) - 1, idx))
        if text[idx].isspace() and idx > 0 and not text[idx - 1].isspace():
            idx -= 1
        elif text[idx].isspace() and idx + 1 < len(text) and not text[idx + 1].isspace():
            idx += 1

        is_word_char = lambda c: c.isalnum() or c in "_-–"

        if is_word_char(text[idx]):
            start = idx
            while start > 0 and is_word_char(text[start - 1]):
                start -= 1
            end = idx + 1
            while end < len(text) and is_word_char(text[end]):
                end += 1
            return start, end
        else:
            return idx, idx + 1

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self.state == self.STATE_RESULT and event.button() == Qt.MouseButton.LeftButton:
            pt = event.pos()
            line_idx = self._find_line_at_point(pt)
            if line_idx is not None:
                item = self.translated_items[line_idx]
                text = item.block.original_text if self.show_original else item.translated_text
                char_idx = self._get_char_index_at_x(item, pt.x())
                word_start, word_end = self._find_word_bounds(text, char_idx)
                self.sel_start_line = line_idx
                self.sel_start_char = word_start
                self.sel_end_line = line_idx
                self.sel_end_char = word_end
                self.update()
                self.copy_to_clipboard()

    def start_processing(self):
        rx = int(self.selected_rect.x() * self.dpr)
        ry = int(self.selected_rect.y() * self.dpr)
        rw = int(self.selected_rect.width() * self.dpr)
        rh = int(self.selected_rect.height() * self.dpr)

        cropped_pixmap = self.pixmap.copy(rx, ry, rw, rh)
        qimg = cropped_pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(h * w * 4)
        pil_img = Image.frombuffer("RGBA", (w, h), bytes(ptr), "raw", "RGBA", 0, 1).convert("RGB")

        self.worker = WorkerThread(
            pil_image=pil_img,
            sel_rect=self.selected_rect,
            dpr=self.dpr,
            source_lang=self.source_lang,
            target_lang=self.target_lang,
        )
        self.worker.finished_data.connect(self.on_processing_finished)
        self.worker.error_occurred.connect(self.on_processing_error)
        self.worker.start()

    def on_processing_finished(self, items: List[TranslatedItem], full_text: str):
        self.translated_items = items
        self.state = self.STATE_RESULT
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.clear_selection()

        if not items:
            self.show_toast("Текст не обнаружен. Нажмите Esc")
        self.update()

    def on_processing_error(self, err: str):
        self.state = self.STATE_RESULT
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 1. Base screenshot
        painter.drawPixmap(self.rect(), self.pixmap)

        dim_color = QColor(0, 0, 0, 115)

        if self.state == self.STATE_IDLE:
            painter.fillRect(self.rect(), dim_color)
            self._draw_toast_if_any(painter)
            return

        # Dim surroundings around selection
        r = self.selected_rect
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, r.top(), dim_color)
        painter.fillRect(0, r.bottom() + 1, w, h - (r.bottom() + 1), dim_color)
        painter.fillRect(0, r.top(), r.left(), r.height() + 1, dim_color)
        painter.fillRect(r.right() + 1, r.top(), w - (r.right() + 1), r.height() + 1, dim_color)

        # Clean minimalist border (crisp neutral white)
        pen = QPen(QColor(255, 255, 255, 230), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        if self.state == self.STATE_DRAGGING:
            pass

        elif self.state == self.STATE_PROCESSING:
            pass

        elif self.state == self.STATE_RESULT:
            norm_sel = self._get_normalized_selection()

            # Render translated text lines directly with QPainter
            for i, item in enumerate(self.translated_items):
                text = item.block.original_text if self.show_original else item.translated_text
                if not text:
                    continue

                # 1. Fill smooth background (ZERO BORDERS, NO OUTLINES)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(item.bg_color)
                painter.drawRoundedRect(item.card_rect, 4, 4)

                # 2. Check selection range for line i
                sel_start_col = None
                sel_end_col = None
                if norm_sel:
                    l1, c1, l2, c2 = norm_sel
                    if l1 <= i <= l2:
                        if l1 == l2:
                            sel_start_col = c1
                            sel_end_col = c2
                        elif i == l1:
                            sel_start_col = c1
                            sel_end_col = len(text)
                        elif i == l2:
                            sel_start_col = 0
                            sel_end_col = c2
                        else:
                            sel_start_col = 0
                            sel_end_col = len(text)

                fm = QFontMetrics(item.font)
                line_left = item.card_rect.left() + 4
                line_h = item.card_rect.height()

                painter.setFont(item.font)

                if sel_start_col is None or sel_start_col == sel_end_col:
                    # Normal unselected text
                    painter.setPen(item.fg_color)
                    draw_r = item.card_rect.adjusted(4, 0, -4, 0)
                    painter.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
                else:
                    # Line with multi-line selection highlight
                    prefix = text[:sel_start_col]
                    sel_text = text[sel_start_col:sel_end_col]
                    suffix = text[sel_end_col:]

                    prefix_w = fm.horizontalAdvance(prefix)
                    sel_w = fm.horizontalAdvance(sel_text)

                    # A) Draw selection highlight (minimalist translucent monochrome)
                    sel_bg_rect = QRect(line_left + prefix_w, item.card_rect.top() + 1, sel_w, line_h - 2)
                    is_dark = item.bg_color.lightness() < 128
                    sel_color = QColor(255, 255, 255, 65) if is_dark else QColor(0, 0, 0, 45)
                    painter.fillRect(sel_bg_rect, sel_color)

                    # B) Draw prefix
                    if prefix:
                        painter.setPen(item.fg_color)
                        draw_r = QRect(line_left, item.card_rect.top(), prefix_w, line_h)
                        painter.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, prefix)

                    # C) Draw selected text
                    if sel_text:
                        painter.setPen(QColor(255, 255, 255) if is_dark else QColor(10, 10, 10))
                        draw_r = QRect(line_left + prefix_w, item.card_rect.top(), sel_w, line_h)
                        painter.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sel_text)

                    # D) Draw suffix
                    if suffix:
                        painter.setPen(item.fg_color)
                        suffix_w = fm.horizontalAdvance(suffix)
                        draw_r = QRect(line_left + prefix_w + sel_w, item.card_rect.top(), suffix_w, line_h)
                        painter.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, suffix)

        self._draw_toast_if_any(painter)

    def _draw_minimal_pill(self, painter: QPainter, text: str):
        pass

    def _draw_toast_if_any(self, painter: QPainter):
        pass
