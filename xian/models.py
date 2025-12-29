from dataclasses import dataclass
from enum import Enum

class TranslationMode(Enum):
    FULL_SCREEN = "full_screen"
    REGION_SELECT = "region_select"

@dataclass
class TranslationRegion:
    """Represents a region to be translated"""
    x: int
    y: int
    width: int
    height: int
    name: str = ""
    enabled: bool = True

@dataclass
class TranslationResult:
    """Result from translation API"""
    translated_text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0
