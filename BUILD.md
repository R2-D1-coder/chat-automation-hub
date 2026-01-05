# PyInstaller 打包说明

本说明文档介绍如何使用 PyInstaller 将微信群发自动化工具打包成独立的可执行文件。

## 📦 打包步骤

### 1. 安装依赖

确保已安装所有依赖（包括 PyInstaller）：

```powershell
pip install -r requirements.txt
```

### 2. 执行打包

运行打包脚本：

```powershell
build.bat
```

或者手动执行 PyInstaller：

```powershell
pyinstaller --clean --noconfirm chat-automation-hub.spec
```

### 3. 获取打包结果

打包完成后，可执行文件位于：
- `dist/chat-automation-hub.exe`

## 📁 打包内容

打包后的可执行文件包含：
- ✅ 所有 Python 依赖库
- ✅ Web 模板文件（`web/templates/`）
- ✅ 资源文件（`assets/` 目录）
- ✅ 配置文件（`config.json`）

## 🚀 运行打包后的程序

### 方式一：直接运行

双击 `dist/chat-automation-hub.exe` 或在命令行运行：

```powershell
cd dist
.\chat-automation-hub.exe
```

### 方式二：分发程序

如果要分发程序给其他用户，需要：

1. **必需文件**：
   - `chat-automation-hub.exe`（可执行文件）
   - `config.json`（配置文件，首次运行后会自动生成默认配置）

2. **可选文件**（如果配置中使用了）：
   - `assets/` 目录（包含图片等资源）

3. **数据文件**（运行时自动创建）：
   - `output/` 目录（日志、数据库等）

## ⚙️ 配置文件说明

首次运行后，程序会在可执行文件同目录下查找 `config.json`。如果不存在，程序会使用默认配置。

建议在打包后，将 `config.json` 放在与 `chat-automation-hub.exe` 相同的目录下。

## 📝 打包配置说明

### spec 文件配置项

- **主程序入口**：`run_web.py`
- **控制台模式**：`console=True`（显示控制台窗口以便查看日志）
- **数据文件**：自动包含 `config.json`、`web/templates/` 和 `assets/`
- **隐藏导入**：包含 Flask、APScheduler、uiautomation 等所有必要的模块

### 自定义配置

如果需要修改打包配置，编辑 `chat-automation-hub.spec` 文件：

- **添加图标**：在 `exe` 部分设置 `icon='路径/图标.ico'`
- **隐藏控制台**：将 `console=True` 改为 `console=False`（不推荐，会无法查看日志）
- **添加额外文件**：在 `datas` 列表中添加 `('源路径', '目标路径')` 元组

## 🔧 常见问题

### 1. 打包失败：缺少模块

**问题**：打包时报错 "ModuleNotFoundError"

**解决**：在 `chat-automation-hub.spec` 的 `hiddenimports` 列表中添加缺失的模块名

### 2. 运行时找不到模板文件

**问题**：程序启动后显示 "Template not found"

**解决**：检查 `datas` 配置是否包含 `('web/templates', 'web/templates')`

### 3. 文件体积过大

**问题**：打包后的 exe 文件很大（可能几百MB）

**解决**：这是正常的，因为包含了 Python 解释器和所有依赖库。可以使用 UPX 压缩（已在配置中启用）

### 4. 杀毒软件报毒

**问题**：部分杀毒软件可能误报打包后的 exe

**解决**：这是 PyInstaller 打包程序的常见问题，可以：
- 将程序添加到杀毒软件白名单
- 使用代码签名证书签名 exe 文件
- 使用在线扫描服务验证（如 VirusTotal）

### 5. 打包后无法连接数据库

**问题**：程序无法创建或访问 SQLite 数据库

**解决**：确保程序有写入权限，`output/` 目录会自动创建

## 📊 打包体积参考

- **打包前**（源代码）：约 1-2 MB
- **打包后**（单文件 exe）：约 150-300 MB（取决于依赖）

## 🔍 调试打包问题

如果打包后程序无法正常运行：

1. **查看控制台输出**：检查是否有错误信息
2. **检查依赖**：确认所有必需的模块都已包含
3. **测试环境**：在干净的 Windows 系统上测试打包结果
4. **详细日志**：运行程序时查看控制台输出的详细错误信息

## 📚 更多信息

- [PyInstaller 官方文档](https://pyinstaller.readthedocs.io/)
- [项目 README](README.md)



