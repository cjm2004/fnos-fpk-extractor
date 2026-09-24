# 应用提取器 (fpk-extractor)

[![latest release](https://img.shields.io/github/v/release/cjm2004/fnos-fpk-extractor?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC&color=3b7cf0)](https://github.com/cjm2004/fnos-fpk-extractor/releases/latest)
[![platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-fnOS%20x86%20%2F%20ARM-12a150)](https://github.com/cjm2004/fnos-fpk-extractor)

带图形界面的飞牛 fnOS 应用：把应用中心里**已安装**的应用，一键还原成可以离线安装的 `.fpk`。

- **备份** —— 应用下架、版本回退不了时，手里还有安装包
- **离线安装** —— 给没有外网 / 纯内网的飞牛设备装应用
- **迁移** —— 把一台 NAS 上装好的应用搬到另一台

## 安装

1. 到 [Releases](https://github.com/cjm2004/fnos-fpk-extractor/releases/latest) 下载 `.fpk`
2. 飞牛桌面 →「应用中心」→ 右上角「**手动安装**」→ 选中它
3. 桌面上出现「应用提取器」图标，点开即用

支持 x86 与 ARM。装好后可以在应用里点「检查更新」升级。

## 使用

打开即自动扫描已安装应用，勾选要导出的，点「开始提取」：

- 实时进度与日志，可随时中止
- 结果可直接下载到电脑，或在共享文件夹 `fpk-extractor` 里取
- 右上角「更改」可自定义输出目录（填绝对路径，目录不存在会自动创建）

## 注意事项

- 以 **root** 运行，但**全程只读**：不修改、不删除任何已安装应用，也不会把用户数据打进包里
- 导出的是**当前安装状态**；包的架构沿用原应用，**不能跨架构使用**
- 卸载本应用**不会删除**已导出的 `.fpk`
- 请勿把导出的包用于商业传播或分发付费应用

## 自己构建

```bash
# 先把官方打包工具 fnpack 放进 tools/
#   下载：https://developer.fnnas.com/docs/cli/fnpack/
bash build.sh
```

需要 bash、tar、md5sum 和 Python 3（生成图标，纯标准库、无第三方依赖）。

> 改版本号时要**同时**改两处：`source/fpk-extractor/manifest` 的 `version`，
> 和 `app/bin/fpk-extract` 里的 `ENGINE_VER`。

## 技术要点

- `.fpk` 就是 tar.gz，成员为包根条目、没有顶层目录；`manifest.checksum` = `md5(app.tgz)`
- 反向打包 = 复制包根文件 + 把 `target/` 打成 `app.tgz` + 重算 checksum
- 桌面入口走飞牛**统一网关**（`/app/fpk-extractor`），http 与 https 下都能打开
- 后端只用 Python 3 标准库，前端是单文件 HTML，没有第三方依赖

命令行用法：`sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract --help`

窗口打不开时，先确认应用中心里状态是「运行中」，再看服务端日志：

```bash
cat /vol*/@appdata/fpk-extractor/server.log
```

## 关于

- 仓库：<https://github.com/cjm2004/fnos-fpk-extractor> ·
  问题反馈：<https://github.com/cjm2004/fnos-fpk-extractor/issues>
- 作者 / 发布者：**无名的小卒**
