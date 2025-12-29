# PinFrame | 定帧

[English](./README_EN.md) |  [中文说明](./README.md)

PinFrame is a distinctive sprite sequence tool. While it may not replace a full animation suite for creating assets from scratch, it excels at previewing, fine-tuning, and consolidating sprite sequences or sprite sheets. It is particularly effective for managing assets with inconsistent dimensions or processing AI-generated character sequences.

## Core Features

*   **Precise Alignment**: Supports per-frame translation and scaling.
*   **Onion Skinning**: Configurable multi-frame overlays for perfect animation continuity.
*   **Reference Frame System**: Lock any frame as a foreground or background reference; includes smart mutual exclusion with onion skinning.
*   **Flexible Preview**: Forward and reverse playback, custom FPS, and instant overlay preview for multiple selected frames.
*   **Sprite Sheet Processing**: Built-in slicing tool to recover sequences from existing sprite sheets.
*   **Professional Export**: Supports custom frame ranges, custom background colors, and exporting as either PNG sequences or compact sprite sheets.
*   **Batch Operations**: Batch copy/paste properties, duplicate, remove, and reverse frame order.
*   **Lossless Workflow**: Data is stored in JSON; the tool does not duplicate resources or sacrifice precision due to import scaling.
*   **Project Portability**: Easily consolidate external assets into the project directory with automatic relative path management.

## Running & Development

### Prerequisites
*   Python 3.11+
*   PyQt6
*   Pillow

### Quick Start
```powershell
# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

## Packaging

The project includes a pre-configured PyInstaller spec file for building standalone Windows executables:

```powershell
# Install packager
pip install pyinstaller

# Run build
pyinstaller PinFrame.spec
```

The resulting executable will be located in the `dist/PinFrame` directory.
