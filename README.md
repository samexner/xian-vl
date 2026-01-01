# Xian - Real-time Video Game Translation Overlay

<img width="768" height="768" alt="xian" src="https://github.com/user-attachments/assets/7b9498fd-4786-481f-b2c9-e29632b2ec24" />

Xian is a PyQt6-based translation overlay designed for Linux Wayland (specifically KDE Plasma). It uses local OCR and Transformers-based translation models (like NLLB-200) to provide real-time translations of video games or websites directly on your screen.

## Screenshots

![screenshot1](https://github.com/user-attachments/assets/065e1da7-6cef-4d26-999d-96516769614c)
![Screenshot2](https://github.com/user-attachments/assets/3f9c0c0b-e773-4dac-a6aa-6a7e80cb429c)

## Features

- **Real-time Translation**: Automatically captures and translates text from your screen.
- **Two Translation Modes**:
    - **Full Screen**: Analyzes the entire screen and places translated text boxes over the original content.
    - **Region Selection**: Allows you to define specific areas of the screen for targeted translation.
- **Click-Through Overlay**: The translation overlay is transparent to mouse input, allowing you to play games or browse websites uninterrupted.
- **Direct Transformer Integration**:
    - Uses `facebook/nllb-200-distilled-600M` by default for fast, high-quality local translation.
    - No external API server required (replaces Ollama integration).
- **EasyOCR Integration**:
    - Uses EasyOCR for fast and reliable text detection.
    - Works natively without external screenshot tools.
- **Persistent Settings**:
    - Saves your configuration, including model selection, languages, and custom regions.
- **Customizable Appearance**: Adjustable overlay opacity.

## Requirements

- **Linux with Wayland** (Tested on KDE Plasma).
- **Python 3.10+**
- **PyQt6**
- **EasyOCR**
- **Transformers** & **PyTorch**
- **SentencePiece** (for NLLB tokenizer)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/samexner/xian-vl.git
   cd xian
   ```

2. Install dependencies:
   ```bash
   pip install PyQt6 easyocr transformers torch sentencepiece
   ```

## Usage

1. Start the application:
   ```bash
   python main.py
   ```

2. **Configure Translator**:
   - Go to the **Settings** tab.
   - Select or enter the desired **Model** (default: `facebook/nllb-200-distilled-600M`).
   - The first time you start translation, the model will be downloaded automatically (approx. 600MB for the default model).
   - Note (Helsinki-NLP/opus-mt): When choosing the generic `Helsinki-NLP/opus-mt` option, you must set explicit Source and Target languages (e.g., Japanese → English). The app will auto-resolve and download the correct pair-specific checkpoint (e.g., `Helsinki-NLP/opus-mt-ja-en`). Using `Source=auto` is not supported for opus-mt.

3. **Select Mode**:
   - In the **General** tab, choose between **Full Screen Analysis** or **Region Selection**.

4. **Define Regions (Optional)**:
   - Go to the **Regions** tab to add specific areas for translation.

5. **Start Translating**:
   - Click the **Start Translation** button.
   - The overlay will appear, and translations will be updated periodically.

## License

GNU General Public License v3.0 - See LICENSE file for details.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
