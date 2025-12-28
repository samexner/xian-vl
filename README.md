# xian-vl
<img width="512" height="512" alt="xian" src="https://github.com/user-attachments/assets/f8db003f-38ba-4282-9293-427a358f8119" />

A real-time game translation overlay for Linux that uses local AI (Ollama + Qwen3-VL) to translate text from games and applications. Work-in-progress.

## Features

- **Real-time Translation**: Automatically captures and translates text from your screen.
- **Two Translation Modes**:
    - **Full Screen**: Analyzes the entire screen and places translated text boxes over the original content.
    - **Region Selection**: Allows you to define specific areas of the screen for targeted translation.
- **Click-Through Overlay**: The translation overlay is transparent to mouse input, allowing you to play games or browse websites uninterrupted.
- **Clean Screenshots**: Automatically hides the overlay during screen capture to ensure the LLM sees the original game content.
- **Ollama Integration**:
    - Supports custom API URLs and models.
    - Automatically fetches and lists available models from your Ollama server.
    - Provides helpful troubleshooting for missing models.
- **Persistent Settings**: Saves your configuration, including API settings, languages, intervals, and custom regions.
- **Customizable Appearance**: Adjustable overlay opacity.

## Requirements

- **Linux with Wayland** (Tested on KDE Plasma).
- **Python 3.10+**
- **PyQt6**
- **Ollama** running locally or on your network.
- **Vision Model**: Recommended `qwen3-vl:8b-instruct` or similar.
- **Screenshot Tools**: `spectacle` (KDE) or `grim`.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/xian.git
   cd xian
   ```

2. Install dependencies:
   ```bash
   pip install PyQt6 requests
   ```

3. Ensure you have Ollama installed and the vision model pulled:
   ```bash
   ollama pull qwen3-vl:8b-instruct
   ```

## Usage

1. Start the application:
   ```bash
   python main.py
   ```

2. **Configure API**:
   - Go to the **Settings** tab.
   - Enter your **Ollama API URL** (default: `http://localhost:11434`).
   - Select the desired **Model** from the dropdown (it will populate once connected).

3. **Select Mode**:
   - In the **General** tab, choose between **Full Screen Analysis** or **Region Selection**.

4. **Define Regions (Optional)**:
   - Go to the **Regions** tab to add specific areas for translation.

5. **Start Translating**:
   - Click the **Start Translation** button.
   - The overlay will appear, and translations will be updated periodically based on the set interval.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

## License

GNU General Public License v3.0 - See LICENSE file for details.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

## Acknowledgments

- Built with PyQt6
- Powered by Ollama and Qwen3-VL
- Inspired by the need for accessible game translation tools on Linux
