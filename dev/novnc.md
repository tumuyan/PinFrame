# noVNC 远程 GUI 调试配置

此配置用于在无桌面环境的 Linux 系统上通过浏览器远程运行和调试 PyQt6 GUI 程序。

## 架构说明

```
浏览器 (noVNC 客户端)
    ↓ WebSocket (端口 6080)
websockify (代理)
    ↓ TCP (端口 5900)
x11vnc (VNC 服务器)
    ↓
Xvfb (虚拟显示器 :99)
    ↓
PyQt6 应用程序
```

## 快速开始

### 1. 安装依赖

```bash
chmod +x novnc_install.sh
sudo ./novnc_install.sh
```

这将安装以下软件包:
- `xvfb` - 虚拟显示服务器
- `x11vnc` - VNC 服务器
- `python3-websockify` - WebSocket 到 TCP 的转换器
- `novnc` - Web 端 VNC 客户端
- `net-tools` - 网络工具

### 2. 启动服务

```bash
chmod +x novnc_start.sh
./novnc_start.sh
```

这会自动启动:
1. Xvfb 虚拟显示器 (分辨率 1280x720x24)
2. x11vnc 服务器 (端口 5900)
3. websockify 代理 (端口 6080)
4. PyQt6 应用程序

### 3. 访问 GUI

打开浏览器访问:
- **本地访问**: http://localhost:6080/vnc.html
- **远程访问**: http://<服务器IP>:6080/vnc.html

### 4. 停止服务

```bash
chmod +x novnc_stop.sh
./novnc_stop.sh
```

## 配置说明

### novnc_start.sh

启动脚本包含以下配置:

```bash
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
```

- `:99` - 显示器编号
- `1280x720x24` - 分辨率和颜色深度
- `-ac` - 禁用访问控制
- `+extension GLX` - 启用 OpenGL 扩展
- `+render` - 启用渲染扩展
- `-noreset` - 最后一个客户端断开后不重置

如果需要更高分辨率, 修改为:
```bash
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
```

### 端口配置

- **6080** - noVNC/WebSocket 端口 (浏览器访问)
- **5900** - VNC 端口 (内部使用)

如需修改端口, 同时修改两个脚本:
- `novnc_start.sh`: 修改 `-rfbport 5900` 和 `6080`
- `novnc_stop.sh`: 无需修改 (使用进程名停止)

## 故障排查

### 1. 无法访问浏览器界面

检查端口是否监听:
```bash
netstat -tlnp | grep -E '6080|5900'
```

检查进程状态:
```bash
ps aux | grep -E 'Xvfb|x11vnc|websockify'
```

查看日志:
```bash
# websockify 日志
journalctl -u websockify  # 如果使用 systemd

# 或者直接查看进程输出
ps aux | grep websockify
```

### 2. 连接时出现 "Connection refused"

确保防火墙允许 6080 端口:
```bash
# Ubuntu/Debian
sudo ufw allow 6080/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=6080/tcp
sudo firewall-cmd --reload
```

### 3. 显示空白或黑屏

~~ 检查 Xvfb 是否正常运行: ~~
```bash
DISPLAY=:99 xeyes &
```
~~ 如果能看到眼睛图标, 说明 Xvfb 正常。~~

手动启动程序
```
export DISPLAY=:99 && python main.py 
```

### 4. 应用程序启动失败

检查 Python 环境:
```bash
cd /workspace
python main.py
```

查看具体错误信息。

## 高级配置

### 使用 systemd 管理服务

创建服务文件 `/etc/systemd/system/novnc.service`:

```ini
[Unit]
Description=noVNC Remote Display Service
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/workspace
Environment="DISPLAY=:99"
ExecStart=/workspace/dev/novnc_start.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable novnc
sudo systemctl start novnc
```

### 调整性能

在浏览器 noVNC 设置中:
- **Quality**: 降低到 6-8 提升性能
- **Compression**: 启用
- **Shared Mode**: 禁用以获得更好性能

### 安全加固

添加密码保护:

修改 `novnc_start.sh`:
```bash
# 使用密码文件
x11vnc -display :99 -forever -rfbauth ~/.vnc/passwd -rfbport 5900 &
```

创建密码:
```bash
mkdir -p ~/.vnc
x11vnc -storepasswd your_password ~/.vnc/passwd
```

## 相关命令

### 手动启动各组件

```bash
# 1. 启动 Xvfb
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &

# 2. 设置环境变量
export DISPLAY=:99

# 3. 启动 x11vnc
x11vnc -display :99 -forever -nopwfb -quiet -rfbport 5900 &

# 4. 启动 websockify
websockify --web=/usr/share/novnc 6080 localhost:5900 &

# 5. 启动应用
python main.py &
```

### 检查状态

```bash
# 查看所有相关进程
ps aux | grep -E 'Xvfb|x11vnc|websockify|main.py'

# 查看端口占用
netstat -tlnp | grep -E '6080|5900'

# 测试 Xvfb
DISPLAY=:99 xterm &
```

## 资源占用

- **内存**: 约 50-100 MB (取决于应用复杂度)
- **CPU**: 低负载时 < 5%, GUI 交互时 10-20%
- **网络**: 取决于分辨率和操作频率, 通常 < 1 Mbps

## 替代方案

如果 noVNC 性能不满足需求, 可以考虑:

1. **X2Go**: 更好的性能, 但需要客户端安装
2. **VNC 直接访问**: 需要配置 SSH 隧道
3. **RDP (xrdp)**: Windows 远程桌面协议, 需要额外配置

## 参考资料

- [noVNC GitHub](https://github.com/novnc/noVNC)
- [x11vnc 手册](https://github.com/LibVNC/x11vnc)
- [Xvfb 文档](https://www.x.org/releases/X11R7.7/doc/man/man1/Xvfb.1.xhtml)
