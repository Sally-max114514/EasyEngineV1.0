# EasyEngine 剧情编辑器

这是一个独立的可选工具，编辑项目现有格式的 JSON 剧本。编辑器代码位于 `editor/`，不改动 `easyengine/galgame/` 或 `easyengine/desktop/`。

## 安装与启动

在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r editor/requirements.txt
.venv/bin/python editor/main.py
```

也可以启动时打开剧本：

```bash
.venv/bin/python editor/main.py assets/text/scripts/demo.json
```

Windows 可运行 `py -3 -m venv .venv`，然后用 `.venv\Scripts\python.exe` 替代 `.venv/bin/python`。建议使用虚拟环境，以免修改系统 Python。编辑器使用 PySide6；CLI 和桌面玩家前端不依赖此编辑器依赖。

## 界面

- **左侧剧情树**：剧本、场景、台词和选项。右键可新建场景/台词/选项、删除和上下移动；删除被其他场景跳转引用的场景会被拒绝。
- **中间属性面板**：使用中文名称编辑剧本标题、角色、变量、CG 清单、场景设置、台词、选项、条件、立绘和变量变更。鼠标悬停在输入框上可查看白话说明和填写示例；跳转场景使用现有场景下拉列表，复杂值以 JSON 编辑。
- **右侧资源浏览器**：复用 `easyengine.resources.scan_assets()`，按 `image`、`audio`、`text`、`video`、`other` 分类扫描 `assets/`。双击资源或拖入资源输入框会填入相对 `assets/` 的路径。

`require` 可使用安全表达式，也可以切换为 JSON 条件树。表达式最终由引擎现有解析器校验，不会执行任意 Python 代码。

首次启动时会显示非模态的新手教程，阅读期间仍可继续操作编辑器。勾选“不再提示”后会通过 Qt 设置记住选择；之后可从 **帮助 → 新手教程** 随时重新打开。

## 偏好设置

通过 **工具 → 偏好设置...** 或快捷键 `Ctrl+,` 打开设置窗口：

- **主题**：浅色、深色或系统默认；更改后立即生效。
- **字体大小**：10–24 pt，应用后立即影响编辑区。
- **自动保存**：切换左侧剧情节点时，自动校验并保存当前剧本。未命名剧本需要先手动保存一次以选择文件位置；自动保存失败时会保留当前节点并提示错误。
- **启动时打开上次编辑的剧本**：开启后，下次启动会尝试恢复最近成功打开或保存的剧本。
- **默认资源目录**：选择扫描图片、音频等素材的目录；应用后资源浏览器会立即重新扫描。剧本内仍保存相对该资源目录的路径。

**应用**会保存并立即生效但保持窗口打开，**确定**保存并关闭，**取消**放弃本次尚未应用的改动。设置使用 `QSettings("EasyEngine", "Editor")` 持久化。

## 保存与测试

- 打开文件时只解析标准 JSON，允许先修复不符合剧本 schema 的内容。
- **测试剧本**会将内存数据写入临时 JSON，并调用 `load_script()`。
- **保存/另存为**同样先写入临时 JSON 并调用 `load_script()`；只有校验通过才以原子替换写入正式文件。
- 校验失败会显示 `ScriptError` 详情，已存在的剧本文件不会被部分写入。
- 保存数据就是引擎原生 JSON，不会生成编辑器私有格式。图片/音频文件是否存在仍由资源扫描和运行时资源层负责；剧本 schema 校验不要求资源必须齐全。

## 编辑器测试

安装编辑器依赖后，在项目根目录运行：

```bash
.venv/bin/python -m unittest discover -s editor/tests -v
```

GUI 冒烟测试使用 Qt offscreen 平台，不需要打开真实窗口。
