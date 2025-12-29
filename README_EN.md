# PinFrame | 定帧

[English](./README_EN.md) |  [中文说明](./README.md)

PinFrame is a distinctive sprite sequence tool. While it may not replace a full animation suite for creating assets from scratch, it excels at previewing, fine-tuning, and consolidating sprite sequences or sprite sheets. It is particularly effective for managing assets with inconsistent dimensions or processing AI-generated character sequences.

PinFrame is also a GIF processing tool: supporting frame decomposition, cropping, merging, resolution adjustment, speed adjustment, and frame removal.

## Core Features

*   **Precise Alignment**: Supports per-frame translation and scaling.
*   **Onion Skinning**: Configurable multi-frame overlays for perfect animation continuity.
*   **Reference Frame System**: Lock any frame as a foreground or background reference; includes smart mutual exclusion with onion skinning.
*   **Flexible Preview**: Forward and reverse playback, custom FPS, and instant overlay preview for multiple selected frames.
*   **Sprite Sheet & GIF Processing**: Extract frames from sprite sheets or GIFs.
*   **Professional Export**: Supports custom frame ranges, custom background colors, and exporting as PNG sequences, sprite sheets, or high-quality GIFs.
*   **Batch Operations**: Batch copy/paste properties, duplicate, remove, and reverse frame order.
*   **Lossless Workflow**: Data is stored in JSON; the tool does not duplicate resources or sacrifice precision due to import scaling.
*   **Project Portability**: Easily consolidate external assets into the project directory with automatic relative path management.

## Future Plans

*   **Video Import/Export**: Precise preview and frame extraction from videos. However, this may significantly increase the application size.
*   **Basic Background Removal**: Useful for better asset previews, though high-quality integrated implementations are complex.
*   **Rotation**: Adding rotation to the existing scaling and translation system. The challenge lies in maintaining the lossless preview consistency.

## Non-Goals

*   **Pixel-level Editing**.
*   **Layers**: PinFrame will not provide layer functionality, as it would overcomplicate the timeline and deviates from its goal as a fine-tuning tool.

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
