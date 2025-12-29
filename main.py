#!/usr/bin/env python3
"""
Xian - Real-time Video Game Translation Overlay
A PyQt6-based translation overlay for Linux Wayland KDE Plasma
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from xian.gui import MainWindow
from xian.capture import SCREENSHOT_AVAILABLE

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("xian.png"))

    # Check for required dependencies
    if not SCREENSHOT_AVAILABLE:
        print("Warning: Screenshot dependencies not available")

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
