# 在 code-server 中使用

本文档说明了在code-server 中如何利用 `.vscode/tasks.json` 与 `.vscode/launch.json`。

## 1. tasks.json 放在哪

本项目根目录下的 `.vscode/tasks.json` 已定义以下任务：

| label | 作用 | group | 备注 |
| --- | --- | --- | --- |
| `Setup Python` | 执行 `./dev/setup.sh` 初始化 Python 环境 | build | |
| `Setup noVNC` | 执行 `./dev/novnc_install.sh` 安装 noVNC | build | |
| `start-xvfb` | 后台启动虚拟显示 `:99`（`Xvfb`） | （后台任务） | `isBackground: true` |
| `运行 PyQt 应用` | `${workspaceFolder}/venv/bin/python main.py` 运行程序 | build | 无 DISPLAY |
| `运行 PyQt 应用 (noVNC)` | 经 `dev/run_gui.sh` 运行 `main.py`（脚本内调用 `dev/start_xvfb.sh` 确保 Xvfb 就绪并设 `DISPLAY=:99`） | build | `isDefault: true` |
| `截图测试` | 执行 `./dev/screenshot.sh` 截图验证界面 | test | |
| `启动 noVNC` | 后台执行 `./dev/novnc_start.sh`（常驻 x11vnc + websockify） | none | `isBackground: true` |
| `停止 noVNC` | 执行 `./dev/novnc_stop.sh` 清理 noVNC/Xvfb 进程 | none | |

## 2. 如何触发任务

在 code-server 中：

- **运行指定任务**：`Ctrl+Shift+P` → 输入 `Tasks: Run Task` → 选择任务名。
- **默认构建任务**：`Ctrl+Shift+B`，会运行 `group: "build"` 的任务（本项目的 build 任务会让你选择）。
- **作为调试前置任务**：`.vscode/launch.json` 里的 `运行 PyQt 应用 (venv + noVNC)`
  配置的 `"preLaunchTask": "运行 PyQt 应用 (noVNC)"` 会在启动调试（F5）前自动先运行
  该任务（由 `dev/run_gui.sh` 确保虚拟显示就绪），无需依赖 `start-xvfb` 任务。

## 3. code-server 无头环境下的关键点

### 3.1 GUI 必须依赖虚拟显示

code-server 跑在服务器上，没有物理屏幕，PyQt 程序需要虚拟显示才能启动。

- `start-xvfb` 任务启动 `Xvfb :99 -screen 0 1920x1080x24`（见 `dev/start_xvfb.sh`），
  提供虚拟显示（仅供单独管理显示时使用）。
- noVNC 浏览 GUI：先 `Tasks: Run Task` → `启动 noVNC`（后台常驻 x11vnc + websockify），
  再用浏览器访问 `http://<服务器IP>:6080/vnc.html` 查看界面。
- **注意**：`运行 PyQt 应用`（非 noVNC 版）这个 task 没有设置 `DISPLAY`，
  在无头服务器上会报 `cannot connect to display`。如需无头运行 GUI，请改用
  `运行 PyQt 应用 (noVNC)` 任务——它由 `dev/run_gui.sh` 调用 `dev/start_xvfb.sh`
  确保 Xvfb 就绪并设置 `DISPLAY=:99`，不依赖外部的 `start-xvfb` 任务。
- **排错**：`Ctrl+Shift+B` 改动默认任务后，code-server 可能缓存上一次的选择，
  导致仍跑无 DISPLAY 的旧默认任务（终端里任务名不带 `(noVNC)` 后缀即属此情况）。
  验证与处理：
  - 确认虚拟显示是否就绪：`xdpyinfo -display :99 >/dev/null 2>&1 && echo OK || echo NOT running`；
    若 `NOT running`，先 `Tasks: Run Task` → `start-xvfb`（看到打印 `xvfb-ready` 即就绪）。
  - 在命令面板 `Tasks: Run Task` 中手动选择 `运行 PyQt 应用 (noVNC)`（带"默认"标记）；
    若默认未及时更新，重载窗口 / 重启 code-server 让 `tasks.json` 重新加载。
  - Qt 6.5+ 还需系统库 `libxcb-cursor0`（及 `libxcb-xinerama0`），缺失会报
    `could not load the Qt platform plugin "xcb"`，用
    `apt-get install -y libxcb-cursor0 libxcb-xinerama0` 安装。
  - 只要 `xdpyinfo` 显示 `:99 OK` 且任务带 `(noVNC)`，即可正常渲染窗口。

