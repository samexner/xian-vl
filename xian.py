#!/usr/bin/env python3
"""
Real-time Game Translation Tool for Linux
Supports Wayland and X11, uses Qwen3-VL via Ollama for OCR and translation
"""

import sys
import json
import base64
import io
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QSpinBox, QCheckBox, QDialog, QListWidget,
                             QDialogButtonBox, QGroupBox, QSlider, QFrame)
from PyQt6.QtCore import Qt, QRect, QPoint, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import (QPainter, QColor, QPen, QPixmap, QFont, QGuiApplication,
                         QScreen, QPainterPath, QRegion, QKeySequence, QShortcut)
import requests


class TranslationWorker(QThread):
    """Background worker for translation requests"""
    translation_ready = pyqtSignal(str, QRect)
    
    def __init__(self, image_data, bbox, source_lang, target_lang, model):
        super().__init__()
        self.image_data = image_data
        self.bbox = bbox
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model = model
        
    def run(self):
        try:
            # Convert image to base64
            buffered = io.BytesIO()
            self.image_data.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode()
            
            # Prepare prompt for Qwen3-VL
            prompt = f"""Extract and translate the text in this image from {self.source_lang} to {self.target_lang}. 
Only provide the translated text, nothing else. If there's no text, respond with [NO TEXT]."""
            
            # Call Ollama API
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': self.model,
                    'prompt': prompt,
                    'images': [img_base64],
                    'stream': False
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get('response', '').strip()
                
                if translated_text and translated_text != '[NO TEXT]':
                    self.translation_ready.emit(translated_text, self.bbox)
        except Exception as e:
            print(f"Translation error: {e}")


class TranslationOverlay(QWidget):
    """Transparent overlay showing translated text"""
    
    def __init__(self, text, rect, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | 
                        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        self.text = text
        self.original_rect = rect
        self.dragging = False
        self.drag_start = QPoint()
        self.opacity = 0.8
        
        self.setGeometry(rect)
        self.show()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        bg_color = QColor(0, 0, 0, int(200 * self.opacity))
        painter.fillRect(self.rect(), bg_color)
        
        # Border
        painter.setPen(QPen(QColor(100, 150, 255), 2))
        painter.drawRect(1, 1, self.width()-2, self.height()-2)
        
        # Text
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Sans", 10)
        painter.setFont(font)
        
        text_rect = self.rect().adjusted(5, 5, -5, -5)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | 
                        Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, 
                        self.text)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_start = event.globalPosition().toPoint()
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            
    def mouseMoveEvent(self, event):
        if self.dragging:
            delta = event.globalPosition().toPoint() - self.drag_start
            self.move(self.pos() + delta)
            self.drag_start = event.globalPosition().toPoint()
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            
    def mouseDoubleClickEvent(self, event):
        """Double-click to remove overlay"""
        self.close()


