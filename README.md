# EasyEngine 使用指南

EasyEngine 是一个纯 Python 的小型 Galgame 引擎，包含核心剧情运行时和可选的 Pygame-CE 桌面前端：

1. **资源系统**：自动扫描 `assets/`，按类型或目录归类，支持大小写不敏感查找和自动关闭文件句柄。
2. **Galgame 核心**：JSON 剧本、对话、选项分支、好感度/旗标、背景/立绘/音乐引用、打字机和存读档。
3. **桌面前端（可选）**：状态机驱动的窗口、图片与文字缓存、脏矩形刷新，以及后台音频预加载。

Galgame 核心仍与界面、音频库解耦：桌面前端只是一个适配器，读取 `GameView` 并响应 `GameEvent`。也可以继续接入终端、Tkinter、Web 或自定义 UI。

项目作者为 [Sally-max114514](https://github.com/Sally-max114514)，按仓库现有 MIT License 开源。MIT 许可允许再分发和商业销售，但必须随副本保留原版权声明与许可证；代码内署名是可见的作者信息，不是防篡改机制。

### 阅读导航

- 想快速制作和运行剧情：从[快速开始](#1-环境要求与快速开始)和[最小剧本](#5-galgame-最小示例)开始。
- 想查 JSON 字段：看[剧本格式参考](#6-剧本格式参考)。
- 想自己写 Python 程序驱动剧情：看[引擎 API](#7-引擎-api)。
- 想启动图形界面：看[Pygame 桌面前端](#78-pygame-ce-桌面前端)。
- 想管理图片、音乐等文件：看[资源系统](#4-资源系统)。

### 引擎如何协作

```text
main.py
  ├─ 自检、扫描 assets/、选择 JSON 剧本
  ├─ easyengine/galgame/script.py 读取并校验剧本
  ├─ easyengine/galgame/engine.py 推进剧情，产生 GameView / GameEvent
  └─ easyengine/desktop/ 将视图绘制到窗口并响应输入、图片和音频事件
```

`GalgameEngine` 不依赖 Pygame。命令行演示和自定义界面只需使用核心层；桌面模式在此基础上增加状态机、渲染、异步音频、菜单和存档界面。

---

## 1. 环境要求与快速开始

### 1.1 环境要求

- Python **3.10+**（项目使用 `X | Y` 类型语法）
- 核心 CLI 无第三方依赖
- 可选桌面模式使用 Pygame-CE，安装方式见下方
- 开发时使用 Python 3.14.6 验证

### 1.2 快速开始

以下命令从包含 `main.py` 的项目根目录执行。文中用 `python` 表示 Python 3.10+ 解释器；如果 Linux/macOS 上没有 `python` 命令，请改用 `python3`，Windows 可用 `py -3`。

```bash
# 启动自检、创建分类目录、扫描资源，并校验示例剧本
python main.py

# 只校验示例剧本，打印角色、场景和缺失资源
python main.py --validate

# 无界面跑一遍示例剧本，自动选择第一个可用选项
python main.py --demo

# 推荐用虚拟环境安装可选桌面依赖
python -m venv .venv
# Linux / macOS
.venv/bin/python -m pip install -r requirements-ui.txt
.venv/bin/python main.py --play
# Windows
.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.venv\Scripts\python.exe main.py --play
```

示例剧本位于 [assets/text/scripts/demo.json](./assets/text/scripts/demo.json)，`--demo` 会自动走到真结局。

### 1.3 默认启动流程

`python main.py` 依次执行：

1. 打印 EasyEngine 作者、GitHub 和许可证 Banner，以及当前时间；
2. 检查操作系统是否为 `posix` / `nt`，并写入 `config/platform.txt`；
3. 检查当前工作目录可访问；
4. 检查 `assets/` 和 `config/` 存在；
5. 自动创建 `assets/video`、`assets/audio`、`assets/image`、`assets/text`、`assets/other`；
6. 递归扫描 `assets/` 并按类型打印资源数量；
7. 校验示例剧本并打印摘要。

---

## 2. 项目结构

```text
EasyEngineV1.0/
├── main.py                         # 启动入口与 CLI
├── export_game.py                  # 单文件游戏打包脚本
├── README.md                       # 本文档
├── assets/                         # 所有游戏资源
│   ├── video/                      # 视频
│   ├── audio/
│   │   ├── bgm/                    # 背景音乐
│   │   └── se/                     # 音效
│   ├── image/
│   │   ├── bg/                     # 背景图
│   │   └── characters/
│   │       └── yuki/               # 角色立绘
│   ├── text/
│   │   └── scripts/                # JSON 剧本
│   └── other/                      # 未识别的扩展名
├── config/
│   └── platform.txt                # 启动时自动写入
├── easyengine/
│   ├── config.py                   # 路径与资源分类常量
│   ├── resources.py                # 资源扫描、查找、读取
│   ├── selfcheck.py                # 启动自检
│   ├── clock.py                    # 时间工具
│   ├── desktop/                    # 可选 Pygame-CE 桌面前端
│   │   ├── app.py                  # 窗口生命周期与主循环
│   │   ├── state_machine.py        # 状态机
│   │   ├── states.py               # 标题、游戏、暂停、结局状态
│   │   ├── renderer.py             # 渲染、缓存与脏矩形刷新
│   │   ├── assets.py               # 图片加载与缩放缓存
│   │   └── audio.py                # 后台音频预加载
│   └── galgame/
│       ├── script.py               # JSON 剧本模型、解析、校验
│       ├── engine.py               # GalgameEngine 核心
│       ├── state.py                # 运行时状态与存读档
│       └── text.py                 # 打字机状态
├── requirements-ui.txt             # 桌面模式可选依赖
├── requirements-export.txt         # PyInstaller 游戏打包依赖
├── tests/                           # 核心回归测试
└── saves/                          # 存档目录，保存时自动创建
```

> `assets/` 下的 `.gitkeep` 只是占位文件，扫描时会自动跳过所有以 `.` 开头的文件和目录。

---

## 3. 命令行参考

### 3.1 参数

| 命令 | 作用 |
|---|---|
| `python main.py` | 自检 + 扫描资源 + 校验示例剧本 |
| `python main.py --validate` | 校验示例剧本并打印摘要 |
| `python main.py --demo` | 校验并自动运行示例剧本 |
| `python main.py --story path/to/story.json` | 校验指定剧本 |
| `python main.py --story path/to/story.json --demo` | 自动运行指定剧本 |
| `python main.py --story path/to/story.json --validate` | 校验指定剧本，不运行 |
| `python main.py --play` | 在 Pygame-CE 窗口中运行默认示例 |
| `python main.py --story path/to/story.json --play` | 在窗口中运行指定剧本 |

`--demo` 会自动选择 `available_choices` 中的第一个选项，仅用于验证剧情能否走通，不是正式游戏界面。
桌面模式需要先安装 `requirements-ui.txt` 中的可选依赖；纯 CLI 用户无需安装 Pygame。

### 3.2 退出码

- `0`：成功
- `1`：自检失败、资源目录异常、剧本校验失败或演示异常

### 3.3 打包为单文件游戏

在项目根目录安装打包依赖并指定剧本：

```bash
python -m pip install -r requirements-export.txt
python export_game.py --story assets/text/scripts/demo.json --name "我的游戏"
```

可使用绝对路径或相对路径指定外部剧本；不传 `--name` 时使用剧本标题。生成的可执行文件和同名 ZIP 位于 `dist/`；ZIP 内含可执行文件及仓库现有 `LICENSE`。Windows 可执行文件还会带有 EasyEngine 产品名与作者信息。打包会把所选剧本放到内置默认入口，并排除其他 `assets/text/scripts/` 剧本；图片和音频仍按原资源相对路径打入程序。游戏构建使用 `--onefile` / `--windowed`，并显式排除 PySide6、PyQt 等编辑器专属依赖。

---

## 4. 资源系统

### 4.1 分类目录

资源按扩展名归档到五个目录：

| 分类 | 目录 | 常见扩展名 |
|---|---|---|
| `video` | `assets/video/` | `mp4` `avi` `mkv` `mov` `webm` `flv` `wmv` `m4v` |
| `audio` | `assets/audio/` | `mp3` `wav` `ogg` `flac` `m4a` `aac` `wma` `opus` |
| `image` | `assets/image/` | `jpg` `jpeg` `png` `gif` `bmp` `webp` `tif` `tiff` `svg` `ico` |
| `text` | `assets/text/` | `txt` `md` `json` `csv` `xml` `yaml` `yml` `ini` `cfg` `log` |
| `other` | `assets/other/` | 其他未知扩展名 |

要新增分类，只需修改 [easyengine/config.py](./easyengine/config.py) 里的 `EXTENSION_GROUPS`。启动时 `ensure_category_dirs()` 会自动创建同名文件夹。

### 4.2 扫描规则

- 递归扫描整个 `assets/`，包括所有子目录。
- 扩展名大小写不敏感：`.MP4`、`.Mp4`、`.mp4` 都会归为 `video`。
- 默认跳过隐藏文件和隐藏目录，例如 `.gitkeep`。
- 已知扩展名优先按扩展名分类。
- 未知扩展名会参考它所在的一级目录，例如：
  - `assets/image/sprite.aseprite` → `image`
  - `assets/video/clip.xyz` → `video`
  - 不在分类目录中的未知扩展名 → `other`

### 4.3 资源 API

```python
from easyengine.resources import find_resource, load_text, read_bytes, scan_assets

# 按类型归类：{"video": [Path, ...], "audio": [...], ...}
resources = scan_assets()

# 按子目录归类：{"video": [...], "video/sub": [...], ".": [...]}
by_folder = scan_assets(group_by="folder")

# 按文件名或相对路径查找，大小写不敏感
path = find_resource(resources, "video/Intro.MP4")

# 查找并读取文本资源，句柄自动关闭
text = load_text(resources, "docs/readme.txt")

# 读取二进制资源
data = read_bytes(path)
```

常用函数：

| 函数 | 说明 |
|---|---|
| `scan_assets(root=ASSETS_DIR, *, group_by="type", include_hidden=False)` | 扫描并返回 `{分组: [Path, ...]}` |
| `iter_asset_files(root=ASSETS_DIR, *, include_hidden=False)` | 逐个遍历资源文件 |
| `classify(path, root=None)` | 返回文件所属分类 |
| `find_resource(resources, name)` | 按文件名或相对路径查找，大小写不敏感 |
| `read_text(path, *, encoding="utf-8", errors="strict")` | 读取文本，自动关闭句柄 |
| `read_bytes(path)` | 读取二进制，自动关闭句柄 |
| `load_text(resources, name, *, encoding="utf-8")` | 查找 + 读取文本 |
| `load_bytes(resources, name)` | 查找 + 读取二进制 |
| `ensure_category_dirs(root=ASSETS_DIR)` | 创建五个分类目录，幂等 |
| `category_dir(category, root=ASSETS_DIR)` | 获取某分类的规范目录 |
| `relative_path(path, root=ASSETS_DIR)` | 转为相对 POSIX 路径，便于展示 |

### 4.4 Galgame 资源约定

示例剧本使用以下目录，可以按自己的项目调整剧本内的引用：

```text
assets/
├── audio/
│   ├── bgm/daily.mp3
│   └── se/click.wav
├── image/
│   ├── bg/classroom.png
│   └── characters/yuki/normal.png
└── text/scripts/demo.json
```

剧本里的资源名相对于 `assets/` 书写，例如 `image/bg/classroom.png`。查找时不区分大小写。

---

## 5. Galgame 最小示例

### 5.1 新建剧本

创建 `assets/text/scripts/hello.json`：

```json
{
  "title": "第一次见面",
  "start": "start",
  "characters": {
    "yuki": {"name": "雪乃"}
  },
  "vars": {
    "affection.yuki": 0
  },
  "scenes": {
    "start": {
      "background": "image/bg/classroom.png",
      "bgm": "audio/bgm/daily.mp3",
      "lines": [
        {
          "speaker": "yuki",
          "text": "你好，初次见面。",
          "show": [
            {
              "id": "yuki",
              "image": "image/characters/yuki/normal.png",
              "position": "center"
            }
          ]
        },
        {
          "text": "要和她打招呼吗？",
          "choices": [
            {
              "text": "打招呼",
              "add": {"affection.yuki": 1},
              "goto": "friendly"
            },
            {
              "text": "沉默",
              "goto": "silent"
            }
          ]
        }
      ]
    },
    "friendly": {
      "lines": [
        {"speaker": "yuki", "text": "太好了，我们走吧。", "end": true}
      ]
    },
    "silent": {
      "lines": [
        {"speaker": "yuki", "text": "……那下次见。", "end": true}
      ]
    }
  }
}
```

### 5.2 校验并运行

```bash
python main.py --story assets/text/scripts/hello.json
python main.py --story assets/text/scripts/hello.json --demo
```

编写 JSON 时请注意：

- JSON 不支持注释；字符串和对象键必须使用双引号，最后一项后不能有逗号。
- 字段名必须与本指南一致；未知字段会导致剧本校验失败。
- `start`、`goto`、`next` 必须与 `scenes` 中的场景 ID 完全一致（区分大小写）。
- 剧本中的资源路径相对于 `assets/`，例如写 `image/bg/classroom.png`，不要写 `assets/image/bg/classroom.png`。
- 剧本加载会校验结构、表达式和跳转目标；资源文件缺失会单独报告，不会阻止核心剧情运行。

---

## 6. 剧本格式参考

### 6.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 否 | 剧本名，默认 `未命名剧本`；存档会用它校验剧本 |
| `start` | string | 否 | 起始场景 id，默认取 `scenes` 的第一个 |
| `characters` | object | 否 | 角色 id → 角色名或角色对象 |
| `vars` | object | 否 | 初始变量；支持嵌套 JSON 对象、数组和标量 |
| `scenes` | object | 是 | 场景 id → 场景对象，不能为空 |
| `gallery` | array | 否 | CG 鉴赏清单；每项声明图片资源及显示信息 |
| `generator` / `_generator` | string | 否 | 生成器署名元数据；编辑器和打包器会在缺失时写入 `_generator` |

除生成器元数据外，未知顶层字段会直接报错，便于发现拼写错误。

### 6.2 角色

两种写法：

```json
"characters": {
  "yuki": "雪乃",
  "me": {"name": "我", "color": "#f4a261"}
}
```

| 字段 | 说明 |
|---|---|
| `name` | 显示名 |
| `color` | 可选颜色字符串，仅提供给界面层使用 |

`speaker` 可以是角色 id，也可以是未登记的字面名称。登记过的 id 会解析为 `name`。界面层可以通过 `engine.story.characters[speaker_id].color` 读取颜色。

### 6.3 变量

变量可以使用嵌套 JSON 值：

```json
"vars": {
  "stats": {"affection": {"yuki": 0}},
  "flags": {"met_yuki": false},
  "route": ""
}
```

可以使用点号访问或更新嵌套变量；旧式点号键仍兼容：

```json
{"add": {"stats.affection.yuki": 1}}
```

精确存在的顶层键优先于点号路径。`add` 只接受数字，变量不存在时按 `0` 处理；遇到非数字值或点号路径中间不是对象时会报告错误。

### 6.4 场景

```json
"start": {
  "background": "image/bg/classroom.png",
  "bgm": "audio/bgm/daily.mp3",
  "transition": {"type": "crossfade", "duration": 0.5},
  "lines": [],
  "next": "next_scene",
  "end": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `background` | string | 进入场景时切换背景；空字符串 `""` 表示清除 |
| `bgm` | string | 进入场景时播放 BGM；空字符串 `""` 表示停止 |
| `transition` | string/object | 场景转场，可选；类型与时长见「6.10 语音、转场与 CG」 |
| `lines` | array | 台词/指令列表 |
| `next` | string | 播完 `lines` 后进入的场景 |
| `end` | boolean | 显式标记终止场景；不能与 `next` 同时设置 |

> 没有 `next` 时，播完当前场景的 `lines` 后会自动结束。

### 6.5 台词行

```json
{
  "speaker": "yuki",
  "text": "今天的晚霞真好看。",
  "background": "image/bg/sunset.png",
  "bgm": "audio/bgm/warm.mp3",
  "voice": "audio/voice/yuki_001.wav",
  "transition": {"type": "slide-left", "duration": 0.4},
  "se": "audio/se/click.wav",
  "show": [
    {"id": "yuki", "image": "image/characters/yuki/smile.png", "position": "right"}
  ],
  "hide": ["other_character"],
  "set": {"route": "walk"},
  "add": {"affection.yuki": 1},
  "set_expr": {"stats.affection.yuki": "stats.affection.yuki + 1"},
  "goto": "next_scene"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `speaker` | string | 角色 id 或显示名；省略表示旁白 |
| `text` | string | 台词文本，默认 `""` |
| `background` | string | 本行切换背景；`""` 清除；省略表示不变 |
| `bgm` | string | 本行切换 BGM；`""` 停止；省略表示不变 |
| `voice` | string | 播放当前台词语音；桌面端可按音频时长近似同步字幕 |
| `se` | string | 本行播放一次音效 |
| `transition` | string/object | 本行转场；设置后优先于场景转场 |
| `show` | array | 显示/更新立绘 |
| `hide` | string/array | 隐藏立绘；`"all"` 表示全部隐藏 |
| `set` | object | 变量赋绝对值 |
| `add` | object | 数字变量累加 |
| `set_expr` | object | 以安全表达式计算并设置变量 |
| `add_expr` | object | 以安全表达式计算数字增量 |
| `goto` | string | 本行读完后跳转场景 |
| `choices` | array | 选项列表 |
| `end` | boolean | 本行读完后结束游戏 |

约束：

- `goto` 与 `choices` 不能同时出现。
- `end` 与 `choices` 不能同时出现。
- `end` 与 `goto` 不能同时出现。
- `show` 在同一行中先于 `hide` 执行。
- 立绘 `position` 只能是 `left`、`center`、`right`。

### 6.6 选项

```json
"choices": [
  {
    "text": "牵住她的手。",
    "require": {
      "affection.yuki": {"op": ">=", "value": 2}
    },
    "add": {"affection.yuki": 1},
    "goto": "ending_true"
  },
  {
    "text": "安静地陪她走。",
    "goto": "ending_good"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 选项文本，必填且非空 |
| `goto` | string | 选择后跳转的场景；省略则继续下一行 |
| `set` | object | 选择后设置变量 |
| `add` | object | 选择后累加数字变量 |
| `require` | object | 解锁条件 |

未满足 `require` 的选项不会从 `GameView.choices` 中消失，而是带有 `available: false`，方便界面显示为灰色或隐藏。`engine.available_choices` 只返回可选项。

### 6.7 条件 `require`

条件可以使用旧式对象、表达式字符串或组合树。旧式对象的多个键之间仍是 AND，键和值可以是：

1. **直接写期望值**：表示相等比较。

```json
"require": {
  "flags.met_yuki": true,
  "route": "walk"
}
```

2. **比较对象**：`{"op": ">=", "value": 2}`。

```json
"require": {
  "affection.yuki": {"op": ">=", "value": 2}
}
```

支持的运算符：

| 运算符 | 说明 |
|---|---|
| `==` | 等于 |
| `!=` | 不等于 |
| `>` | 大于 |
| `>=` | 大于等于 |
| `<` | 小于 |
| `<=` | 小于等于 |

`=` 是 `==` 的别名。如果变量不存在，有序比较会返回 `false`；相等/不等比较则按 `None` 参与。

也可写安全表达式，支持嵌套变量、比较、算术、`and` / `or` / `not` 和括号：

```json
"require": "stats.affection.yuki >= 3 and (route == 'walk' or flags.special)"
```

复杂条件可用 `all`、`any`、`not` 组合；其值是条件数组（`not` 需要一个条件）：

```json
"require": {
  "all": [
    {"var": "stats.affection.yuki", "op": ">=", "value": 2},
    {"any": ["route == 'walk'", "flags.special"]}
  ]
}
```

表达式通过受限 AST 解释，不执行任意 Python 代码；函数调用、私有属性访问等不受支持，并在剧本加载阶段校验。

### 6.8 跳转规则

- `line.goto`：当前行读完后跳转。
- `choice.goto`：选择后跳转。
- `scene.next`：场景 `lines` 播完后跳转。
- `line.end: true`：当前行读完后结束。
- 没有 `next` 的场景：播完后自动结束。

所有 `goto` 和 `next` 必须在解析阶段指向存在的场景，否则剧本加载失败。

### 6.9 语音、转场与 CG

`voice` 指向一段音频文件。桌面端异步解码并从独立频道播放；开启设置里的「语音字幕同步」后，文字速度会按音频总时长近似调整，自动播放会等语音结束。同步不是逐字或逐词时间轴。

转场可以写在场景或台词行上，字符串形式使用默认时长 0.32 秒；对象形式可指定 0–5 秒：

```json
"transition": "fade"
```

```json
"transition": {"type": "slide-right", "duration": 0.45}
```

支持 `none`、`fade`、`crossfade`、`slide-left` 和 `slide-right`。台词行上的转场覆盖场景转场；场景切换和中途背景切换默认使用淡入转场。

CG 由顶层 `gallery` 清单声明，所有清单项都会出现在桌面端鉴赏页：

```json
"gallery": [
  {
    "id": "sunset",
    "image": "image/cg/sunset.png",
    "title": "晚霞",
    "description": "放学后的约定"
  }
]
```

`id` 必须唯一，`image` 为资源路径；`title` 和 `description` 用于鉴赏页展示。该清单目前是静态目录，不会自动根据剧情解锁。

### 6.10 剧本校验

加载剧本时会检查：

- 顶层、场景、台词、选项是否包含未知字段；
- 台词、选项文本等必填字符串是否为空；
- `add` 的值是否为数字；
- 条件的运算符是否合法；
- 条件表达式语法与组合树结构是否合法；
- 转场类型/时长、CG 清单字段及 id 是否合法；
- `goto` / `next` 是否指向存在的场景；
- `choices` 是否为空数组；
- `goto`、`choices`、`end` 是否冲突；
- 立绘位置是否合法。

只要有一项不通过，`load_script()` 会抛出 `ScriptError`，命令行会返回退出码 `1`。

---

## 7. 引擎 API

### 7.1 创建引擎

```python
from easyengine import GalgameEngine, load_script

story = load_script("assets/text/scripts/demo.json")
engine = GalgameEngine(
    story,
    assets_root="assets",   # 可选；默认按剧本文件位置推断
    save_dir="saves",       # 可选；开发环境默认项目 saves/
)
```

`load_script()` 接受绝对路径和相对于当前工作目录的路径。文件剧本位于项目 `assets/` 下时，引擎会自动找到该资源根目录；其他位置的剧本默认查找其所在目录下的 `assets/`。显式传入 `assets_root` 时以指定目录为准。内存构建的剧本默认使用项目资源目录。
打包环境的默认存档目录为可执行文件同级的 `saves/`。连续超过 100 次没有产生 `line` 事件的 `goto` / `next` 跳转会抛出 `ScriptError`，并记录当前场景。

也可以先自行扫描资源，避免重复扫描：

```python
from easyengine.resources import AssetCatalog, scan_assets

resources = scan_assets()
engine = GalgameEngine(story, resources=resources)

# 桌面层可复用同一个 pathlib 资源索引，避免再次扫描/查找
catalog = AssetCatalog(resources=resources)
engine = GalgameEngine(story, asset_catalog=catalog)
```

### 7.2 方法

| 方法/属性 | 返回值 | 说明 |
|---|---|---|
| `start(scene_id=None)` | `StepResult` | 开始游戏，重置变量、背景、立绘、音乐和剧情位置 |
| `advance()` | `StepResult` | 文字未显示完时先补全；已完整时进入下一行/场景 |
| `choose(index)` | `StepResult` | 选择选项，`index` 是 `GameView.choices` 中的原始下标 |
| `reload_script()` | `StepResult` | 从原 JSON 文件重新加载剧本并重置运行状态 |
| `tick(count=1)` | `GameView` | 打字机推进 `count` 个字符 |
| `reveal_all()` | `GameView` | 立即显示当前行全部文字 |
| `save(slot="quick")` | `Path` | 保存到 `saves/<slot>.json` |
| `load(slot="quick")` | `StepResult` | 读取存档并恢复状态 |
| `list_saves()` | `tuple[str, ...]` | 列出存档名 |
| `resolve_asset(name)` | `AssetRef \| None` | 解析资源引用 |
| `missing_assets()` | `tuple[str, ...]` | 列出剧本引用但缺失的资源 |
| `view` | `GameView` | 当前画面快照 |
| `available_choices` | `tuple[ChoiceView, ...]` | 当前可选项 |
| `state` | `GameState` | 当前运行时状态，启动前为 `None` |
| `typer` | `TextTyper` | 当前打字机，启动前或结束时可能为 `None` |

### 7.3 `GameView`

| 字段 | 类型 | 说明 |
|---|---|---|
| `started` | bool | 是否已调用 `start()` |
| `ended` | bool | 游戏是否结束 |
| `scene_id` | string/null | 当前场景 |
| `line_index` | int | 当前行下标 |
| `speaker_id` | string/null | 当前角色 id |
| `speaker` | string/null | 当前角色显示名 |
| `text` | string | 当前行完整文本 |
| `visible_text` | string | 打字机已显示的部分 |
| `text_complete` | bool | 当前行是否显示完毕 |
| `background` | AssetRef/null | 当前背景 |
| `bgm` | AssetRef/null | 当前 BGM |
| `voice` | AssetRef/null | 当前台词语音 |
| `sprites` | tuple[SpriteView, ...] | 当前立绘，按 id 排序 |
| `choices` | tuple[ChoiceView, ...] | 当前行全部选项，含 `available` 标记 |
| `variables` | Mapping | 当前全部变量快照 |

`SpriteView`：

| 字段 | 说明 |
|---|---|
| `id` | 立绘 id |
| `image` | `AssetRef` |
| `position` | `left` / `center` / `right` |

`ChoiceView`：

| 字段 | 说明 |
|---|---|
| `index` | 传给 `choose()` 的原始下标 |
| `text` | 选项文本 |
| `available` | 条件是否满足 |

`AssetRef`：

| 字段 | 说明 |
|---|---|
| `name` | 剧本中写的资源名 |
| `path` | 实际文件路径（默认配置下为绝对路径）；缺失时为 `None` |
| `exists` | 便捷属性，等价于 `path is not None` |

### 7.4 典型主循环

```python
from easyengine import GalgameEngine, load_script

story = load_script("assets/text/scripts/demo.json")
engine = GalgameEngine(story)

step = engine.start()
handle_events(step.events)

while not engine.view.ended:
    view = engine.view

    if not view.text_complete:
        # 界面层可以按自己的帧率调用 tick(1)
        engine.tick(1)
        continue

    if view.choices:
        available = engine.available_choices
        if not available:
            print("没有可用选项")
            break
        # 真实界面应从点击事件取得 ChoiceView.index
        result = engine.choose(available[0].index)
    else:
        # 等待玩家点击/按键
        result = engine.advance()

    handle_events(result.events)
```

`handle_events()` 由界面层实现，见 7.6。

### 7.5 打字机

引擎不自带计时器，只维护“显示到第几个字符”：

```python
engine.tick(1)          # 显示 1 个字符
engine.tick(5)          # 显示 5 个字符
engine.reveal_all()     # 立即全部显示

view = engine.view
print(view.visible_text)
print(view.text_complete)
```

`TextTyper` 也可以单独使用：

```python
from easyengine import TextTyper

typer = TextTyper("你好，世界")
typer.tick(2)
print(typer.visible_text)   # 你好
print(typer.remaining)      # 3
typer.reveal_all()
```

注意：

- `advance()` 在文字未显示完时会先补全，不会直接跳到下一行。
- `choose()` 也会先补全当前行文字。
- `tick()` 的 `count` 必须是整数，否则抛 `TypeError`；负数会抛 `ValueError`。

### 7.6 事件

每次 `start()`、`advance()`、`choose()`、`load()` 都会返回 `StepResult`：

```python
@dataclass(frozen=True)
class StepResult:
    events: tuple[GameEvent, ...]
    view: GameView
```

`GameEvent` 是瞬时事件，界面层需要响应；`GameView` 是可重复读取的快照。

| `kind` | `data` | 触发时机 |
|---|---|---|
| `scene` | `{"scene": str, "transition": Transition}` | 进入场景并通知界面转场 |
| `transition` | `{"transition": Transition}` | 应用台词行配置的转场 |
| `background` | `{"ref": AssetRef \| None}` | 切换/清除背景 |
| `bgm` | `{"ref": AssetRef \| None}` | 播放/停止 BGM |
| `se` | `{"ref": AssetRef}` | 播放一次音效 |
| `sprite_show` | `{"id": str, "image": AssetRef, "position": str}` | 显示/更新立绘 |
| `sprite_hide` | `{"id": str}` | 隐藏立绘；`id` 可能为 `"all"` |
| `variables` | `{"values": dict}` | 变量发生变化；普通变化只含本次变更的键，读档时含全部变量 |
| `line` | `{"speaker_id": str \| None, "speaker": str \| None, "text": str, "voice": AssetRef \| None, "transition": Transition \| None, "choices": tuple[ChoiceView, ...]}` | 开始显示新台词 |
| `choice` | `{"index": int, "text": str}` | 玩家选择后 |
| `text_complete` | `{"text": str}` | `advance()` 补全打字机时 |
| `load` | `{"slot": str, "unverified": bool}` | 读取存档；无剧本指纹的旧存档标记为未验证 |
| `sprites` | `{"sprites": tuple[SpriteView, ...]}` | 读档时恢复全部立绘 |
| `end` | `{"scene": str}` | 游戏结束 |

示例适配：

```python
def handle_events(events):
    for event in events:
        if event.kind == "background":
            ref = event.data["ref"]
            if ref is None:
                clear_background()
            elif ref.exists:
                show_background(ref.path)
            else:
                show_missing_asset(ref.name)

        elif event.kind == "bgm":
            ref = event.data["ref"]
            if ref is None:
                stop_bgm()
            elif ref.exists:
                play_bgm(ref.path)

        elif event.kind == "se":
            ref = event.data["ref"]
            if ref.exists:
                play_se(ref.path)

        elif event.kind == "sprite_show":
            image = event.data["image"]
            if image.exists:
                show_sprite(event.data["id"], image.path, event.data["position"])
            else:
                show_missing_asset(image.name)

        elif event.kind == "sprite_hide":
            hide_sprite(event.data["id"])

        elif event.kind == "line":
            update_dialogue(
                event.data["speaker"],
                event.data["text"],
                event.data["choices"],
            )

        elif event.kind == "end":
            show_ending()
```

### 7.7 接入自定义界面和音频

推荐分工：

- **UI**：每个渲染帧读取 `engine.view`，用 `visible_text` 显示台词，用 `sprites` 绘制立绘，用 `choices` 显示选项。
- **音频**：只在收到 `bgm` / `se` 事件时切换或播放；台词行事件中的 `voice` 用于播放语音。不要每帧重复播放。
- **输入**：
  - 点击“继续” → `engine.advance()`
  - 点击选项 → `engine.choose(choice.index)`
  - 快进/跳过 → 先 `engine.reveal_all()` 补全当前行，再 `engine.advance()`
- **资源缺失**：先判断 `AssetRef.exists`，缺失时显示占位图或打印日志，不要直接打开 `None`。

### 7.8 Pygame-CE 桌面前端

安装可选依赖并启动默认剧本：

```bash
# 建议在项目虚拟环境中执行；若已激活 venv，可直接使用 python
python -m venv .venv
# Linux / macOS
.venv/bin/python -m pip install -r requirements-ui.txt
.venv/bin/python main.py --play

# Windows PowerShell
.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.venv\Scripts\python.exe main.py --play
```

已有虚拟环境时，也可以直接安装：

```bash
python -m pip install -r requirements-ui.txt
python main.py --play

# 指定其他 JSON 剧本
python main.py --story assets/text/scripts/hello.json --play
```

Linux 发行版管理的系统 Python 可能禁止全局 pip 安装；使用虚拟环境即可，不要对系统 Python 强制覆盖安装。

桌面层通过 `PygameApplication` 组合 Galgame 引擎、`AssetCatalog`、`PygameRenderer`、音频加载器和 `StateMachine`。核心 CLI 不会导入 Pygame，因此未安装桌面依赖时 `--validate` / `--demo` 仍可正常使用。

默认控制：

| 输入 | 行为 |
|---|---|
| 标题页 Enter / Space | 开始或重新开始 |
| 游戏中 Enter / Space | 先补全当前台词，再推进；有选项时需点击可用选项 |
| 游戏中 Esc | 暂停 |
| 暂停时 Esc / Enter / Space | 继续 |
| F5 / F9 | 快速存档 / 读档（`saves/quick.json`） |
| 结局页 Enter / Space | 返回标题；Esc 退出 |
| A | 开关自动播放；自动播放会等待当前语音结束 |
| S | 开关跳过已读文本；遇到未读行会自动停止 |
| Backspace | 回滚到上一条剧情快照 |
| V | 收藏 / 取消收藏当前台词语音 |
| 标题页、故事库、存档、收藏列表 ↑/↓ | 移动选择；故事库、存档和收藏列表支持滚轮分页 |
| CG 鉴赏 ←/→ | 浏览上一张 / 下一张 CG |
| 游戏选项滚轮 | 浏览较长选项列表 |

标题页还可进入故事库、最近存档、CG 鉴赏、语音收藏和设置。设置可调文字速度、主音量、语音字幕同步和自动播放间隔。收藏列表及存档列表按页显示，避免条目过多时超出窗口。

桌面性能与资源行为：

- `pathlib` 资源索引在窗口启动时构建一次，按相对路径优先、文件名回退查找，路径匹配不区分大小写。
- 图片采用按需解码，并缓存源图与缩放图；窗口尺寸变化时只清理缩放缓存。
- 字体、渲染文本和换行结果有界缓存；无内容变化时不会重复绘制，内容变化时只更新场景或对话区域。
- 音频文件在单个后台工作线程中预加载/解码；主线程负责播放与音轨切换。BGM、音效和语音使用独立控制路径，语音时长用于近似字幕同步和自动播放等待。若系统没有可用音频设备，窗口仍可静音运行并输出提示。
- 缺失或无法解码的图片显示占位提示；资源错误和音频解码错误不会被静默吞掉。

可在代码中直接使用桌面应用：

```python
from easyengine.desktop.app import run_window
from easyengine.galgame import load_script

story = load_script("assets/text/scripts/demo.json")
run_window(story)
```

### 7.9 图形化剧本编辑器

编辑器是位于 `editor/` 的独立可选工具，不修改 Galgame 核心或桌面玩家前端。安装依赖并启动：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r editor/requirements.txt
.venv/bin/python editor/main.py
# 启动时直接打开已有 JSON 剧本
.venv/bin/python editor/main.py assets/text/scripts/demo.json
```

Windows 使用 `.venv\Scripts\python.exe`，例如 `py -3 -m venv .venv` 后再安装依赖。

界面采用三栏布局：左侧管理场景/台词/选项，中间编辑剧本属性，右侧通过 `scan_assets()` 浏览资源。资源可以双击或拖入背景、BGM、语音和音效输入框。`goto`、`next`、起始场景均从已有场景 ID 下拉选择；选项 `require` 支持安全表达式或 JSON 条件树。

编辑器首次启动会显示不阻断操作的新手教程，中间表单提供中文标签和悬停提示；之后也可通过“帮助 → 新手教程”重新查看。

通过“工具 → 偏好设置...”或 `Ctrl+,` 可调整主题、字体、自动保存、启动时恢复剧本和默认资源目录；设置会保存在 Qt `QSettings` 中，并在适用时即时生效。

测试和保存都会先写入临时 JSON 并调用 `load_script()`；只有校验通过才会原子保存。校验失败时显示 `ScriptError`，不会覆盖旧文件。安装编辑器依赖后可运行 UI 与模型测试：

```bash
.venv/bin/python -m unittest discover -s editor/tests -v
```

更多操作说明见 [editor/README.md](./editor/README.md)。

---

## 8. 存读档

### 8.1 用法

```python
path = engine.save("slot1")
print(path)                 # .../saves/slot1.json

engine.load("slot1")
print(engine.list_saves())  # ("slot1",)
```

存档名规则：`[A-Za-z0-9_-]{1,64}`，不能包含 `/`、`..` 等路径字符。

`load()` 可以在尚未 `start()` 的引擎上直接调用，读档成功后引擎即进入存档状态。

### 8.2 存档内容

```json
{
  "engine": "EasyEngine",
  "author": "Sally-max114514",
  "version": 2,
  "script_title": "放学后的约定",
  "script_fingerprint": "0000000000000000000000000000000000000000000000000000000000000000",
  "state": {
    "scene_id": "walk_home",
    "line_index": 1,
    "variables": {
      "stats": {"affection": {"yuki": 2}},
      "flags": {"met_yuki": true},
      "route": "walk"
    },
    "background": "image/bg/sunset.png",
    "bgm": "audio/bgm/warm.mp3",
    "sprites": {
      "yuki": {
        "image": "image/characters/yuki/smile.png",
        "position": "right"
      }
    },
    "ended": false,
    "seen_lines": ["9:walk_home:0"]
  }
}
```

保存内容包括：

- 当前场景和行号
- 全部变量
- 当前背景、BGM
- 当前全部立绘
- 是否已结束、已读行记录
- 新存档绑定的规范化剧本 JSON SHA-256 指纹

### 8.3 兼容与行为

- 写入采用“临时文件 + 原子替换”，避免中途失败留下半个存档。
- 读档后当前行会**从头开始打字机显示**，不会恢复上次的可见字符数。
- 版本 `1` 与 `2` 都可读取；新写入的存档使用版本 `2`。
- 始终校验 `script_title`。有指纹的存档还会校验剧本内容；指纹不匹配会拒绝加载，避免旧行号映射到新剧情。
- 没有指纹的旧版存档在标题相同时仍可读取，但桌面端会提示“未验证”；这类存档无法检测同标题剧本是否被修改。
- 场景必须存在，行号必须有效（已结束的存档会夹到最后一行）。
- 回滚快照仅保留在本次运行内，读档后清空；已读行记录随存档保存。
- 桌面端保存时会尝试生成同名 PNG 缩略图；缩略图失败不会撤销已成功写入的 JSON 存档。
- 语音收藏单独存放于 `saves/voice-favorites.json`。存档不包含音频播放进度、界面设置或 CG 解锁状态；当前 CG 清单是静态展示，不做剧情解锁。

---

## 9. 常见问题

### `ModuleNotFoundError: No module named 'easyengine'`

从包含 `main.py` 的项目根目录运行，或设置 `PYTHONPATH`：

```bash
cd EasyEngine
python main.py
```

### `引擎尚未启动，请先调用 start()`

在调用 `advance()`、`choose()`、`tick()`、`reveal_all()`、`save()` 之前先执行：

```python
engine.start()
```

### `当前行有选项，请调用 choose(index)`

当前行包含 `choices`。文字显示完后应调用：

```python
engine.choose(choice.index)
```

`advance()` 不会自动选择选项。

### `选项尚未解锁`

该选项的 `require` 条件未满足。检查 `engine.view.variables` 和剧本里的 `require`。

### `选项下标越界`

`choose(index)` 使用的是 `GameView.choices` 的原始下标，不是 `available_choices` 过滤后的下标。始终使用 `ChoiceView.index`：

```python
for choice in engine.available_choices:
    engine.choose(choice.index)
```

### `找不到资源` / `AssetRef.path is None`

核心引擎允许资源缺失，但 `AssetRef.path` 会是 `None`。检查：

- 资源是否放在 `assets/` 下；
- 剧本引用是否相对于 `assets/`；
- 文件名是否与引用一致（查找不区分大小写）；
- 文件是否位于隐藏目录（默认跳过）。

### `剧本含未知字段`

剧本校验比较严格。例如把 `text` 写成 `txt` 会直接报错。按照第 6 节字段表检查。

### `goto` / `next 指向不存在的场景`

检查场景 id 拼写，并确保目标场景存在于 `scenes` 中。

### `不支持的存档版本`

当前写入版本为 `2`，并兼容读取版本 `1`。未知版本不能读取；保留旧文件或通过旧版本程序迁移后再试。

### `存档的剧本内容与当前版本不匹配`

新存档除标题外还会绑定剧本内容指纹。修改剧本后应使用新存档槽；同标题的无指纹旧版存档仍能读取，但会提示未验证。

### `python main.py` 返回 1

通常是示例剧本校验失败。运行：

```bash
python main.py --validate
```

查看具体错误。

### 音频/图片没有显示或播放

确认已安装桌面依赖并使用 `python main.py --play`。图片按剧本中的相对资源路径放入 `assets/image/`；音频放入 `assets/audio/`。窗口遇到缺失图片会显示占位提示；音频设备初始化失败时会提示静音运行。也可使用第 7.7 节将核心接入自定义 UI。

---

## 10. 扩展指南

### 新增资源分类

编辑 `easyengine/config.py`：

```python
EXTENSION_GROUPS: dict[str, frozenset[str]] = {
    # ...
    "font": frozenset({"ttf", "otf", "woff", "woff2"}),
}
```

`RESOURCE_GROUPS` 会自动包含新分类，启动时自动创建 `assets/font/`。如果有需要，还可以在 `config.py` 增加对应的子目录常量。

### 新增剧本字段

1. 在 `script.py` 的 `_LINE_KEYS` / `_SCENE_KEYS` / `_CHOICE_KEYS` 中加入字段；
2. 在对应数据类中加入属性；
3. 在 `_parse_line()` / `_parse_scene()` / `_parse_choices()` 中解析并校验；
4. 在 `engine.py` 中实现运行时行为，并通过 `GameEvent` 通知界面层。

### 新增事件

在 `engine.py` 中追加 `GameEvent("your_event", {...})`，并在文档/界面层处理。事件是单向瞬时通知，不进入存档。

### 接入 UI

推荐先实现一个适配层：

```python
class GameScreen:
    def __init__(self, engine):
        self.engine = engine

    def on_click(self):
        view = self.engine.view
        if view.ended:
            return
        if not view.text_complete:
            self.engine.reveal_all()
        elif not view.choices:
            self.engine.advance()

    def on_choice(self, choice):
        self.engine.choose(choice.index)

    def render(self):
        view = self.engine.view
        draw_background(view.background)
        draw_sprites(view.sprites)
        draw_text(view.speaker, view.visible_text)
        draw_choices(view.choices)
```

音频层监听 `bgm` / `se` 事件即可。

---

## 11. 当前限制

- 语音字幕同步按音频总时长估算文字速度，不支持逐字/逐词时间轴，也不做嘴型同步。
- 转场支持淡入、交叉淡化和左右滑动；暂不包含立绘动画、镜头移动或可编排的多阶段转场。
- CG 清单由剧本静态声明，当前没有剧情解锁、成就或缩略图分组机制。
- 条件表达式是受限的 Python-like 子集，不支持函数调用、任意 Python 代码或自定义脚本函数。
- 新存档以剧本内容指纹校验；没有指纹的旧版存档只能按标题兼容读取，界面会标记为未验证。
- 回滚历史仅在当前运行期间保存，不写入存档；存档不记录音频播放位置和界面设置。
- 桌面端是玩家用的运行界面；独立的可视化剧本编辑器位于 `editor/`。核心资源层只解析路径，图片/音频解码由桌面适配层负责。

---

## 12. 已验证内容

以下命令已在 Python 3.14.6 环境中实际运行：

```bash
python3 -m unittest discover -s tests -v
```

结果：24 项核心与打包测试全部通过。

```bash
python3 main.py --story assets/text/scripts/demo.json --validate
```

结果：剧本校验成功。仓库中的演示剧本引用了尚未随仓库提供的图片和音频文件，因此命令会列出缺失资源；核心引擎允许在资源未齐全时校验和运行剧情。桌面功能可使用 SDL dummy 驱动在无真实窗口/音频设备的环境中做冒烟验证。