- **如何退出 `运行 PyQt 应用 (noVNC)` 任务（重要）**：该任务默认由 `Ctrl+Shift+B`
  前台运行，`dev/run_gui.sh` 内部用 `setsid` 把 python 放进**独立进程组**，并注册
  `trap cleanup EXIT INT TERM`——所以以下两种退出方式都能可靠杀掉 python 进程树：
  - **`Ctrl+C`**：终端的 SIGINT 会被 `run_gui.sh` 捕获，进而向 python 进程组发
    `TERM` 再兜底 `KILL`，终端打印 `run_gui: terminated` 后任务退出。
  - **`Ctrl+Shift+P` → `Tasks: Terminate Task`**：任务管理器发 SIGTERM 给脚本，
    同样触发 `cleanup` 清理 python。
  - 退出后若仍残留 `:99` 虚拟显示，用 `Tasks: Run Task` → `停止 noVNC`
    （或 `./dev/novnc_stop.sh`）统一清理 x11vnc / websockify / Xvfb。
  - 该任务已配置 `problemMatcher`（`beginsPattern: "run_gui: DISPLAY="`，
    `endsPattern: "run_gui: (exited|terminated)"`），使 code-server 把它当作需显式
    终止的持续任务，正确绑定进程组；`panel` 设为 `shared` + `close: false` 避免
    新建面板丢失焦点导致 `Ctrl+C` 发错终端。
  - 注意：切勿在 `run_gui.sh` 里用 `exec "${PY}" "$@"` 直接替换 shell，否则在
    code-server 的 `bash -c` 包装下 `Ctrl+C` / 任务终止的 SIGINT/SIGTERM 转发不稳定，
    会出现 `^C` 回显但进程不退出的情况（本项目早期版本即因此问题而改为 `setsid` + `trap`）。

- **关于 `DISPLAY` 的注入方式（重要）**：本项目的 code-server / zsh 环境下，
  `tasks.json` 的 `"env": { "DISPLAY": ":99" }` 对 `type: "shell"` 任务**不会可靠注入**
  （实测任务进程内 `DISPLAY` 为空，程序仍报 `could not connect to display`）；
  且把 `DISPLAY=:99` **内联进 `command` 字符串**会被 zsh 当成单个文件路径而报
  `没有那个文件或目录`（exit 127）。因此 `运行 PyQt 应用 (noVNC)` 改用 wrapper 脚本
  `dev/run_gui.sh`，由脚本内部 `export DISPLAY=:99` 后 `exec` venv 的 python 运行
  `main.py`，彻底绕开上述问题。如需调整显示号，可设环境变量 `DISPLAY` 或改脚本。
    若仍报 `could not connect to display`，先确认 `xdpyinfo -display :99` 是否为 OK，
    再检查 `dev/run_gui.sh` 是否带执行权限（`chmod +x dev/run_gui.sh`）。

- **`start-xvfb` 作为 `dependsOn` 不可靠（重要）**：`start-xvfb` 是
  `isBackground: true` 任务，VS Code / code-server 会在其 `problemMatcher` 判定
  "就绪"后管理并可能清理其进程树，导致它拉起的 `Xvfb` 在后续 `run_gui.sh` 运行前
  被一起杀掉；而手动先跑 `novnc_start.sh` 时 Xvfb 已作为独立进程持久存在，所以能成功。
  为避免这种时序/进程清理问题，`运行 PyQt 应用 (noVNC)` **已移除对 `start-xvfb` 的
  `dependsOn`**，改由 `dev/run_gui.sh` 在运行前调用统一的 `dev/start_xvfb.sh`
  （内部用 `setsid` 脱离调用方进程树拉起 Xvfb，参数含 `-ac +extension GLX +render
  -noreset`，与 `novnc_start.sh`、`screenshot.sh` 共用同一来源），确保程序一定能
  投到已就绪的虚拟显示器。
    因此：无需手动预跑 `novnc_start.sh` 或 `start-xvfb`，直接 `Ctrl+Shift+B`
    （或 `Tasks: Run Task` → `运行 PyQt 应用 (noVNC)`）即可。`start-xvfb` 任务保留
    仅供需要单独管理虚拟显示时使用。

### 3.2 解释器一致性

- `launch.json` 用 `${command:python.interpreterPath}`（跟随当前选中的 Python 解释器）。
- `tasks.json` 中 `运行 PyQt 应用` 写死为 `${workspaceFolder}/venv/bin/python`
  （venv 绝对路径）；而 `运行 PyQt 应用 (noVNC)` 的 `command` 是 `./dev/run_gui.sh`，
  python 路径由 `run_gui.sh` 内部解析（优先 `PYTHON` / `VIRTUAL_ENV`，回退
  `${workspaceFolder}/venv/bin/python`）。两者最终都指向 venv，无需再改。
- 若尚未创建 venv，需先运行 `Setup Python` 任务生成 `${workspaceFolder}/venv`；
  若想改用其他解释器，把这些 task 的 `command` 改为对应路径，或在 `launch.json`
  中通过 `Python: Select Interpreter` 切换（调试配置走 `python.interpreterPath`）。

### 3.3 后台任务的 problemMatcher

有两个 `"isBackground": true` 的后台任务，code-server 依赖各自的 `problemMatcher`
判断"启动就绪"，否则会一直等待或提前结束进程。

**`start-xvfb`**（仅供单独管理显示）：`dev/start_xvfb.sh` 在启动时打印 `xvfb-start: ...`、
就绪时打印 `xvfb-ready`（复用已有显示时也会打印这两行）。`tasks.json` 配置：

