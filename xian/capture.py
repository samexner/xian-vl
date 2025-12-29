import os
import shutil
import subprocess
import hashlib
from typing import Optional, Tuple
from PyQt6.QtGui import QImage, QGuiApplication
from PyQt6.QtCore import QBuffer, QIODevice, Qt

try:
    # Try to import screenshot capability for Wayland
    import subprocess
    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False

class ScreenCapture:
    """Handle screen capture on Wayland"""

    @staticmethod
    def capture_screen() -> Optional[bytes]:
        """Capture entire screen using available tools (grim, spectacle, or PyQt fallback)"""
        temp_file = '/tmp/xian_screenshot.png'
        try:
            # Ensure fresh capture
            if os.path.exists(temp_file):
                os.remove(temp_file)

            # 1. Try grim (Native Wayland)
            if shutil.which('grim'):
                result = subprocess.run([
                    'grim', temp_file
                ], capture_output=True, timeout=5)
                
                if result.returncode == 0 and os.path.exists(temp_file):
                    with open(temp_file, 'rb') as f:
                        data = f.read()
                        if len(data) > 0:
                            print(f"Captured screen using grim: {len(data)} bytes")
                            return data

            # 2. Try spectacle (KDE's tool)
            if shutil.which('spectacle'):
                # Try spectacle background mode
                result = subprocess.run([
                    'spectacle', '-b', '-n', '-o', temp_file
                ], capture_output=True, timeout=5)

                if result.returncode == 0 and os.path.exists(temp_file):
                    with open(temp_file, 'rb') as f:
                        data = f.read()
                        if len(data) > 0:
                            print(f"Captured screen using spectacle: {len(data)} bytes")
                            return data

            # 3. Last resort: PyQt fallback (may not work perfectly on all Wayland compositors)
            print("No native screenshot tools found, trying PyQt fallback...")
            screen = QGuiApplication.primaryScreen()
            if screen:
                pixmap = screen.grabWindow(0)
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                data = bytes(buffer.buffer())
                print(f"Captured screen using PyQt fallback: {len(data)} bytes")
                return data

        except Exception as e:
            print(f"Screenshot capture error: {e}")

        return None

    @staticmethod
    def capture_region(x: int, y: int, width: int, height: int) -> Optional[bytes]:
        """Capture specific screen region using available tools"""
        temp_file = '/tmp/xian_region.png'
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)

            # 1. Try grim for region capture
            if shutil.which('grim'):
                result = subprocess.run([
                    'grim', '-g', f'{x},{y} {width}x{height}', temp_file
                ], capture_output=True, timeout=5)

                if result.returncode == 0 and os.path.exists(temp_file):
                    with open(temp_file, 'rb') as f:
                        data = f.read()
                        if len(data) > 0:
                            print(f"Captured region ({width}x{height}) using grim: {len(data)} bytes")
                            return data

            # 2. Try spectacle for region capture
            if shutil.which('spectacle'):
                result = subprocess.run([
                    'spectacle', '-b', '-n', '-r', '-o', temp_file
                ], capture_output=True, timeout=5)
                # Note: spectacle -r usually requires user interaction unless configured.
                # KDE/Wayland security often prevents non-interactive region capture.
                
                if result.returncode == 0 and os.path.exists(temp_file):
                    with open(temp_file, 'rb') as f:
                        data = f.read()
                        if len(data) > 0:
                            print(f"Captured region using spectacle: {len(data)} bytes")
                            return data

            # 3. PyQt fallback for region
            print("Using PyQt fallback for region capture...")
            screen = QGuiApplication.primaryScreen()
            if screen:
                pixmap = screen.grabWindow(0, x, y, width, height)
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                data = bytes(buffer.buffer())
                print(f"Captured region ({width}x{height}) using PyQt fallback: {len(data)} bytes")
                return data

        except Exception as e:
            print(f"Region capture error: {e}")

        return None

    @staticmethod
    def compress_image(image_data: bytes, quality: int = 50) -> Tuple[bytes, int, int]:
        """Compress image to JPEG and return (data, width, height)"""
        # 1. Load the image from provided data
        image = QImage.fromData(image_data)
        
        if image.isNull():
            print("Warning: Failed to load image for compression")
            return image_data, 0, 0

        # 2. Convert to RGB888 for consistent JPEG compression
        image = image.convertToFormat(QImage.Format.Format_RGB888)

        # 3. Save with compression to memory buffer
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "JPG", quality)
        
        return bytes(buffer.buffer()), image.width(), image.height()

    @staticmethod
    def calculate_hash(image_data: bytes) -> str:
        """Calculate a simple perceptual hash for change detection"""
        image = QImage.fromData(image_data)
        if image.isNull():
            return ""
        
        # Downsample to a very small size to ignore minor noise/flicker
        small = image.scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        small = small.convertToFormat(QImage.Format.Format_Grayscale8)
        
        bits = []
        for y in range(16):
            for x in range(16):
                # Using a simple bitmask based on average pixel value
                bits.append(str(small.pixelColor(x, y).red()))
        
        return hashlib.md5(",".join(bits).encode()).hexdigest()