class DraggableBox(QWidget):
    """Draggable and resizable box that can be positioned before confirming"""
    
    def __init__(self, is_capture=True, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | 
                        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.is_capture = is_capture
        self.dragging = False
        self.resizing = False
        self.drag_start = QPoint()
        self.resize_edge = None
        self.resize_margin = 10
        
        # Start with a reasonable size in the center of the screen
        screen = QGuiApplication.primaryScreen().geometry()
        box_width = 300
        box_height = 150
        x = (screen.width() - box_width) // 2
        y = (screen.height() - box_height) // 2
        
        self.setGeometry(x, y, box_width, box_height)
        self.setMouseTracking(True)
        self.show()
        self.raise_()
        self.activateWindow()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Semi-transparent background
        if self.is_capture:
            bg_color = QColor(0, 255, 0, 60)
            border_color = QColor(0, 255, 0, 255)
            label = "CAPTURE REGION"
        else:
            bg_color = QColor(255, 0, 0, 60)
            border_color = QColor(255, 0, 0, 255)
            label = "EXCLUDE REGION"
        
        painter.fillRect(self.rect(), bg_color)
        
        # Border
        painter.setPen(QPen(border_color, 3))
        painter.drawRect(1, 1, self.width()-2, self.height()-2)
        
        # Label
        painter.setPen(border_color)
        font = QFont("Sans", 12, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, label)
        
        # Instructions
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Sans", 9)
        painter.setFont(font)
        instructions = "Drag to move • Resize from edges/corners"
        painter.drawText(self.rect().adjusted(0, 30, 0, 0), 
                        Qt.AlignmentFlag.AlignCenter, instructions)
        
        # Resize handles
        handle_size = 10
        painter.setBrush(border_color)
        # Corners
        painter.drawEllipse(QRect(-handle_size//2, -handle_size//2, handle_size, handle_size))
        painter.drawEllipse(QRect(self.width()-handle_size//2, -handle_size//2, handle_size, handle_size))
        painter.drawEllipse(QRect(-handle_size//2, self.height()-handle_size//2, handle_size, handle_size))
        painter.drawEllipse(QRect(self.width()-handle_size//2, self.height()-handle_size//2, 
                        handle_size, handle_size))
        
    def get_resize_edge(self, pos):
        """Determine which edge/corner is being grabbed"""
        margin = self.resize_margin
        w, h = self.width(), self.height()
        
        left = pos.x() < margin
        right = pos.x() > w - margin
        top = pos.y() < margin
        bottom = pos.y() > h - margin
        
        if left and top:
            return 'top_left'
        elif right and top:
            return 'top_right'
        elif left and bottom:
            return 'bottom_left'
        elif right and bottom:
            return 'bottom_right'
        elif left:
            return 'left'
        elif right:
            return 'right'
        elif top:
            return 'top'
        elif bottom:
            return 'bottom'
        return None
        
    def update_cursor(self, pos):
        """Update cursor based on position"""
        edge = self.get_resize_edge(pos)
        
        if edge in ['top_left', 'bottom_right']:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ['top_right', 'bottom_left']:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ['left', 'right']:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ['top', 'bottom']:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.resize_edge = self.get_resize_edge(event.pos())
            
            if self.resize_edge:
                self.resizing = True
                self.original_geometry = self.geometry()
            else:
                self.dragging = True
                
    def mouseMoveEvent(self, event):
        if self.resizing and self.resize_edge:
            delta = event.globalPosition().toPoint() - self.drag_start
            geo = QRect(self.original_geometry)
            
            if 'left' in self.resize_edge:
                geo.setLeft(geo.left() + delta.x())
            if 'right' in self.resize_edge:
                geo.setRight(geo.right() + delta.x())
            if 'top' in self.resize_edge:
                geo.setTop(geo.top() + delta.y())
            if 'bottom' in self.resize_edge:
                geo.setBottom(geo.bottom() + delta.y())
                
            # Minimum size
            if geo.width() > 50 and geo.height() > 50:
                self.setGeometry(geo)
                
        elif self.dragging:
            delta = event.globalPosition().toPoint() - self.drag_start
            new_pos = self.pos() + delta
            self.move(new_pos)
            self.drag_start = event.globalPosition().toPoint()
        else:
            self.update_cursor(event.pos())
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_edge = None


class RegionBox(QWidget):
    """Fixed region box after confirmation"""
    
    def __init__(self, rect, is_capture=True, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | 
                        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.is_capture = is_capture
        self.dragging = False
        self.resizing = False
        self.drag_start = QPoint()
        self.resize_edge = None
        self.resize_margin = 10
        
        self.setGeometry(rect)
        self.setMouseTracking(True)
        self.show()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Semi-transparent background
        if self.is_capture:
            bg_color = QColor(0, 255, 0, 30)
            border_color = QColor(0, 255, 0, 200)
            label = "CAPTURE"
        else:
            bg_color = QColor(255, 0, 0, 30)
            border_color = QColor(255, 0, 0, 200)
            label = "EXCLUDE"
        
        painter.fillRect(self.rect(), bg_color)
        
        # Border
        painter.setPen(QPen(border_color, 3))
        painter.drawRect(1, 1, self.width()-2, self.height()-2)
        
        # Label
        painter.setPen(border_color)
        font = QFont("Sans", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, label)
        
        # Resize handles
        handle_size = 8
        painter.setBrush(border_color)
        # Corners
        painter.drawRect(0, 0, handle_size, handle_size)
        painter.drawRect(self.width()-handle_size, 0, handle_size, handle_size)
        painter.drawRect(0, self.height()-handle_size, handle_size, handle_size)
        painter.drawRect(self.width()-handle_size, self.height()-handle_size, 
                        handle_size, handle_size)
        
    def get_resize_edge(self, pos):
        """Determine which edge/corner is being grabbed"""
        margin = self.resize_margin
        w, h = self.width(), self.height()
        
        left = pos.x() < margin
        right = pos.x() > w - margin
        top = pos.y() < margin
        bottom = pos.y() > h - margin
        
        if left and top:
            return 'top_left'
        elif right and top:
            return 'top_right'
        elif left and bottom:
            return 'bottom_left'
        elif right and bottom:
            return 'bottom_right'
        elif left:
            return 'left'
        elif right:
            return 'right'
        elif top:
            return 'top'
        elif bottom:
            return 'bottom'
        return None
        
    def update_cursor(self, pos):
        """Update cursor based on position"""
        edge = self.get_resize_edge(pos)
        
        if edge in ['top_left', 'bottom_right']:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ['top_right', 'bottom_left']:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ['left', 'right']:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ['top', 'bottom']:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.resize_edge = self.get_resize_edge(event.pos())
            
            if self.resize_edge:
                self.resizing = True
                self.original_geometry = self.geometry()
            else:
                self.dragging = True
                
    def mouseMoveEvent(self, event):
        if self.resizing and self.resize_edge:
            delta = event.globalPosition().toPoint() - self.drag_start
            geo = QRect(self.original_geometry)
            
            if 'left' in self.resize_edge:
                geo.setLeft(geo.left() + delta.x())
            if 'right' in self.resize_edge:
                geo.setRight(geo.right() + delta.x())
            if 'top' in self.resize_edge:
                geo.setTop(geo.top() + delta.y())
            if 'bottom' in self.resize_edge:
                geo.setBottom(geo.bottom() + delta.y())
                
            # Minimum size
            if geo.width() > 30 and geo.height() > 30:
                self.setGeometry(geo)
                
        elif self.dragging:
            delta = event.globalPosition().toPoint() - self.drag_start
            new_pos = self.pos() + delta
            self.move(new_pos)
            self.drag_start = event.globalPosition().toPoint()
        else:
            self.update_cursor(event.pos())
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_edge = None
            
    def mouseDoubleClickEvent(self, event):
        """Double-click to remove"""
        self.close()


class BoxCreationOverlay(QWidget):
    """Fullscreen overlay for creating and positioning boxes"""
    boxes_confirmed = pyqtSignal(list)  # List of (rect, is_capture) tuples
    
    def __init__(self, is_capture=True):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | 
                        Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        
        self.is_capture = is_capture
        self.boxes = []
        
        # Create first box
        self.create_new_box()
        
        self.showFullScreen()
        
    def create_new_box(self):
        """Create a new draggable box"""
        box = DraggableBox(is_capture=self.is_capture, parent=self)
        self.boxes.append(box)
        box.raise_()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Dark semi-transparent background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        
        # Instructions
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Sans", 14, QFont.Weight.Bold)
        painter.setFont(font)
        
        instructions = [
            f"Creating {'CAPTURE' if self.is_capture else 'EXCLUDE'} Regions",
            "",
            "• Drag boxes to position them",
            "• Resize from edges and corners",
            "• Press SPACE to add another box",
            "• Press ENTER to confirm all boxes",
            "• Press ESC to cancel"
        ]
        
        y = 50
        for line in instructions:
            painter.drawText(QRect(50, y, self.width()-100, 30), 
                           Qt.AlignmentFlag.AlignLeft, line)
            y += 35
            
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Confirm all boxes
            confirmed_boxes = []
            for box in self.boxes:
                confirmed_boxes.append((box.geometry(), self.is_capture))
            self.boxes_confirmed.emit(confirmed_boxes)
            self.close_all()
            
        elif event.key() == Qt.Key.Key_Space:
            # Create another box
            self.create_new_box()
            self.update()
            
        elif event.key() == Qt.Key.Key_Escape:
            # Cancel
            self.close_all()
            
        elif event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            # Delete last box
            if len(self.boxes) > 1:
                self.boxes[-1].close()
                self.boxes.pop()
                self.update()
                
    def close_all(self):
        """Close all boxes and this overlay"""
        for box in self.boxes:
            box.close()
        self.close()


class SettingsDialog(QDialog):
    """Settings dialog for languages and models"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(400, 350)
        
        layout = QVBoxLayout()
        
        # Languages
        lang_group = QGroupBox("Languages")
        lang_layout = QVBoxLayout()
        
        src_layout = QHBoxLayout()
        src_layout.addWidget(QLabel("Source Language:"))
        self.source_lang = QComboBox()
        self.source_lang.addItems(["Japanese", "Chinese", "Korean", "English", 
                                   "Spanish", "French", "German", "Auto-detect"])
        src_layout.addWidget(self.source_lang)
        lang_layout.addLayout(src_layout)
        
        tgt_layout = QHBoxLayout()
        tgt_layout.addWidget(QLabel("Target Language:"))
        self.target_lang = QComboBox()
        self.target_lang.addItems(["English", "Spanish", "French", "German", 
                                   "Japanese", "Chinese", "Korean"])
        tgt_layout.addWidget(self.target_lang)
        lang_layout.addLayout(tgt_layout)
        
        lang_group.setLayout(lang_layout)
        layout.addWidget(lang_group)
        
        # Model selection
        model_group = QGroupBox("Model")
        model_layout = QVBoxLayout()
        
        model_h_layout = QHBoxLayout()
        model_h_layout.addWidget(QLabel("Ollama Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["qwen2-vl:7b", "qwen2-vl:2b", "llava", "bakllava"])
        self.model_combo.setEditable(True)
        model_h_layout.addWidget(self.model_combo)
        model_layout.addLayout(model_h_layout)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # Capture settings
        capture_group = QGroupBox("Capture Settings")
        capture_layout = QVBoxLayout()
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Update Interval (seconds):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 30)
        self.interval_spin.setValue(3)
        interval_layout.addWidget(self.interval_spin)
        capture_layout.addLayout(interval_layout)
        
        self.auto_capture = QCheckBox("Auto-capture on interval")
        capture_layout.addWidget(self.auto_capture)
        
        capture_group.setLayout(capture_layout)
        layout.addWidget(capture_group)
        
        # Hotkeys info
        hotkey_group = QGroupBox("Hotkeys")
        hotkey_layout = QVBoxLayout()
        hotkey_layout.addWidget(QLabel("Ctrl+Shift+C - Add Capture Regions"))
        hotkey_layout.addWidget(QLabel("Ctrl+Shift+E - Add Exclude Regions"))
        hotkey_layout.addWidget(QLabel("Ctrl+Shift+T - Translate Now"))
        hotkey_layout.addWidget(QLabel("Ctrl+Shift+R - Toggle Region Boxes"))
        hotkey_layout.addWidget(QLabel("Ctrl+Shift+X - Clear All Overlays"))
        hotkey_group.setLayout(hotkey_layout)
        layout.addWidget(hotkey_group)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        
    def get_settings(self):
        return {
            'source_lang': self.source_lang.currentText(),
            'target_lang': self.target_lang.currentText(),
            'model': self.model_combo.currentText(),
            'interval': self.interval_spin.value(),
            'auto_capture': self.auto_capture.isChecked()
        }


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translation Tool")
        self.resize(400, 250)
        
        # State
        self.capture_boxes = []
        self.exclude_boxes = []
        self.overlays = []
        self.regions_visible = True
        self.settings = {
            'source_lang': 'Japanese',
            'target_lang': 'English',
            'model': 'qwen2-vl:7b',
            'interval': 3,
            'auto_capture': False
        }
        
        # Timer for auto-capture
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_and_translate)
        
        self.init_ui()
        self.setup_hotkeys()
        
    def setup_hotkeys(self):
        """Setup global hotkeys"""
        # Ctrl+Shift+C - Add capture region
        shortcut_capture = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        shortcut_capture.activated.connect(self.create_capture_regions)
        
        # Ctrl+Shift+E - Add exclude region
        shortcut_exclude = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        shortcut_exclude.activated.connect(self.create_exclude_regions)
        
        # Ctrl+Shift+T - Translate now
        shortcut_translate = QShortcut(QKeySequence("Ctrl+Shift+T"), self)
        shortcut_translate.activated.connect(self.capture_and_translate)
        
        # Ctrl+Shift+R - Toggle region boxes
        shortcut_toggle = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        shortcut_toggle.activated.connect(self.toggle_region_boxes)
        
        # Ctrl+Shift+X - Clear overlays
        shortcut_clear = QShortcut(QKeySequence("Ctrl+Shift+X"), self)
        shortcut_clear.activated.connect(self.clear_overlays)
        
    def init_ui(self):
        central = QWidget()
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Real-time Game Translation Tool")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Buttons
        btn_layout = QVBoxLayout()
        
        select_btn = QPushButton("Add Capture Regions (Ctrl+Shift+C)")
        select_btn.clicked.connect(self.create_capture_regions)
        btn_layout.addWidget(select_btn)
        
        exclude_btn = QPushButton("Add Exclude Regions (Ctrl+Shift+E)")
        exclude_btn.clicked.connect(self.create_exclude_regions)
        btn_layout.addWidget(exclude_btn)
        
        toggle_btn = QPushButton("Toggle Region Boxes (Ctrl+Shift+R)")
        toggle_btn.clicked.connect(self.toggle_region_boxes)
        btn_layout.addWidget(toggle_btn)
        
        capture_btn = QPushButton("Capture & Translate Now (Ctrl+Shift+T)")
        capture_btn.clicked.connect(self.capture_and_translate)
        capture_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        btn_layout.addWidget(capture_btn)
        
        clear_overlays_btn = QPushButton("Clear All Overlays (Ctrl+Shift+X)")
        clear_overlays_btn.clicked.connect(self.clear_overlays)
        btn_layout.addWidget(clear_overlays_btn)
        
        clear_regions_btn = QPushButton("Clear All Regions")
        clear_regions_btn.clicked.connect(self.clear_regions)
        btn_layout.addWidget(clear_regions_btn)
        
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.show_settings)
        btn_layout.addWidget(settings_btn)
        
        layout.addLayout(btn_layout)
        
        # Status
        self.status_label = QLabel("Ready - Press buttons or use hotkeys to get started")
        self.status_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        central.setLayout(layout)
        self.setCentralWidget(central)
        
    def create_capture_regions(self):
        """Open box creation overlay for capture regions"""
        self.box_overlay = BoxCreationOverlay(is_capture=True)
        self.box_overlay.boxes_confirmed.connect(self.add_confirmed_boxes)
        
    def create_exclude_regions(self):
        """Open box creation overlay for exclude regions"""
        self.box_overlay = BoxCreationOverlay(is_capture=False)
        self.box_overlay.boxes_confirmed.connect(self.add_confirmed_boxes)
        
    def add_confirmed_boxes(self, boxes):
        """Add confirmed boxes as fixed region boxes"""
        for rect, is_capture in boxes:
            box = RegionBox(rect, is_capture=is_capture)
            if is_capture:
                self.capture_boxes.append(box)
            else:
                self.exclude_boxes.append(box)
        
        capture_count = sum(1 for _, is_cap in boxes if is_cap)
        exclude_count = sum(1 for _, is_cap in boxes if not is_cap)
        
        if capture_count > 0:
            self.status_label.setText(f"Added {capture_count} capture region(s). Total: {len(self.capture_boxes)}")
        else:
            self.status_label.setText(f"Added {exclude_count} exclude region(s). Total: {len(self.exclude_boxes)}")
        
    def toggle_region_boxes(self):
        """Show/hide region boxes"""
        self.regions_visible = not self.regions_visible
        
        for box in self.capture_boxes + self.exclude_boxes:
            if self.regions_visible:
                box.show()
            else:
                box.hide()
                
        status = "shown" if self.regions_visible else "hidden"
        self.status_label.setText(f"Region boxes {status}")
        
    def clear_regions(self):
        for box in self.capture_boxes + self.exclude_boxes:
            box.close()
        self.capture_boxes.clear()
        self.exclude_boxes.clear()
        self.status_label.setText("All regions cleared")
        
    def clear_overlays(self):
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()
        self.status_label.setText("All overlays cleared")
        
    def capture_and_translate(self):
        """Capture screen regions and send for translation"""
        if not self.capture_boxes:
            self.status_label.setText("No capture regions defined!")
            return
            
        self.status_label.setText("Capturing and translating...")
        
        screen = QGuiApplication.primaryScreen()
        
        for capture_box in self.capture_boxes:
            region = capture_box.geometry()
            
            # Check if region overlaps with exclude regions
            should_skip = False
            for exclude_box in self.exclude_boxes:
                if region.intersects(exclude_box.geometry()):
                    should_skip = True
                    break
                    
            if should_skip:
                continue
                
            # Capture screenshot
            pixmap = screen.grabWindow(0, region.x(), region.y(), 
                                      region.width(), region.height())
            
            # Convert to QImage for processing
            image = pixmap.toImage()
            
            # Start translation worker
            worker = TranslationWorker(
                image, region,
                self.settings['source_lang'],
                self.settings['target_lang'],
                self.settings['model']
            )
            worker.translation_ready.connect(self.show_translation)
            worker.finished.connect(lambda: self.status_label.setText("Ready"))
            worker.start()
            
            # Keep reference to prevent garbage collection
            if not hasattr(self, 'workers'):
                self.workers = []
            self.workers.append(worker)
            
    def show_translation(self, text, rect):
        """Display translation overlay"""
        overlay = TranslationOverlay(text, rect, None)
        self.overlays.append(overlay)
        
    def show_settings(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self)
        
        # Set current values
        dialog.source_lang.setCurrentText(self.settings['source_lang'])
        dialog.target_lang.setCurrentText(self.settings['target_lang'])
        dialog.model_combo.setCurrentText(self.settings['model'])
        dialog.interval_spin.setValue(self.settings['interval'])
        dialog.auto_capture.setChecked(self.settings['auto_capture'])
        
        if dialog.exec():
            self.settings = dialog.get_settings()
            
            # Update timer
            if self.settings['auto_capture']:
                self.capture_timer.start(self.settings['interval'] * 1000)
                self.status_label.setText(f"Auto-capture enabled ({self.settings['interval']}s)")
            else:
                self.capture_timer.stop()
                self.status_label.setText("Auto-capture disabled")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
