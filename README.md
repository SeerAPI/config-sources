# Seer Config Source

赛尔号游戏配置数据自动提取工具

## 简介

本项目用于自动获取 [SeerAPI](https://github.com/SeerAPI) 项目所使用的赛尔号客户端（Flash、HTML5、Unity）配置数据。

## 功能特性

### 多平台支持

- **Flash 版本**：从 SWF 文件中提取 XML 与 AMF3 格式的配置
- **HTML5 版本**：从官方服务器批量下载配置文件
- **Unity 版本**：从 GitHub 仓库获取配置并通过 solaris 解析

### 核心功能

- **AMF3 数据解析器**：完整支持 ActionScript 3 ByteArray 格式的二进制数据解析
- **SWF 文件处理**：支持压缩/解压 SWF 文件，提取资源和数据
- **版本管理**：自动检测配置版本变化，仅在有更新时执行提取
- **异步下载**：支持并发下载，提高数据获取效率
- **自动化部署**：通过 GitHub Actions 每日自动运行并提交更新

## 使用方法

### 安装依赖

```bash
uv sync
```

### 手动运行

```bash
uv run _scripts/update_config.py
```

### 自动化运行

项目配置了 GitHub Actions 工作流，每日 10:00 UTC 自动执行配置更新。

## 输出目录结构

```
flash/    # Flash 版本配置（XML 格式）
html5/    # HTML5 版本配置
unity/    # Unity 版本配置
```

每个目录包含 `.version` 文件用于跟踪当前配置版本。

## 技术栈

- **Python 3.10+**
- **httpx** - 异步 HTTP 客户端
- **GitPython** - Git 仓库操作
- **xmltodict** - XML 数据转换
- **solaris** - Unity 配置数据解析库
- **pytz** - 时区处理

## 许可

本项目仅用于学习和研究目的，严禁用于商业用途，使用者应自行承担相应的法律风险。