```json
"problemMatcher": {
    "pattern": { "regexp": "^$" },
    "background": {
        "activeOnStart": true,
        "beginsPattern": "xvfb-start:",
        "endsPattern": "xvfb-ready"
    }
}
```

**`启动 noVNC`**（常驻服务）：`dev/novnc_start.sh` 在就绪时打印 `novnc-start: ready`，
随后 `wait` 前台阻塞以保持任务存活（使 noVNC 不被任务清理杀掉）。`tasks.json` 配置：

```json
"problemMatcher": {
    "pattern": { "regexp": "^$" },
    "background": {
        "activeOnStart": true,
        "beginsPattern": "novnc-start:",
        "endsPattern": "novnc-start: ready"
    }
}
```

**`运行 PyQt 应用 (noVNC)`**（前台运行任务）：`dev/run_gui.sh` 启动后打印
`run_gui: DISPLAY=:99 ready`，python 退出或被终止时打印 `run_gui: terminated` /
`run_gui: exited (code N)`。`tasks.json` 配置（使其被当作需显式终止的持续任务，
正确绑定进程组，保证 `Ctrl+C` / `Tasks: Terminate Task` 能杀掉 python）：

```json
"problemMatcher": {
    "pattern": { "regexp": "^$" },
    "background": {
        "activeOnStart": true,
        "beginsPattern": "run_gui: DISPLAY=",
        "endsPattern": "run_gui: (exited|terminated)"
    }
}
```

`pattern.regexp: "^$"` 只是占位（无实际捕获字段），真正判定就绪的是
`background` 块的 `beginsPattern` / `endsPattern`，与脚本输出一一对应，无需改动。
若后续修改脚本的打印内容，需同步更新这里的起止正则。

### 3.4 脚本执行权限

code-server 的集成终端就是服务器的 shell，运行 `./dev/xxx.sh` 需要脚本有执行权限：

```bash
chmod +x dev/*.sh
```

相对路径基于 `${workspaceFolder}`（工作区根目录），无需额外配置 cwd。

## 4. 推荐的任务分组

当前任务已按语义分组，并非全部为 `build`：

- `build`：`Setup Python`、`Setup noVNC`、`运行 PyQt 应用`、`运行 PyQt 应用 (noVNC)`
  （其中 `运行 PyQt 应用 (noVNC)` 是 `isDefault: true`，`Ctrl+Shift+B` 会直接运行它——由
  `dev/run_gui.sh` 经 `dev/start_xvfb.sh` 拉起 `:99` 虚拟显示并以 `DISPLAY=:99` 启动，适合无头环境；
  该任务为前台持续任务，用 `Ctrl+C` 或 `Tasks: Terminate Task` 即可可靠退出，见 3.1 节）。
- `test`：`截图测试`。
- `none`：`启动 noVNC`、`停止 noVNC`（运维类，不出现在默认构建流程中）。`启动 noVNC`
  是后台常驻任务，跑起来后 noVNC 网页持续可用，停止请用 `停止 noVNC` 任务。

如需调整交互：把一次性/运维类脚本保持为 `"group": "none"` 即可避免污染
`Ctrl+Shift+B`，保留真正的构建/运行在 `build`，提升命令面板体验。

## 5. 典型工作流示例

在 code-server 中调试带 GUI 的程序：

1. `Tasks: Run Task` → `Setup Python`（首次初始化环境）。
2. （如需浏览器看界面）`Tasks: Run Task` → `Setup noVNC`，再 `启动 noVNC`
   （后台常驻，`http://<服务器IP>:6080/vnc.html` 可看 GUI）。
3. 按 `Ctrl+Shift+B` 直接运行默认任务 `运行 PyQt 应用 (noVNC)`（或 `Tasks: Run Task`
   手动选择）：
   - `dev/run_gui.sh` 调用 `dev/start_xvfb.sh` 自动检查并在需要时拉起 `:99` 虚拟显示；
   - 程序以 `DISPLAY=:99` 启动；
   - 通过 noVNC 网页查看界面。
   - （也可按 `F5` 走 `运行 PyQt 应用 (venv + noVNC)` 调试配置，其 `preLaunchTask`
     指向 `运行 PyQt 应用 (noVNC)`，由 `run_gui.sh` 确保虚拟显示就绪，无需依赖
     不可靠的 `start-xvfb` 前置任务。）
4. 验证界面：`Tasks: Run Task` → `截图测试`，查看 `tmp_screenshot.png`。
5. 结束程序：`Ctrl+C` 或 `Ctrl+Shift+P` → `Tasks: Terminate Task` → `运行 PyQt 应用 (noVNC)`
   （`run_gui.sh` 会杀掉 python 进程组并打印 `run_gui: terminated`）。
6. 结束 noVNC：`Tasks: Run Task` → `停止 noVNC`（清理 x11vnc / websockify / Xvfb；
   若之前没手动停程序，此脚本也会一并清理残留的 `python main.py` 进程）。
