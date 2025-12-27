# xian-vl
<img width="512" height="512" alt="xian" src="https://github.com/user-attachments/assets/f8db003f-38ba-4282-9293-427a358f8119" />

A real-time game translation overlay for Linux that uses local AI (Ollama + Qwen3-VL) to translate text from games and applications. Work-in-progress.

## Features

- 🎮 **Real-time translation overlays** - Translated text appears directly over the original
- 🖼️ **Flexible region selection** - Define multiple capture and exclude regions
- 🔄 **Drag and resize** - Easily adjust regions and overlays on the fly
- ⌨️ **Hotkey support** - Control everything with keyboard shortcuts
- 🌍 **Multiple languages** - Supports Japanese, Chinese, Korean, and more
- 🔒 **100% local** - All processing happens on your machine via Ollama
- 💻 **Wayland & X11** - Works on modern Linux desktop environments including KDE Plasma

## Requirements

- Python 3.8+
- PyQt6
- Ollama with a vision model (Qwen3-VL recommended)
- Linux with Wayland or X11

## Installation

### 1. Install Python dependencies

```bash
pip install PyQt6 requests pillow
```

### 2. Install and setup Ollama

```bash
# Install Ollama (see https://ollama.ai)
curl -fsSL https://ollama.com/install.sh | sh

# Pull Qwen3-VL model
ollama pull qwen2-vl:7b
```

### 3. Run the application

```bash
python game_translator.py
```

## Usage

### Quick Start

1. **Launch the application**
2. **Add capture regions** - Click "Add Capture Regions" or press `Ctrl+Shift+C`
   - Green boxes appear in the center of your screen
   - Drag them to position over game text
   - Resize by dragging edges/corners
   - Press `SPACE` to add more boxes
   - Press `ENTER` to confirm all boxes
3. **Translate** - Press `Ctrl+Shift+T` or click "Capture & Translate Now"
4. **Adjust overlays** - Drag translation overlays to reposition them

### Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+C` | Add capture regions |
| `Ctrl+Shift+E` | Add exclude regions |
| `Ctrl+Shift+T` | Translate now |
| `Ctrl+Shift+R` | Toggle region boxes visibility |
| `Ctrl+Shift+X` | Clear all translation overlays |

### Region Creation Mode

When creating regions:
- **Drag** - Move boxes around
- **Resize** - Grab edges or corners to resize
- **SPACE** - Add another box
- **ENTER** - Confirm all boxes
- **ESC** - Cancel
- **DELETE/BACKSPACE** - Remove last box

### Settings

Access settings to configure:
- Source and target languages
- Ollama model selection
- Auto-capture interval
- Enable/disable auto-capture mode

## How It Works

1. You define screen regions where text appears in your game
2. The tool captures screenshots of those regions
3. Images are sent to Qwen3-VL (running locally via Ollama)
4. The AI extracts and translates the text
5. Translations appear as semi-transparent overlays on your screen

## Supported Languages

**Source Languages:**
- Chinese
- Japanese
- Korean
- English
- Spanish
- French
- German
- Auto-detect

**Target Languages:**
- English
- Spanish
- French
- German
- Japanese
- Chinese
- Korean

## Tips

- **Hide region boxes while gaming** - Press `Ctrl+Shift+R` to hide boxes (they remain active)
- **Exclude UI elements** - Use exclude regions to skip menus, health bars, etc.
- **Adjust overlay positions** - Double-click translation overlays to remove them
- **Auto-capture mode** - Enable in settings for continuous translation
- **Multiple regions** - Create several capture regions for different text areas

## Troubleshooting

### Ollama connection issues
Make sure Ollama is running:
```bash
ollama serve
```

### Model not found
Pull the model first:
```bash
ollama pull qwen2-vl:7b
```

### Wayland permission issues
Some Wayland compositors may require additional permissions for screen capture. Check your desktop environment's screen capture settings.

### Translations not appearing
- Verify capture regions are positioned correctly over text
- Check that regions aren't overlapping with exclude regions
- Ensure text is clearly visible in the captured area
- Try a different model in settings if translations are poor

## Alternative Models

While Qwen3-VL is recommended, you can try other vision models:

```bash
ollama pull llava
ollama pull bakllava
```

Select your preferred model in the Settings dialog.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

## License

GNU General Public License v3.0 - See LICENSE file for details
This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

## Acknowledgments

- Built with PyQt6
- Powered by Ollama and Qwen3-VL
- Inspired by the need for accessible game translation tools on Linux
