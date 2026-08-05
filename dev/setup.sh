#!/bin/bash
apt-get update
apt install -y python3 python3-venv pip
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

apt-get install -y \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    libxkbcommon-x11-0 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libfontconfig1 \
    libxrender1 \
    libxi6