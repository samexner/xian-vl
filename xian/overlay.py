from typing import List
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QScrollArea, QStackedWidget
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, QSettings, QObject
from PyQt6.QtGui import QPainter, QColor, QFont, QGuiApplication, QMouseEvent, QPaintEvent, QFontMetrics, QRegion
from .models import TranslationResult

class OverlayWindow(QWidget):
    """Full-screen transparent container for bubbles to fix Wayland positioning"""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Cover the primary screen
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        # Initial mask is empty so it's click-through
        self.setMask(QRegion())
        self.show()

    def paintEvent(self, event: QPaintEvent):
        """Ensure the background is always cleared/transparent"""
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.end()

    def update_mask_during_drag(self):
        """Recalculate mask from all children during a drag operation"""
        mask = QRegion()
        # Iterate over all child widgets (the bubbles)
        for child in self.findChildren(QWidget):
            if child.isVisible() and not child.isWindow():
                mask += child.geometry()
        self.setMask(mask)
        self.update()

class TranslationBubble(QWidget):
    """Translation bubble, now a child of OverlayWindow for reliable positioning"""
    def __init__(self, result: TranslationResult, opacity: int, parent_overlay: QWidget = None):
        super().__init__(parent_overlay)
        self.result = result
        self.opacity = opacity
        self.dragging = False
        self.expanded = False
        self.drag_start_pos = QPoint()
        self.press_pos = QPoint()
        
        # Since it's a child widget, we don't need all the window flags
        # But we still want it to look like a bubble
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setup_ui()
        self.update_geometry()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 10)
        
        # Close button
        self.close_btn = QPushButton("×", self)
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(200, 0, 0, 180);
                color: white;
                border-radius: 10px;
                font-weight: bold;
                border: none;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 0, 0, 220);
            }}
        """)
        self.close_btn.clicked.connect(self.deleteLater)
        
        self.stack = QStackedWidget()
        
        # Collapsed view
        self.collapsed_label = QLabel()
        self.collapsed_label.setWordWrap(True)
        self.collapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collapsed_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background: transparent;")
        
        # Expanded view
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.expanded_label = QLabel()
        self.expanded_label.setWordWrap(True)
        self.expanded_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.expanded_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background: transparent;")
        
        self.scroll_area.setWidget(self.expanded_label)
        
        self.stack.addWidget(self.collapsed_label)
        self.stack.addWidget(self.scroll_area)
        
        layout.addWidget(self.stack)
        self._update_text_displays()

    def _get_truncated_text(self, text, word_limit=8):
        words = text.split()
        if len(words) <= word_limit:
            return text
        return " ".join(words[:word_limit]) + "..."

    def _update_text_displays(self):
        full_text = self.result.translated_text
        truncated = self._get_truncated_text(full_text)
        self.collapsed_label.setText(truncated)
        self.expanded_label.setText(full_text)

    def update_geometry(self):
        # Calculate size based on text
        font = QFont("Arial", 12, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        
        padding = 20
        if not self.expanded:
            text = self.collapsed_label.text()
            measure_width = max(150, self.result.width + padding * 2)
            if measure_width > 350: measure_width = 350
            
            text_rect = metrics.boundingRect(QRect(0, 0, measure_width - padding * 2, 1000), 
                                            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, 
                                            text)
            
            box_width = text_rect.width() + padding * 2
            box_height = text_rect.height() + padding * 2 + 10
        else:
            # Expanded mode size
            box_width = 400
            box_height = 250
        
        # Apply min sizes
        box_width = max(box_width, 100)
        box_height = max(box_height, 40)
        
        self.setFixedSize(box_width, box_height)
        
        # Parent geometry (OverlayWindow covers screen)
        if self.parentWidget():
            parent_geo = self.parentWidget().rect()
        else:
            parent_geo = QGuiApplication.primaryScreen().geometry()
        
        # Center the bubble over the original text coordinates
        target_x = self.result.x + (self.result.width - box_width) // 2
        target_y = self.result.y + (self.result.height - box_height) // 2
        
        x = max(10, min(target_x, parent_geo.width() - box_width - 10))
        y = max(10, min(target_y, parent_geo.height() - box_height - 10))
        
        self.move(int(x), int(y))

    def toggle_expansion(self):
        self.expanded = not self.expanded
        self.stack.setCurrentIndex(1 if self.expanded else 0)
        self.update_geometry()
        
        # Update mask because size changed
        parent = self.parentWidget()
        if parent and hasattr(parent, 'update_mask_during_drag'):
            parent.update_mask_during_drag()

    def update_content(self, result: TranslationResult):
        """Update bubble with new translation result"""
        if self.result.translated_text != result.translated_text:
            self.result = result
            self._update_text_displays()
            self.update_geometry()
            self._pulse()
        else:
            # Just update coordinates if they changed significantly
            old_pos = QPoint(int(self.result.x), int(self.result.y))
            new_pos = QPoint(int(result.x), int(result.y))
            if (old_pos - new_pos).manhattanLength() > 5:
                self.result = result
                self.update_geometry()

    def _pulse(self):
        """Briefly highlight the bubble when updated"""
        target = self.expanded_label if self.expanded else self.collapsed_label
        target.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 15px; background: transparent;")
        QTimer.singleShot(500, self._reset_style)

    def _reset_style(self):
        if not sip.isdeleted(self):
            style = "color: white; font-weight: bold; font-size: 14px; background: transparent;"
            self.collapsed_label.setStyleSheet(style)
            self.expanded_label.setStyleSheet(style)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        opacity_alpha = int(self.opacity * 2.55)
        
        # Draw shadow
        painter.setBrush(QColor(0, 0, 0, min(255, opacity_alpha + 40)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.translated(2, 2), 10, 10)
        
        # Draw background
        painter.setBrush(QColor(0, 0, 0, opacity_alpha))
        painter.drawRoundedRect(rect, 10, 10)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_start_pos = event.position().toPoint()
            self.press_pos = event.globalPosition().toPoint()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.deleteLater()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            new_pos = self.pos() + event.position().toPoint() - self.drag_start_pos
            self.move(new_pos)
            
            parent = self.parentWidget()
            if parent and hasattr(parent, 'update_mask_during_drag'):
                parent.update_mask_during_drag()
            
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.dragging:
            # Check for click vs drag
            curr_pos = event.globalPosition().toPoint()
            if (curr_pos - self.press_pos).manhattanLength() < 5:
                self.toggle_expansion()
        self.dragging = False
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.close_btn.move(self.width() - 25, 5)

class TranslationOverlay(QObject):
    """Manager for TranslationBubble widgets using a full-screen container"""

    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self.bubbles = []
        self.parent_window = parent_window
        self.overlay_window = OverlayWindow()
        
        # Ensure overlay window follows main window lifecycle
        if parent_window:
            parent_window.destroyed.connect(self.overlay_window.deleteLater)

    def hide(self):
        """Hide overlay and all bubbles"""
        self.overlay_window.hide()

    def show(self):
        """Show overlay and all bubbles"""
        self.overlay_window.show()
        self.overlay_window.raise_()

    def update_translations(self, translations: List[TranslationResult], updated_area: QRect = None):
        """Add new translations as bubbles with smart merging and grouping"""
        # Clean up any deleted objects first
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]

        if not translations and not updated_area:
            return
            
        # Limit the number of input translations to prevent O(N^2) hangs
        if len(translations) > 50:
            print(f"Warning: Too many translations received ({len(translations)}), limiting to 50")
            translations = translations[:50]
            
        print(f"Updating overlay with {len(translations)} results" + (f" in area {updated_area}" if updated_area else ""))
        settings = QSettings("Xian", "VideoGameTranslator")
        opacity = int(settings.value("opacity", 80))
        
        # Track which bubbles were matched/created in this update
        matched_bubble_ids = set()
        
        # 1. Pre-process: Merge very close results from the API itself
        merged_results = []
        sorted_results = sorted(translations, key=lambda r: (r.y, r.x))
        
        for res in sorted_results:
            found_group = False
            for existing in merged_results:
                y_diff = abs(existing.y - res.y)
                x_diff = res.x - (existing.x + existing.width)
                
                if y_diff < 20:
                    if res.translated_text.strip() == existing.translated_text.strip() and abs(x_diff) < 50:
                        found_group = True
                        break
                    
                    if -20 < x_diff < 40:
                        if res.translated_text.strip().lower() not in existing.translated_text.lower():
                            existing.translated_text += " " + res.translated_text
                        
                        new_right = max(existing.x + existing.width, res.x + res.width)
                        existing.width = new_right - existing.x
                        existing.height = max(existing.height, res.height)
                        existing.y = min(existing.y, res.y)
                        found_group = True
                        break
            
            if not found_group:
                from dataclasses import replace
                merged_results.append(replace(res))

        # 2. Update existing bubbles or create new ones
        for result in merged_results:
            best_match = None
            highest_score = 0.0
            
            result_text_norm = result.translated_text.strip().lower()
            new_source_rect = QRect(int(result.x), int(result.y), int(result.width), int(result.height))
            
            for bubble in self.bubbles:
                if sip.isdeleted(bubble): continue
                
                score = 0.0
                ex = bubble.result
                ex_text_norm = ex.translated_text.strip().lower()
                ex_source_rect = QRect(int(ex.x), int(ex.y), int(ex.width), int(ex.height))
                
                iou = 0.0
                if ex_source_rect.intersects(new_source_rect):
                    inter = ex_source_rect.intersected(new_source_rect)
                    union = ex_source_rect.united(new_source_rect)
                    iou = (inter.width() * inter.height()) / (union.width() * union.height())
                
                if ex_text_norm == result_text_norm or ex_text_norm in result_text_norm or result_text_norm in ex_text_norm:
                    dist = abs(ex.x - result.x) + abs(ex.y - result.y)
                    if dist < 500:
                        score = 0.7 + (1.0 - min(1.0, dist / 500)) * 0.3
                
                score = max(score, iou)
                
                c_dist = (ex_source_rect.center() - new_source_rect.center()).manhattanLength()
                if c_dist < 100:
                    score = max(score, (1.0 - c_dist / 100) * 0.6)
                
                if score > highest_score:
                    highest_score = score
                    best_match = bubble
            
            if best_match and highest_score > 0.4:
                try:
                    best_match.update_content(result)
                    matched_bubble_ids.add(id(best_match))
                    continue
                except (RuntimeError, AttributeError):
                    pass

            try:
                bubble = TranslationBubble(result, opacity, self.overlay_window)
                if not sip.isdeleted(bubble):
                    self.bubbles.append(bubble)
                    matched_bubble_ids.add(id(bubble))
                    bubble.destroyed.connect(self._remove_bubble)
                    
                    if self.parent_window and not sip.isdeleted(self.parent_window):
                        if self.parent_window.hide_overlay_checkbox.isChecked():
                            bubble.hide()
                        else:
                            bubble.show()
                    else:
                        bubble.show()
                        
                    try:
                        bubble.raise_()
                    except (RuntimeError, AttributeError):
                        pass
            except (RuntimeError, AttributeError) as e:
                print(f"Failed to create or show bubble: {e}")
                continue
        
        # 3. If an updated_area was provided, remove unmatched bubbles in that area
        if updated_area:
            for bubble in self.bubbles[:]:
                if sip.isdeleted(bubble): continue
                if id(bubble) not in matched_bubble_ids:
                    # Check if bubble's original text area is within the updated_area
                    r = bubble.result
                    bubble_source_rect = QRect(int(r.x), int(r.y), int(r.width), int(r.height))
                    
                    # If the bubble's source area overlaps significantly with the updated area, remove it.
                    # We use intersection or center check. Intersection is safer.
                    # We also add a small margin to the updated_area to handle floating point issues or minor shifts.
                    margin_area = updated_area.adjusted(-5, -5, 5, 5)
                    if margin_area.intersects(bubble_source_rect) or margin_area.contains(bubble_source_rect.center()):
                        bubble.close()
        
        # 4. Limit total number of bubbles to prevent performance issues/crashes
        MAX_BUBBLES = 50
        if len(self.bubbles) > MAX_BUBBLES:
            # Sort by age (oldest first - bubbles are appended, so early ones are older)
            # Actually, bubbles might be updated, but new ones are at the end.
            # Let's just remove the oldest ones that weren't just matched.
            num_to_remove = len(self.bubbles) - MAX_BUBBLES
            removed_count = 0
            for i in range(len(self.bubbles)):
                bubble = self.bubbles[i]
                if id(bubble) not in matched_bubble_ids:
                    bubble.close()
                    removed_count += 1
                    if removed_count >= num_to_remove:
                        break

        self._update_mask()

    def _update_mask(self):
        """Update overlay window mask to allow click-through outside bubbles"""
        if sip.isdeleted(self.overlay_window):
            return
            
        mask = QRegion()
        for bubble in self.bubbles:
            if not sip.isdeleted(bubble) and bubble.isVisible():
                # We use the bubble's geometry which is relative to the overlay_window
                mask += bubble.geometry()
        
        self.overlay_window.setMask(mask)
        self.overlay_window.update() # Force repaint to clear old trails

    def _remove_bubble(self, qobj):
        """Handle bubble destruction safely"""
        for bubble in self.bubbles[:]:
            if bubble is qobj or sip.isdeleted(bubble):
                try:
                    self.bubbles.remove(bubble)
                except (ValueError, RuntimeError):
                    pass
        self._update_mask()

    def clear_translations(self):
        """Clear all active translation bubbles"""
        print("Clearing all translations")
        to_close = [b for b in self.bubbles if not sip.isdeleted(b)]
        self.bubbles = []
        for bubble in to_close:
            try:
                bubble.close()
            except:
                pass
        self._update_mask()

    def get_bubble_geometries(self) -> List[QRect]:
        """Return list of current bubble geometries and original source geometries for redaction"""
        active_geoms = []
        for b in self.bubbles:
            if not sip.isdeleted(b):
                try:
                    # 1. Current bubble geometry (needs to be in screen coords for redaction)
                    # Since it's a child of OverlayWindow which is at 0,0 screen coords, 
                    # geometry() and pos() are effectively screen coords.
                    active_geoms.append(b.geometry())
                    
                    # 2. Original source text geometry
                    r = b.result
                    active_geoms.append(QRect(int(r.x), int(r.y), int(r.width), int(r.height)))
                except (RuntimeError, AttributeError):
                    pass
        
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]
        return active_geoms
