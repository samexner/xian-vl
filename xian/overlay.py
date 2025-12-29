from typing import List
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, QSettings, QObject
from PyQt6.QtGui import QPainter, QColor, QFont, QGuiApplication, QMouseEvent, QPaintEvent, QFontMetrics
from .models import TranslationResult

class TranslationBubble(QWidget):
    """Draggable and closable translation bubble"""
    def __init__(self, result: TranslationResult, opacity: int, parent_window=None):
        # Do not set a QWidget parent to avoid child-window mapping issues on Wayland
        super().__init__(None)
        self.result = result
        self.opacity = opacity
        self.parent_window = parent_window
        self.dragging = False
        self.drag_start_pos = QPoint()
        
        # Use Window for reliability on Wayland
        # ToolTips can be treated as popups which require strict parentage in Wayland
        flags = (
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        # Ensure native window is created and then set transient parent
        self.winId()
        
        self.setup_ui()
        self.update_geometry()
        
        # Set transient parent BEFORE showing to satisfy Wayland
        self._setup_wayland_hints()

    def _setup_wayland_hints(self):
        """Finalize window state for Wayland compositors"""
        if self.parent_window:
            try:
                handle = self.windowHandle()
                # Ensure the parent's window handle is also available
                if self.parent_window.windowHandle() is None:
                    self.parent_window.winId()
                
                parent_handle = self.parent_window.windowHandle()
                if handle and parent_handle:
                    handle.setTransientParent(parent_handle)
                    print(f"Debug: Successfully set transient parent for bubble '{self.result.translated_text[:20]}...'")
                else:
                    print(f"Debug: Missing handle for transient parent (self: {handle}, parent: {parent_handle})")
            except Exception as e:
                print(f"Error setting transient parent: {e}")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Close button (only show on hover if we wanted to be fancy, but let's keep it simple)
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
        
        # Move close button to top right
        self.close_btn.move(self.width() - 25, 5)
        
        self.label = QLabel(self.result.translated_text)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background: transparent;")
        
        layout.addWidget(self.label)

    def update_geometry(self):
        # Calculate size based on text
        font = QFont("Arial", 12, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        
        padding = 20
        measure_width = max(150, self.result.width + padding * 2)
        if measure_width > 400: measure_width = 400
        
        text_rect = metrics.boundingRect(QRect(0, 0, measure_width - padding * 2, 1000), 
                                        Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, 
                                        self.result.translated_text)
        
        box_width = text_rect.width() + padding * 2
        box_height = text_rect.height() + padding * 2
        
        # Apply min sizes
        box_width = max(box_width, 100)
        box_height = max(box_height, 40)
        
        self.setFixedSize(box_width, box_height)
        
        # Screen boundary clamping
        screen_geo = QGuiApplication.primaryScreen().geometry()
        
        # Center the bubble over the original text coordinates if possible
        target_x = self.result.x + (self.result.width - box_width) // 2
        target_y = self.result.y + (self.result.height - box_height) // 2
        
        x = max(10, min(target_x, screen_geo.width() - box_width - 10))
        y = max(10, min(target_y, screen_geo.height() - box_height - 10))
        
        self.move(x, y)

    def update_content(self, result: TranslationResult):
        """Update bubble with new translation result"""
        if self.result.translated_text != result.translated_text:
            self.result = result
            self.label.setText(result.translated_text)
            self.update_geometry()
            self._pulse()
        else:
            # Just update coordinates if they changed significantly
            old_pos = QPoint(self.result.x, self.result.y)
            new_pos = QPoint(result.x, result.y)
            if (old_pos - new_pos).manhattanLength() > 5:
                self.result = result
                self.update_geometry()

    def _pulse(self):
        """Briefly highlight the bubble when updated"""
        self.label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 15px; background: transparent;")
        QTimer.singleShot(500, self._reset_style)

    def _reset_style(self):
        if not sip.isdeleted(self):
            self.label.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background: transparent;")

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
            self.drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.deleteLater()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_start_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.dragging = False
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.close_btn.move(self.width() - 25, 5)

class TranslationOverlay(QObject):
    """Manager for TranslationBubble widgets"""

    def __init__(self, parent_window=None):
        super().__init__()
        self.bubbles = []
        self.parent_window = parent_window

    def hide(self):
        """Hide all bubbles"""
        # Clean up any deleted objects first
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]
        for bubble in self.bubbles:
            try:
                bubble.hide()
            except:
                pass

    def show(self):
        """Show all bubbles"""
        # Clean up any deleted objects first
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]
        for bubble in self.bubbles:
            try:
                bubble.show()
            except:
                pass

    def update_translations(self, translations: List[TranslationResult]):
        """Add new translations as bubbles with smart merging and grouping"""
        if not translations:
            return
            
        print(f"Updating overlay with {len(translations)} results")
        settings = QSettings("Xian", "VideoGameTranslator")
        opacity = int(settings.value("opacity", 80))
        
        # Clean up any deleted objects first
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]
        
        # 1. Pre-process: Merge very close results from the API itself
        # This handles cases where the LLM splits a single line into multiple fragments
        merged_results = []
        sorted_results = sorted(translations, key=lambda r: (r.y, r.x))
        
        for res in sorted_results:
            found_group = False
            for existing in merged_results:
                # If they are on the same line and close horizontally
                y_diff = abs(existing.y - res.y)
                x_diff = res.x - (existing.x + existing.width)
                
                # Check if they are overlapping or very close
                if y_diff < 20:
                    # Case 1: Identical text and overlapping/near
                    if res.translated_text.strip() == existing.translated_text.strip() and abs(x_diff) < 50:
                        found_group = True
                        break
                    
                    # Case 2: Adjacent text fragments on same line
                    if -20 < x_diff < 40:
                        # Avoid duplicating text if the model repeats it
                        if res.translated_text.strip().lower() not in existing.translated_text.lower():
                            existing.translated_text += " " + res.translated_text
                        
                        new_right = max(existing.x + existing.width, res.x + res.width)
                        existing.width = new_right - existing.x
                        existing.height = max(existing.height, res.height)
                        existing.y = min(existing.y, res.y)
                        found_group = True
                        break
            
            if not found_group:
                # Create a copy to avoid modifying original results from other references
                from dataclasses import replace
                merged_results.append(replace(res))

        # 2. Update existing bubbles or create new ones
        for result in merged_results:
            best_match = None
            highest_score = 0.0
            
            result_text_norm = result.translated_text.strip().lower()
            new_source_rect = QRect(result.x, result.y, result.width, result.height)
            
            for bubble in self.bubbles:
                if sip.isdeleted(bubble): continue
                
                score = 0.0
                ex = bubble.result
                ex_text_norm = ex.translated_text.strip().lower()
                ex_source_rect = QRect(ex.x, ex.y, ex.width, ex.height)
                
                # Check for spatial overlap (Intersection over Union)
                iou = 0.0
                if ex_source_rect.intersects(new_source_rect):
                    inter = ex_source_rect.intersected(new_source_rect)
                    union = ex_source_rect.united(new_source_rect)
                    iou = (inter.width() * inter.height()) / (union.width() * union.height())
                
                # 1. Exact or near text match + proximity
                if ex_text_norm == result_text_norm or ex_text_norm in result_text_norm or result_text_norm in ex_text_norm:
                    dist = abs(ex.x - result.x) + abs(ex.y - result.y)
                    if dist < 500: # Broad radius for similar text
                        score = 0.7 + (1.0 - min(1.0, dist / 500)) * 0.3
                
                # 2. Spatial overlap boost
                score = max(score, iou)
                
                # 3. Center proximity
                c_dist = (ex_source_rect.center() - new_source_rect.center()).manhattanLength()
                if c_dist < 100:
                    score = max(score, (1.0 - c_dist / 100) * 0.6)
                
                if score > highest_score:
                    highest_score = score
                    best_match = bubble
            
            # If we found a good match, update it
            if best_match and highest_score > 0.4:
                try:
                    best_match.update_content(result)
                    continue
                except (RuntimeError, AttributeError):
                    pass

            # No match found, create a new bubble
            try:
                bubble = TranslationBubble(result, opacity, self.parent_window)
                if sip.isdeleted(bubble):
                    continue
                    
                self.bubbles.append(bubble)
                
                # Clean up when bubble is closed
                bubble.destroyed.connect(self._remove_bubble)
                
                print(f"Created bubble: '{result.translated_text[:30]}...' at {result.x}, {result.y}")
                
                if self.parent_window and not sip.isdeleted(self.parent_window):
                    if self.parent_window.hide_overlay_checkbox.isChecked():
                        bubble.hide()
                    else:
                        bubble.show()
                else:
                    bubble.show()
                    
                if not sip.isdeleted(bubble):
                    try:
                        bubble.raise_()
                    except (RuntimeError, AttributeError):
                        pass
            except (RuntimeError, AttributeError) as e:
                print(f"Failed to create or show bubble: {e}")
                continue
        
        # Process events once after all bubbles are created to ensure they are rendered
        QGuiApplication.processEvents()

    def _remove_bubble(self, qobj):
        """Handle bubble destruction safely"""
        # Note: qobj might be already partially deleted, but we can check if it's in our list
        # Using [:] for safe iteration during possible removal
        for bubble in self.bubbles[:]:
            if bubble is qobj or sip.isdeleted(bubble):
                try:
                    self.bubbles.remove(bubble)
                except (ValueError, RuntimeError):
                    pass

    def clear_translations(self):
        """Clear all active translation bubbles"""
        print("Clearing all translations")
        # Work on a copy of the list
        to_close = [b for b in self.bubbles if not sip.isdeleted(b)]
        self.bubbles = [] # Clear the list immediately to prevent double-processing
        for bubble in to_close:
            try:
                bubble.close()
            except:
                pass

    def get_bubble_geometries(self) -> List[QRect]:
        """Return list of current bubble geometries and original source geometries for redaction"""
        # Filter out deleted bubbles and return geometries
        active_geoms = []
        for b in self.bubbles:
            if not sip.isdeleted(b):
                try:
                    # 1. Current bubble geometry (to hide the UI from AI)
                    active_geoms.append(b.geometry())
                    
                    # 2. Original source text geometry (to hide the Chinese text from AI)
                    # This ensures that even if a bubble is moved, the original text stays redacted
                    r = b.result
                    active_geoms.append(QRect(r.x, r.y, r.width, r.height))
                except (RuntimeError, AttributeError):
                    pass
        
        # Update our internal list to remove any found deleted bubbles
        self.bubbles = [b for b in self.bubbles if not sip.isdeleted(b)]
        
        return active_geoms
