import hashlib
from typing import Optional, Tuple
from PyQt6.QtGui import QImage, QGuiApplication
from PyQt6.QtCore import QBuffer, QIODevice, Qt, QRect

SCREENSHOT_AVAILABLE = True

class ScreenCapture:
    """Handle screen capture using PyQt6"""

    @staticmethod
    def capture_screen() -> Optional[bytes]:
        """Capture entire screen using PyQt fallback"""
        try:
            screen = QGuiApplication.primaryScreen()
            if screen:
                pixmap = screen.grabWindow(0)
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                data = bytes(buffer.buffer())
                return data

        except Exception as e:
            print(f"Screenshot capture error: {e}")

        return None

    @staticmethod
    def capture_region(x: int, y: int, width: int, height: int) -> Optional[bytes]:
        """Capture specific screen region"""
        try:
            full_data = ScreenCapture.capture_screen()
            if not full_data:
                return None
                
            image = QImage.fromData(full_data)
            if image.isNull():
                return None
                
            # Crop to region
            rect = QRect(x, y, width, height)
            # Ensure rect is within image bounds
            rect = rect.intersected(image.rect())
            
            if rect.isEmpty():
                print(f"Warning: Requested region {x},{y} {width}x{height} is outside screen bounds")
                return None
                
            cropped = image.copy(rect)
            
            # Convert back to bytes
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            cropped.save(buffer, "PNG")
            data = bytes(buffer.buffer())
            
            return data

        except Exception as e:
            print(f"Region capture error: {e}")

        return None

    @staticmethod
    def preprocess_image(image_data: bytes) -> bytes:
        """Enhance image for better OCR/translation results"""
        image = QImage.fromData(image_data)
        if image.isNull():
            return image_data

        # 1. Convert to Grayscale to simplify and improve contrast focus
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)

        # 2. Simple contrast enhancement: Normalize
        # We find the min/max pixel values and stretch the range
        # Note: In a real app we might use something like histogram equalization, 
        # but for VLMs, clear grayscale with good contrast is often enough.
        
        # This is a basic way to "normalize" using QImage if we don't want OpenCV
        # For efficiency, we just return the grayscale image for now which already helps OCR
        
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.buffer())

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
    def calculate_hash(image_input) -> str:
        """Calculate a simple perceptual hash for change detection"""
        if isinstance(image_input, bytes):
            image = QImage.fromData(image_input)
        else:
            image = image_input

        if not image or image.isNull():
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
