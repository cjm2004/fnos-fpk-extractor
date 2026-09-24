# 应用提取器 (fpk-extractor)

[![latest release](https://img.shields.io/github/v/release/cjm2004/fnos-fpk-extractor?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC&color=3b7cf0)](https://github.com/cjm2004/fnos-fpk-extractor/releases/latest)
[![platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-fnOS%20x86%20%2F%20ARM-12a150)](https://github.com/cjm2004/fnos-fpk-extractor)

带**图形界面**的飞牛 fnOS 应用：扫描应用中心「已安装」的应用，勾选后一键还原成可离线安装的 `.fpk`。

产出的 `.fpk` 可以直接在应用中心用「手动安装」装回去，适用于：

- **备份**：重装系统后应用下架、版本回退不了时，手里还有安装包
- **离线安装**：给没有外网 / 纯内网的飞牛设备装应用
- **迁移**：把一台 NAS 上装好的应用搬到另一台

> 仓库：<https://github.com/cjm2004/fnos-fpk-extractor> · 作者 / 发布者：**无名的小卒**

---

## 一、安装 & 打开

**方式一（推荐）**：到 [Releases](https://github.com/cjm2004/fnos-fpk-extractor/releases/latest) 下载
`fpk-extractor_<版本>_all.fpk`。也可以直接用仓库根目录里同名的那份。

**方式二**：`git clone` 后自己 `bash build.sh` 打包（见第五节）。

然后：

1. 把 `fpk-extractor_1.0.0_all.fpk` 拷到飞牛 NAS 任意目录
2. 飞牛桌面 →「应用中心」→ 右上角「**手动安装**」→ 选中该 `.fpk`
3. 装好后飞牛桌面上出现**「应用提取器」**图标，点它即可打开操作窗口

装好之后可以在应用里点「检查更新」：本应用已接入「fnOS 应用更新管理器」，有新版本会直接提示，
点一下就能自动下载、校验并安装（见第六节）。

桌面入口只有一个，走飞牛的**统一网关**：`url` 是 `/app/fpk-extractor`，一个复用**当前域名和协议**的
相对路径。所以不管你用 `http://内网IP:5666` 还是 `https://域名` 打开飞牛桌面，点这个图标都能用 ——
它不会像「声明 `port` 的端口入口」那样在 https 下因混合内容被浏览器拦掉。

> 另：服务仍然在 **8520 端口**上监听（供 SSH 自检用，见第三节）。但那只是调试通道，桌面上不再有
> 对应的第二个图标 —— 端口入口在 https 下必定白屏，留着反而误导。

> 本应用以 **root** 权限运行：需要读取 `/var/apps/<应用>` 下所有应用的文件，普通应用用户没有这个权限。整个过程**只读**，不会修改或删除任何已安装应用，也不会把用户数据打进包里。

---

## 二、界面怎么用

打开窗口后是一页式操作界面：

```
┌─ 应用提取器 ────────────────────────────────── 输出目录: /vol1/fpk-extractor ┐
│                                                                              │
│  已安装应用        共 12 个应用              [刷新] [全选] [开始提取]        │
│  ─────────────────────────────────────────────────────────────────────────  │
│  ☑  影视中心       all        1.2 GB                                         │
│  ☑  qBittorrent    x86         68.4 MB      ← 勾选想导出的应用               │
│  ☐  Jellyfin       x86        412.7 MB                                       │
│                                                                              │
│  提取进度        成功 2 · 失败 0        [显示日志] [中止]                     │
│  ● 提取中…   正在处理：Jellyfin                                              │
│  ████████████████░░░░░░░░░░░░░░                                               │
│                                                                              │
│  已导出的安装包                                                              │
│  qbittorrent_4.6.2_x86.fpk      68.3 MB      [下载]                          │
│  jellyfin_10.9.0_x86.fpk       412.1 MB      [下载]                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **扫描**：打开即自动扫描，点「刷新」可重扫
- **多选**：逐个勾选，或用「全选」；大应用会显示体积，方便避开
- **提取**：点「开始提取」，进度条 + 实时日志同步刷新，可随时「中止」
- **取件**：结果列表里的 **下载** 按钮直接存到电脑；也可以在「文件管理器」→ 共享文件夹 **`fpk-extractor`** 里找到，或通过 SMB 拷贝

### 自定义输出目录

右上角「输出目录」旁的 **更改** 按钮可以随时换输出位置：

1. 点 **更改** → 填入**绝对路径**，例如 `/vol1/备份/fpk`（目录不存在会自动创建）；
2. 点 **保存** 立即生效，之后的提取都输出到那里；改过的目录会带一个「自定义」标记；
3. 点 **恢复默认** 回到共享文件夹 `fpk-extractor`。

也可以在「应用中心」→ 应用提取器 → **应用设置** 里填同一个路径，两处走的是同一份配置。

几条限制（有意为之）：

- 只接受**绝对路径**，相对路径会被拒绝（避免相对服务进程的工作目录产生难以预料的位置）；
- 不接受根目录 `/`，也不接受指向已存在文件的路径；
- 目录必须可写（本应用以 root 运行，一般不会遇到权限问题）；
- **提取任务进行中不能改**，会提示先等任务结束或中止。

每个包文件名形如 `应用名_版本_平台.fpk`（例：`zerotier_0.8.4_x86.fpk`）。输出目录里还会生成 `report.txt` / `report.tsv` 记录本次结果。

---

## 三、命令行用法（可选）

界面背后是一个 shell 打包引擎，同样可以直接在 SSH 里调用：

```bash
# 提取全部
sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract

# 只提指定应用
sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract --only qbittorrent,jellyfin

# 只看有哪些已安装应用（不打包）
sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract --list

# 指定输出目录
sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract --out /vol1/我的备份

# 帮助
sudo bash /var/apps/fpk-extractor/target/bin/fpk-extract --help
```

服务端口默认 **8520**，日志：

```bash
cat /vol*/@appdata/fpk-extractor/server.log          # 服务端日志
cat /vol*/@appdata/fpk-extractor/fpk-extract.log     # 提取日志
cat /vol*/@appdata/fpk-extractor/update-install.log  # 自动更新的安装日志
cat /vol*/@appdata/fpk-extractor/update.conf         # 更新配置（界面不提供入口，按需手改）
ls  /vol*/@appdata/fpk-extractor/updates/            # 已下载并校验过的更新包
```

窗口打不开 / 一片空白时，按顺序排查：

1. 应用中心里状态是否为「**运行中**」；
2. **确认访问方式**：本应用走统一网关（`/app/fpk-extractor`），http 与 https 下都可用，不存在混合内容问题。如果窗口仍是白的，说明请求没被转发到应用，跳到第 4 步看服务端日志（重点看有没有 `统一网关 Socket 就绪`）；
3. 端口 8520 是否被别的程序占用（占用会让启动失败，改源码里的端口重新打包即可）；
4. 看服务端日志有没有打印 `应用提取器已启动` 与 `统一网关 Socket 就绪`：

```bash
cat /vol*/@appdata/fpk-extractor/server.log
```

5. 检查网关 socket 是否生成：

```bash
ls -l /var/apps/fpk-extractor/target/app.sock
```

---

## 四、原理

`.fpk` 本质就是一个 **tar.gz**，内部固定为：

```
manifest          应用元数据（key = value）
app.tgz           应用文件（安装后解到 target/）
cmd/              生命周期脚本
config/privilege  运行身份声明
config/resource   资源声明
wizard/           安装/配置向导
ui/               桌面入口（可选）
ICON.PNG / ICON_256.PNG
*.sc              端口协议声明（可选）
```

关键点（已在真实 fpk 上逐项核对）：

1. **`manifest` 里的 `checksum` 字段 = `app.tgz` 的 MD5**（`md5sum`）
2. 应用安装后位于 `/var/apps/<appname>/`，其中：

   ```
   target -> /vol{n}/@appcenter/<appname>    应用文件
   etc / var / tmp / home / meta             指向存储卷的软链（运行时数据）
   cmd / config / wizard / manifest / ICON*.PNG    包根文件
   ```

3. 所以还原一个包 = **复制包根文件** + **把 `target/` 打成 `app.tgz`** + **重算 checksum**
   → 得到的结构与官方包一致，能被应用中心正常安装。
4. 导出时若原应用缺少标准生命周期脚本（`cmd/install_init` 等），会自动用空实现补齐，
   并写进日志，避免目标机安装时报缺文件。

提取引擎只用 bash + tar + md5sum 实现，**不依赖 fnpack，也不需要联网**；后端界面用飞牛自带的
`/usr/bin/python3`，无第三方依赖。

### 已验证

- 用真实第三方包 `zerotier_0.8.4_x86.fpk` 还原成「已安装」目录，再跑提取引擎：产物结构与原包一致、`checksum` 与 `md5(app.tgz)` 完全吻合
- 把产物解回工程结构后，**fnpack 官方打包工具校验通过**（`Packing successfully`）
- 界面全链路实测：扫描 → 多选 → 提取 → 实时日志 → 下载接口，前端 JS 通过语法检查
- 缺脚本的应用能被自动补齐到完整 9 个生命周期脚本
- 统一网关前缀实测：`/app/fpk-extractor/` 与直连 `/` 两种前缀下，首页注入、接口、图标、提取、下载全部通过（网关无斜杠的写法也兼容）
- 自定义输出目录实测：切换目录后产物确实落在新位置、配置落盘、重启后仍生效；相对路径 / 根目录 / 指向已存在文件 / 任务运行中修改 四种情况均被正确拒绝；传空可恢复默认
- **更新链路端到端实测**（自建假更新管理器 + 假 `appcenter-cli`）：`optional` / `forced` 两种模式、仅下载、
  一键更新、复用已下载的包不再重复下载、SHA-256 不匹配时丢弃文件、管理器连不上时降级，全部符合预期
- **对着真实管理器实测过「认不认得出来」**：正确 `app_key` 会拿到管理器返回的软件名 `应用提取器`；
  写错一个字符则得 404 +「软件不存在或已停用」；把地址指向一个关着的端口则报「连不上」—— 三种情况不混淆
- **界面用无头浏览器实测**：40 项断言全通过 —— 横幅出现时机、强制遮罩不可关闭（ESC / 点空白 / 去掉
  `locked` class 都挡得住）、遮罩层级铺满视口、界面上不存在任何更新设置入口、「检查更新」的四种
  反馈（检查中 / 已是最新 / 发现新版 / 标识不对 / 连不上）、深色与浅色两种配色对比度
- 复核构建产物：包根无顶层目录、`checksum` 与 `md5(app.tgz)` 完全吻合、`app.tgz` 内无 `__pycache__`

---

## 五、目录说明

```
fnos-fpk-extractor/
├── fpk-extractor_1.0.0_all.fpk   ← 成品安装包（根目录只放当前版本）
├── build.sh                      ← 一键重新打包
├── README.md
├── source/
│   ├── gen-icon.py               ← 图标生成（纯标准库，无第三方依赖）
│   └── fpk-extractor/            ← FPK 工程源码
│       ├── manifest              ← 应用元数据（版本号 / 署名 / 更新说明）
│       ├── config/{privilege,resource}
│       ├── cmd/                  ← 9 个生命周期脚本（main 负责服务启停）
│       ├── wizard/{install,config}
│       ├── app/bin/fpk-extract   ← 提取引擎（shell，核心打包逻辑）
│       ├── app/bin/fallback/     ← 图标兜底
│       ├── app/server/server.py  ← 后端服务（Python 3 标准库，含更新模块）
│       ├── app/www/index.html    ← 前端界面（单文件，无外部依赖）
│       └── app/ui/config         ← 桌面入口（统一网关，单一入口）
└── tools/                        ← 放 fnpack（需自行下载，见下）
```

### 两种桌面入口是怎么接的

飞牛桌面入口的 URL 拼接规则是 `{protocol}://{当前浏览器hostname}:{port}{url}`，所以：

- **端口入口**只在 http 直连下成立。若用户用 **https 域名**打开飞牛桌面，HTTPS 页面里加载 http iframe 属于
  **混合内容**，浏览器直接拒绝渲染 → 白屏。服务端一切正常，从日志里看不出问题。
  **所以本应用最终没有采用这种方式**（开发过程中曾栽在这里，表现为点开桌面图标一片空白）。
- **统一网关入口**复用飞牛自己的域名：`ui/config` 里 `protocol` 留空、声明
  `gatewayPrefix=/app/fpk-extractor` 与 `gatewaySocket=app.sock`，由飞牛校验登录态后把
  `/app/fpk-extractor/**` 转发到 `/var/apps/fpk-extractor/target/app.sock`。
  因为 `url` 是**相对当前域名**的路径，http 与 https 下都成立，所以桌面只需要这一个入口。

因此后端 `server.py` **同时监听两路**：`target/app.sock`（统一网关，桌面实际走的就是这条）
与 TCP `0.0.0.0:8520`（保留作 SSH / curl 自检的调试通道，不对应桌面图标），
路由层剥掉 `/app/fpk-extractor` 前缀后走同一套逻辑；返回首页时把前端里的 `__BASE__`
占位符替换成当前访问前缀（直连为 `/`，网关为 `/app/fpk-extractor/`），让所有接口请求自动带上正确前缀。

### 重新打包

```bash
# 1) 先准备 fnpack（官方打包工具，仓库不附带，需自行下载）
#    从 https://developer.fnnas.com/docs/cli/fnpack/ 获取，然后：
#      · Windows：把 fnpack.exe 放进 tools/
#      · Linux / macOS：解出 fnpack 放进 tools/，或直接装进 PATH
# 2) 打包
bash build.sh
```

`build.sh` 会自动完成：生成图标 → 清理 `__pycache__` → 调 `fnpack build` → 给包根补一份 `ui/` →
把成品挪到仓库根目录。产物名形如 `fpk-extractor_<版本>_all.fpk`，版本号取自 `manifest`。

构建脚本会在 fnpack 产物基础上，把 `ui/` 再补一份到包根——fnpack 官方把 ui 打进 `app.tgz`
（安装后即 `target/ui`），社区包习惯在包根再放一份，两处内容相同最保险。
注意这是改**外层 tar**，没有动 `app.tgz`，所以 `manifest` 里的 `checksum` 依然有效。

> 改版本号时记得**同时**改 `source/fpk-extractor/manifest` 的 `version` 和
> `source/fpk-extractor/app/bin/fpk-extract` 里的 `ENGINE_VER`，并顺手更新 `changelog`。

---

## 六、应用内更新（对接 fnOS 应用更新管理器）

本应用已接入 **fnOS 应用更新管理器**（默认地址 `http://nas.192321.xyz:18080`），可以在界面里直接检查并更新自己。

- **检查**：默认「打开应用时自动检查」；也可以随时点右上角 **检查更新** 手动查。
- **可选更新**：顶部出现一条横幅，点「查看更新」能看到版本号、更新说明、体积，再决定要不要更新。
- **强制更新**（管理器返回 `update_mode = forced`）：界面会被一层**不可关闭的遮罩**挡住 ——
  没有关闭按钮，ESC 和点空白处都无效，只能先更新完再用，符合管理器的要求。
- **怎么更新**：点 **立即更新** = 下载 → 校验 SHA-256 → 调用系统 `appcenter-cli install-fpk` 安装 → 重启。
  全程有进度条和日志；装完应用会自己重启，界面自动回到新版本并给一句「更新完成」的提示。
- **怎么知道该问哪个软件**：靠一行 `app_key`，本应用的取值是 **`fpk-extractor`**，
  必须和更新管理器「软件管理」里那条记录的**唯一标识 app_key 逐字符一致**（软件名称显示成什么无所谓）。
  对不上时管理器会回 HTTP 404 `{"error":"软件不存在或已停用"}`，界面会直接点名：
  「更新管理器不认这个应用标识 app_key=xxx」。三种结果分得很清楚，不会互相混淆：

  | 情况 | 界面表现 |
  |---|---|
  | 管理器认得这个 app_key，但没有新版本 | 「已是最新版本」（绿色） |
  | 管理器**不认**这个 app_key | 红字点名 app_key 的实际取值，明确说标识不对 |
  | 网络 / 域名解析 / 端口不通 | 「连不上更新管理器」+ 具体原因，与上一条区分开 |

  > 也就是说：点一次「检查更新」，如果看到的是「已是最新版本」而**不是**「连不上」，
  > 就说明 app_key 是对的、链路是通的。
  > 当前管理器里「应用提取器」记录（app_key `fpk-extractor`）尚未发布任何版本，
  > 所以现在查会显示「已是最新版本」；在管理器里发布新版本之后才会提示更新。

- **不提供更新设置**：界面上只有「检查更新」这一个动作，检测到新版本后按 `update_mode` 走 ——
  可选就由用户决定，强制就必须更新完才能用。管理器地址、`app_key`、渠道这些由 `var/update.conf`
  决定（默认值已配好，一般不用动；确有需要可直接编辑该文件）。

几个刻意保守的地方：

- 检查更新走的是管理器的**公开接口** `GET /api/check-update`（无需登录）。而 `/api/download`、
  `/api/tasks/*`、`/api/software` 这些**需要管理员登录**，普通应用拿不到，所以**下载和校验自己做**：
  按管理器给的 `direct_url` 流式下载，比对 `sha256`，再确认它确实是个合法的 `.fpk`
  （tar.gz 且含 `manifest` + `app.tgz`）才落盘；校验不过就地把文件删掉。
- 管理器**连不上时静默降级**：只提示一句，绝不抛异常，不影响「扫描 / 提取」这两个主功能。
- 管理器只给了网盘链接（没有 `direct_url`）时不硬来，界面直接把链接给你手动下载。
- 「安装中」是瞬时状态：如果安装命令发出后 **5 分钟**应用还没重启成新版本，会明确报失败，并提示到
  「应用中心 → 手动安装」重试 —— 而不是假装一直在装。

> 自动安装调用的是飞牛自带的 `appcenter-cli install-fpk`。官方注明「手动安装仅用于测试用途」，
> 若你的设备上该命令不可用，界面会提示改用手动安装。
>
> 更新模块的配置与状态都落在 `var/update.conf`、`var/update.pending`、`var/updates/`，
> 卸载应用会一并清掉，不影响已导出的 `.fpk`。

---

## 七、注意事项

- 提取的是**当前安装状态**：即 `target/` 目录里现存的文件。
- 提取时会跳过 `etc/var/tmp/home/meta/shares` 等运行时目录与所有软链，**不会把用户数据打进包里**。
- 若某应用缺少图标，会用本应用的图标兜底，避免因缺图标装不上。
- 大应用体积可观（Plex / Emby / Immich 等单个可能上百 MB 到 1 GB+），请留意共享目录所在存储空间的剩余容量。
- `platform = all`：本应用是 shell + Python 标准库实现，x86 与 ARM 飞牛设备都能装。
  提取出来的其他应用包，其 `platform` 字段沿用原应用，**不能跨架构使用**（x86 的包不要装到 ARM 机器上）。
- 从商店下架的官方应用，本工具同样能导出（只要它还装在机器上）。
- 卸载本应用**不会删除**已导出的 `.fpk` 文件。
- 服务监听 **`target/app.sock`**（桌面入口走这条）与 **8520 端口**（仅作 SSH 自检用的调试通道，
  桌面没有对应图标）。8520 会在局域网内可达，请勿把该端口直接暴露到公网；
  经统一网关访问时由飞牛先做登录态校验，相对更安全。
- 请勿将导出的包用于商业传播或分发付费应用。

---

## 八、关于

- 作者 / 发布者：**无名的小卒**
- 仓库：<https://github.com/cjm2004/fnos-fpk-extractor>
- 问题反馈 / 建议：<https://github.com/cjm2004/fnos-fpk-extractor/issues>
- 打包用到的官方工具：[fnpack](https://developer.fnnas.com/docs/cli/fnpack/) ·
  飞牛开发者文档：<https://developer.fnnas.com/docs/>

本应用以 **root** 权限运行，但整个过程**只读**：只读取 `/var/apps` 下已安装应用的文件，
不修改、不删除任何已安装应用，也不会把用户数据打进包里。代码全部是 shell + Python 3 标准库 +
单文件 HTML，没有第三方依赖，也没有联网上传行为（除了你自己配置的更新管理器）。
欢迎自行审阅 `source/fpk-extractor/` 下的全部源码。
