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

## 运行程序
在测试时，最终运行的程序有三类：

- **Xvfb**（虚拟显示，分辨率由它定）
- **python main.py**（项目开发的 PyQt 程序）
- **x11vnc + websockify**（noVNC 转发，用于浏览器查看界面）

不同场景所需的进程（✓ 表示会运行）：

| 场景 | Xvfb | python main.py | x11vnc + websockify | 说明 |
| --- | --- | --- | --- | --- |
| 只跑 GUI（默认流程） | ✓ | ✓ | | 由 `run_gui.sh` 调用 `start_xvfb.sh` 确保显示就绪，适合无头环境直接运行 |
| GUI + 用浏览器看界面 | ✓ | ✓ | ✓ | VNC 相关由 `novnc_start.sh` 管；浏览器访问 `http://<服务器IP>:6080/vnc.html` |
| 运行并自动截图验证 | ✓ | ✓ | | 由 `screenshot.sh` 复用已有 `:99` 显示并截图（`dev/tmp_screenshot.png`），仅清理自身 python |

> 三种场景的虚拟显示都统一由 `dev/start_xvfb.sh` 提供（分辨率 `1920x1080x24`），避免重复拉起与尺寸不一致。停止相关进程统一用 `停止 noVNC`（`novnc_stop.sh`）。

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

4. 推送本地分支到 github 开发分支
```
git push -u github HEAD:cnb_***
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