# 开发笔记
## 在cnb默认开发环境中setup

### 安装python

```
apt install python3 python3-venv pip
```

### 安装QT需要的GUI相关的包

Ubuntu/Debian:

```
apt-get update
apt-get install \
    libgl1-mesa-glx \
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
```    
CentOS/RHEL/Fedora:

```
sudo dnf install \
    mesa-libGL \
    mesa-libEGL \
    glib2 \
    libxkbcommon-x11 \
    libxcb-cursor \
    libxcb-icccm \
    libxcb-keysyms \
    libxcb-randr \
    libxcb-shape \
    libxcb-xfixes \
    libxcb-xinerama \
    fontconfig \
    libXrender \
    libXi
```

## 远程测试
### 激活虚拟环境
```
python3 -m venv venv
source venv/bin/activate
```
### 测试能否启动程序
安装 Xvfb：
Ubuntu/Debian: `apt-get install xvfb`
CentOS/RHEL: `sudo yum install xorg-x11-server-Xvfb`
运行程序：
使用 xvfb-run 工具包装你的 Python 命令。
```
# -a 表示自动寻找一个可用的显示端口号
xvfb-run -a python main.py
```

验证结果：
如果程序启动并未报错（没有出现 cannot connect to display），说明 GUI 初始化成功。
你可以配合截图工具（如 scrot 或 imagemagick）在虚拟环境中截图，验证界面是否渲染正确（见后文进阶技巧）。
``
./dev/screenshot.sh
``

查看生成的 tmp_screenshot.png 即可确认界面是否正常。

### 在novnc中显示GUI
见 [novnc文档](./novnc.md)

## 分支管理
1. 添加 github remote
```
git remote add github https://github.com/tumuyan/PinFrame.git
```
2. 拉取 github 的 main 分支
```
git fetch github main
```

3. 强制重置本地 main 分支到 github/main
```
git reset --hard github/main
```

## 错误处理

### 中文显示为空心方块

如果应用程序中的中文显示为空心方块，说明系统中没有安装中文字体。

解决方案：

**方法 1: 使用字体安装脚本**
```bash
chmod +x install_fonts.sh
./install_fonts.sh
```

**方法 2: 手动安装中文字体**
```bash
apt-get update
apt-get install -y fonts-noto-cjk fonts-wqy-zenhei fontconfig
fc-cache -fv
```

**验证字体**

```bash
fc-list :lang=zh-cn
```


安装完成后，重启应用程序即可正常显示中文。