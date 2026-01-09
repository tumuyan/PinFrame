# PinFrame | 定帧

[English](./README_EN.md) |  [中文说明](./README.md)

PinFrame is a distinctive sprite sequence tool. While it may not replace a full animation suite for creating assets from scratch, it excels at previewing, fine-tuning, and consolidating sprite sequences or sprite sheets. It is particularly effective for managing assets with inconsistent dimensions or processing AI-generated character sequences.

PinFrame is also a GIF processing tool: supporting frame decomposition, cropping, merging, resolution adjustment, speed adjustment, and frame removal.

## Core Features

*   **Precise Transformations**: Supports per-frame translation, scaling, rotation, and mirroring, with independent X/Y scaling ratios.
*   **Multi-Dimensional Anchors**: Four anchor modes available: canvas center, image center, custom canvas position, and custom image-following position, ensuring complete control over transformation pivots.
*   **Onion Skinning**: Configurable multi-frame overlays for perfect animation continuity.
*   **Reference Frame System**: Lock any frame as a foreground or background reference; includes smart mutual exclusion with onion skinning.
*   **Flexible Interaction**: Supports wheel mode toggle (zoom view or scale image).
*   **Flexible Preview**: Forward and reverse playback for global or selected frame ranges, custom playback speed. Multi-selected frames display as instant overlays for batch adjustments.
*   **Sprite Sheet Processing**: Built-in slicing tool to extract sequences from sprite sheets, and direct sprite sheet export support.
*   **Professional Export**: Supports custom frame ranges, custom background colors, and exporting as PNG sequences, compact sprite sheets, or GIFs.
*   **Batch Operations**: Batch copy/paste properties, duplicate frames, remove frames, and reverse frame order.
*   **Lossless Workflow**: Projects store data in JSON without duplicating resources or sacrificing asset precision due to import scaling.
*   **Project Portability**: Quickly copy assets to the project directory with automatic relative path management; assets remain intact when moving projects.

## Future Plans

*   **Video Import/Export**: Precise preview and frame extraction from videos is necessary, but it will significantly increase the application size.
*   **Basic Background Removal**: Useful for better asset previews, though it may not be possible to integrate a highly effective solution.

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
