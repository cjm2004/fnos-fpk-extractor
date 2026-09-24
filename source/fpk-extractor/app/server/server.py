#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用提取器 (fpk-extractor) — 后端服务

只用 Python 3 标准库（飞牛 fnOS 自带 /usr/bin/python3）。
职责：
  · 扫描 /var/apps 下已安装的应用，返回给前端展示
  · 接收前端选择，调用打包引擎 app/bin/fpk-extract 执行提取
  · 把引擎输出实时回传为进度日志
  · 提供已导出 .fpk 的直接下载

打包这件事本身仍由 app/bin/fpk-extract（shell）负责，保证与命令行用法完全一致。
"""
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote

# ------------------------------------------------------------------ 基础路径
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.dirname(HERE)                       # target/
WWW_DIR = os.path.join(TARGET, "www")
ENGINE = os.path.join(TARGET, "bin", "fpk-extract")


def _find_bash():
    """定位负责执行打包引擎的 bash：飞牛上就是 /bin/bash"""
    for c in (os.environ.get("FPK_BASH"), "/bin/bash", "/usr/bin/bash", "/usr/local/bin/bash"):
        if c and os.path.isfile(c):
            return c
    return shutil.which("bash") or "/bin/bash"


BASH = _find_bash()

SELF = os.environ.get("TRIM_APPNAME") or "fpk-extractor"
APPS_ROOT = os.environ.get("APPS_ROOT") or "/var/apps"
VAR_DIR = os.environ.get("TRIM_PKGVAR") or "/tmp"
PORT = int(os.environ.get("TRIM_SERVICE_PORT") or 8520)
HOST = os.environ.get("FPK_HOST") or "0.0.0.0"

# ---- 统一网关（https 域名访问）--------------------------------------------
# 飞牛在 https 域名下会把 /app/<appname> 的请求转发到 target/app.sock，
# 且【保留路径前缀】。所以同一个 Handler 必须能同时吃两种前缀。
GATEWAY_PREFIX = "/app/" + SELF
SOCK_PATH = os.path.join(TARGET, "app.sock")
ICON_DIR = os.path.join(TARGET, "ui", "images")

LOG_LIMIT = 400                                       # 内存里保留的日志行数


def split_base(path):
    """按访问方式拆出 (base, inner)。
       base  —— 前端拼接口路径用的前缀，直连是 "/"，网关是 "/app/<appname>/"
       inner —— 去掉前缀后用于路由的路径"""
    if path == GATEWAY_PREFIX or path.startswith(GATEWAY_PREFIX + "/"):
        return GATEWAY_PREFIX + "/", (path[len(GATEWAY_PREFIX):] or "/")
    return "/", path


# ------------------------------------------------------------------ 工具函数
def manifest_get(path, key):
    """读取 manifest 里的 key（容忍 key=value / key = value / 值带引号）"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip()
    except OSError:
        pass
    return ""


def dir_size(path):
    """目录占用（软链不跟随），失败时忽略"""
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def human(n):
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


OUT_CONF = os.path.join(VAR_DIR, "outdir.conf")       # 用户自定义的输出目录


def load_custom_out():
    """读取用户自定义的输出目录，没设置过返回空串"""
    try:
        with open(OUT_CONF, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def check_out_dir(path):
    """校验输出目录：必须是绝对路径、能创建、可写。返回 (是否通过, 绝对路径或错误说明)"""
    raw = (path or "").strip()
    if not raw:
        return False, "路径不能为空"
    raw = os.path.expanduser(raw)
    # 注意：必须用原样输入判断是否绝对路径，abspath() 之后永远为真
    if not os.path.isabs(raw):
        return False, "请填写绝对路径，例如 /vol1/备份/fpk"
    p = os.path.abspath(raw)
    if os.path.dirname(p) == p:                       # 根目录
        return False, "不能使用根目录作为输出目录"
    if os.path.exists(p) and not os.path.isdir(p):
        return False, "该路径已存在且不是目录：%s" % p
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as exc:
        return False, "无法创建目录：%s" % exc
    if not os.access(p, os.W_OK):
        return False, "目录不可写：%s" % p
    return True, p


def resolve_out():
    """定位输出目录：用户自定义 > 应用共享目录 > 兜底"""
    custom = load_custom_out()
    if custom:
        ok, res = check_out_dir(custom)
        if ok:
            return res

    p = (os.environ.get("TRIM_DATA_SHARE_PATHS") or "").split(":")[0].strip()
    if p:
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            pass
        if os.path.isdir(p):
            return p
    for cand in ("/var/apps/%s/shares" % SELF, "/var/apps/%s/share" % SELF):
        if os.path.isdir(cand):
            subs = []
            try:
                subs = [os.path.join(cand, d) for d in sorted(os.listdir(cand))]
            except OSError:
                pass
            subs = [d for d in subs if os.path.isdir(d)]
            return subs[0] if subs else cand
    for pat in ("/vol*/" + SELF, "/vol*/*/" + SELF):
        for d in sorted(glob.glob(pat)):
            if os.path.isdir(d):
                return d
    p = os.path.join(VAR_DIR, "output")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


OUT_DIR = resolve_out()


def out_is_custom():
    """当前输出目录是不是用户自定义的那个"""
    c = load_custom_out()
    return bool(c) and os.path.abspath(c) == os.path.abspath(OUT_DIR)


def set_out_dir(path):
    """运行时切换输出目录；传空串表示恢复默认"""
    global OUT_DIR
    with JOB_LOCK:
        if JOB.get("running"):
            return False, "提取任务进行中，请等它结束或中止后再修改输出目录"

    if not (path or "").strip():                      # 恢复默认
        try:
            if os.path.exists(OUT_CONF):
                os.unlink(OUT_CONF)
        except OSError as exc:
            return False, "恢复默认失败：%s" % exc
        OUT_DIR = resolve_out()
        return True, OUT_DIR

    ok, res = check_out_dir(path)
    if not ok:
        return False, res
    try:
        os.makedirs(VAR_DIR, exist_ok=True)
        with open(OUT_CONF, "w", encoding="utf-8") as fh:
            fh.write(res + "\n")
    except OSError as exc:
        return False, "保存设置失败：%s" % exc
    OUT_DIR = res
    return True, res


# ------------------------------------------------------------------ 扫描
SCAN_LOCK = threading.Lock()
SIZE_LOCK = threading.Lock()
SIZE_CACHE = {}
SIZES_BUSY = False


def scan_apps():
    """扫描已安装应用（不计算体积，保证响应速度）"""
    apps = []
    try:
        entries = sorted(os.listdir(APPS_ROOT))
    except OSError:
        return apps
    for name in entries:
        d = os.path.join(APPS_ROOT, name)
        mf = os.path.join(d, "manifest")
        if not os.path.isdir(d) or not os.path.isfile(mf):
            continue
        appname = manifest_get(mf, "appname") or name
        if appname == SELF:
            continue
        target = os.path.join(d, "target")
        with SIZE_LOCK:
            size = SIZE_CACHE.get(appname)
        apps.append({
            "name": appname,
            "dir": d,
            "display_name": manifest_get(mf, "display_name") or appname,
            "version": manifest_get(mf, "version") or "-",
            "platform": manifest_get(mf, "platform") or "all",
            "source": manifest_get(mf, "source") or "",
            "service_port": manifest_get(mf, "service_port") or "",
            "size": size,
            "ok": os.path.isdir(target),
        })
    return apps


def scan_sizes_async():
    """后台补齐应用体积，避免阻塞接口"""
    global SIZES_BUSY
    with SIZE_LOCK:
        if SIZES_BUSY:
            return
        SIZES_BUSY = True

    def worker():
        global SIZES_BUSY
        try:
            for name in sorted(os.listdir(APPS_ROOT)):
                d = os.path.join(APPS_ROOT, name)
                mf = os.path.join(d, "manifest")
                if not os.path.isfile(mf):
                    continue
                appname = manifest_get(mf, "appname") or name
                with SIZE_LOCK:
                    if appname in SIZE_CACHE:
                        continue
                tgt = os.path.join(d, "target")
                sz = dir_size(tgt) if os.path.isdir(tgt) else 0
                with SIZE_LOCK:
                    SIZE_CACHE[appname] = sz
        finally:
            with SIZE_LOCK:
                SIZES_BUSY = False

    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ 任务
JOB = {
    "running": False,
    "phase": "idle",        # idle | running | done | error
    "total": 0,
    "done": 0,
    "failed": 0,
    "current": "",
    "log": [],
    "results": [],
    "out": OUT_DIR,
    "started": 0,
    "finished": 0,
    "message": "",
}
JOB_LOCK = threading.Lock()
PROC = None


def job_log(line):
    line = line.rstrip("\n")
    if not line:
        return
    with JOB_LOCK:
        JOB["log"].append(line)
        if len(JOB["log"]) > LOG_LIMIT:
            del JOB["log"][:len(JOB["log"]) - LOG_LIMIT]
        m = re.search(r"^[\d\-]+ [\d:]+ \[(\d+)\] 提取 (.+)$", line)
        if m:
            JOB["current"] = m.group(2)
        if "✓" in line:
            JOB["done"] += 1
            JOB["current"] = ""
            mm = re.search(r"✓\s+(\S+)\s+(\S+)\s+→\s+(\S+)\s+\((.+)\)", line)
            if mm:
                JOB["results"].append({
                    "name": mm.group(1), "version": mm.group(2),
                    "file": mm.group(3), "size": mm.group(4),
                })
        if "! " in line and ("失败" in line or "跳过" in line):
            JOB["failed"] += 1


def job_worker(apps):
    global PROC
    cmd = [BASH, ENGINE, "--scope", "all", "--out", OUT_DIR]
    if apps:
        cmd += ["--only", ",".join(apps)]
    try:
        PROC = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )
        for line in PROC.stdout:
            job_log(line)
        rc = PROC.wait()
    except Exception as exc:                       # noqa: BLE001
        job_log("[服务] 启动打包引擎失败：%s" % exc)
        rc = -1
    finally:
        PROC = None

    with JOB_LOCK:
        JOB["running"] = False
        JOB["finished"] = int(time.time())
        JOB["current"] = ""
        if rc == 0:
            JOB["phase"] = "done"
            JOB["message"] = "提取完成：成功 %d 个，失败 %d 个" % (JOB["done"], JOB["failed"])
        else:
            JOB["phase"] = "error"
            JOB["message"] = "提取中断（退出码 %s），请查看日志" % rc


def start_job(apps):
    with JOB_LOCK:
        if JOB["running"]:
            return False, "已有提取任务在执行"
        JOB.update({
            "running": True, "phase": "running", "total": len(apps) or 0,
            "done": 0, "failed": 0, "current": "", "log": [], "results": [],
            "out": OUT_DIR, "started": int(time.time()), "finished": 0, "message": "",
        })
    threading.Thread(target=job_worker, args=(apps,), daemon=True).start()
    return True, ""


def cancel_job():
    global PROC
    if PROC is None:
        return False
    try:
        os.killpg(os.getpgid(PROC.pid), signal.SIGTERM)
        return True
    except OSError:
        return False


def list_results():
    """扫输出目录里现成的 .fpk"""
    out = []
    try:
        for fn in sorted(os.listdir(OUT_DIR)):
            if not fn.lower().endswith(".fpk"):
                continue
            fp = os.path.join(OUT_DIR, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            out.append({"file": fn, "size": human(st.st_size), "mtime": int(st.st_mtime)})
    except OSError:
        pass
    out.sort(key=lambda x: -x["mtime"])
    return out


# ------------------------------------------------------------------ 更新管理器
# 对接「fnOS 应用更新管理器」的 HTTP JSON 协议。
#
# 实测要点（决定了这里的实现方式）：
#   · GET /api/check-update 是**公开**接口，可直接调用；
#   · /api/download、/api/tasks/{id}、/api/software 等**需要管理员登录**（401），
#     普通应用调不通，也绝不能把管理员密码内置进应用，所以更新包由本应用自己按
#     direct_url 下载、自己校验 SHA-256。
UPD_CONF = os.path.join(VAR_DIR, "update.conf")
UPD_DIR = os.path.join(VAR_DIR, "updates")
UPD_PENDING = os.path.join(VAR_DIR, "update.pending")
UPD_DEFAULT = {
    "enabled": True,
    "base_url": "http://nas.192321.xyz:18080",
    "fallback_url": "http://127.0.0.1:18080",     # 管理器就跑在本机，域名解析不通时兜底
    "app_key": "fpk-extractor",
    "channel": "stable",
    "check_on_open": True,
    "auto_install": True,
}
UPD_LOCK = threading.Lock()
UPD_CACHE = {"ts": 0.0, "data": None}
UPD_DL = {
    "running": False, "phase": "", "progress": 0, "total": 0,
    "file": "", "path": "", "error": "", "verified": False, "log": [],
    "install_started": 0.0,
}
UPD_CLI_PATHS = ("/usr/bin/appcenter-cli", "/usr/local/bin/appcenter-cli",
                 "/usr/sbin/appcenter-cli")
CACHE_TTL = 60.0
INSTALL_TIMEOUT = 300.0     # 安装命令发出后多久还没重启成新版本，就认为失败


def cur_version():
    """本应用当前版本：优先读系统注入的 TRIM_APPVER，退回读 manifest"""
    v = (os.environ.get("TRIM_APPVER") or "").strip()
    if v:
        return v
    return manifest_get(os.path.join(os.path.dirname(TARGET), "manifest"), "version") or "0.0.0"


def normalize_base(u):
    """规范化管理器地址：必须是 http(s) 开头，去掉结尾斜杠"""
    u = (u or "").strip().rstrip("/")
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return ""


def load_update_conf():
    cfg = dict(UPD_DEFAULT)
    try:
        with open(UPD_CONF, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            for k in UPD_DEFAULT:
                if k in d:
                    cfg[k] = d[k]
    except (OSError, ValueError):
        pass
    return cfg


def public_update_cfg(cfg=None):
    """把更新配置回给前端。界面不给用户改配置，这里只用其中的 enabled /
       check_on_open 决定「要不要自动检查」。"""
    return dict(cfg or load_update_conf())


def upd_bases(cfg):
    out = []
    for u in (cfg.get("base_url"), cfg.get("fallback_url")):
        u = normalize_base(u)
        if u and u not in out:
            out.append(u)
    return out


def http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={
        "User-Agent": "fpk-extractor/%s" % cur_version(),
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


def check_update(force=False):
    """问一次更新管理器。连不上/出错都返回结构化结果，绝不抛异常影响主功能。"""
    cfg = load_update_conf()
    ver = cur_version()
    if not cfg.get("enabled"):
        return {"ok": True, "enabled": False, "current_version": ver,
                "update_available": False, "update_mode": "none",
                "config": public_update_cfg(cfg),
                "error": ""}

    with UPD_LOCK:
        if (not force and UPD_CACHE["data"]
                and (time.time() - UPD_CACHE["ts"]) < CACHE_TTL):
            return UPD_CACHE["data"]

    key = cfg.get("app_key") or SELF
    chan = cfg.get("channel") or "stable"
    q = urllib.parse.urlencode({"app_key": key, "current_version": ver, "channel": chan})
    # 三种结果要分清，不能一律当成「连不上」：
    #   · 拿到 JSON        → 管理器认得这个 app_key
    #   · HTTP 4xx + JSON  → 地址通、是我们自己的管理器，但它不认这个 app_key
    #   · 其它异常         → 网络不通 / 域名解析失败 / 端口不通
    data, used, last_err = None, "", ""
    http_code, http_msg = 0, ""
    for base in upd_bases(cfg):
        try:
            data = http_json("%s/api/check-update?%s" % (base, q))
            used = base
            break
        except urllib.error.HTTPError as exc:
            http_code = exc.code
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
                http_msg = (json.loads(body) or {}).get("error") or ""
            except Exception:
                http_msg = ""
            last_err = "%s：HTTP %s %s" % (base, exc.code, http_msg or body[:120].strip())
            if http_msg:            # 管理器明确答复了，换备用地址也没意义
                break
        except Exception as exc:                      # 网络/解析错误
            last_err = "%s：%s" % (base, exc)

    if data is None:
        res = {"ok": False, "enabled": True, "current_version": ver,
               "app_key": key, "channel": chan, "base_url": "",
               "software": "", "update_available": False,
               "update_mode": "none", "config": public_update_cfg(cfg),
               "key_missing": bool(http_msg),
               "error": ("更新管理器不认这个应用标识 app_key=%s：%s" % (key, http_msg)
                         if http_msg else
                         "连不上更新管理器（%s）" % (last_err or "未知错误"))}
        return res

    avail = bool(data.get("update_available"))
    res = {
        "ok": True, "enabled": True, "base_url": used,
        "app_key": key, "channel": chan,
        "software": data.get("software") or "",
        "current_version": data.get("current_version") or ver,
        "update_available": avail,
        "update_mode": data.get("update_mode") or ("optional" if avail else "none"),
        "version": data.get("version") or "",
        "release_notes": data.get("release_notes") or "",
        "direct_url": data.get("direct_url") or "",
        "cloud_url": data.get("cloud_url") or "",
        "sha256": (data.get("sha256") or "").strip().lower(),
        "file_name": data.get("file_name") or "",
        "size": data.get("size") or 0,
        "min_version": data.get("min_version") or "",
        "requires_restart": bool(data.get("requires_restart")),
        "config": public_update_cfg(cfg),
        "error": data.get("error") or "",
    }
    with UPD_LOCK:
        UPD_CACHE["ts"] = time.time()
        UPD_CACHE["data"] = res
    return res


def dl_log(msg):
    UPD_DL["log"].append("%s %s" % (time.strftime("%H:%M:%S"), msg))
    del UPD_DL["log"][:-200]


def _pkg_name(url, version):
    """从直链里推文件名，推不出来就用 app_key_版本_all.fpk"""
    name = os.path.basename(unquote(urlparse(url).path or ""))
    name = os.path.basename(name)
    if name.lower().endswith(".fpk"):
        return name
    return "%s_%s_all.fpk" % (SELF, version or "latest")


def verify_fpk(path, expect_sha256):
    """先校验 SHA-256，再确认它真的是一个 fpk（tar.gz，含 manifest 与 app.tgz）"""
    if expect_sha256:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as exc:
            return False, "读取下载文件失败：%s" % exc
        got = h.hexdigest().lower()
        if got != expect_sha256:
            return False, "SHA-256 不匹配（期望 %s…，实际 %s…），已丢弃" % (
                expect_sha256[:12], got[:12])
    try:
        with tarfile.open(path, "r:gz") as tf:
            names = tf.getnames()
    except Exception as exc:
        return False, "不是有效的 .fpk 压缩包：%s" % exc
    if "manifest" not in names or "app.tgz" not in names:
        return False, "不是有效的 .fpk（缺少 manifest / app.tgz）"
    return True, ""


def _download_and_verify(info):
    """同步下载 + 校验（调用方已持有 running 标记）。返回 (是否成功, 路径或错误)"""
    url = info.get("direct_url") or ""
    version = info.get("version") or ""
    expect = (info.get("sha256") or "").strip().lower()
    name = os.path.basename(info.get("file_name") or _pkg_name(url, version))
    if not name.lower().endswith(".fpk"):
        name += ".fpk"
    os.makedirs(UPD_DIR, exist_ok=True)
    dst = os.path.join(UPD_DIR, name)
    tmp = dst + ".part"

    UPD_DL["phase"] = "下载中"
    dl_log("开始下载 %s" % url)
    got = 0
    req = urllib.request.Request(url, headers={
        "User-Agent": "fpk-extractor/%s" % cur_version()})
    with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        UPD_DL["total"] = total
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            UPD_DL["progress"] = got
    UPD_DL["progress"] = got
    UPD_DL["total"] = UPD_DL["total"] or got

    if os.path.exists(dst):
        os.unlink(dst)
    os.replace(tmp, dst)
    UPD_DL["file"] = name
    UPD_DL["path"] = dst
    dl_log("下载完成 %s（%s）" % (name, human(got)))

    UPD_DL["phase"] = "校验中"
    ok, err = verify_fpk(dst, expect)
    if not ok:
        try:
            os.unlink(dst)
        except OSError:
            pass
        UPD_DL.update(file="", path="", verified=False)
        dl_log("✗ " + err)
        return False, err
    UPD_DL["verified"] = True
    dl_log("✓ 校验通过" + ("（SHA-256）" if expect else "（未提供 SHA-256，仅做了包结构检查）"))
    return True, dst


def _download_worker(info):
    try:
        _download_and_verify(info)
        if UPD_DL["verified"]:
            UPD_DL["phase"] = "已就绪"
    except Exception as exc:
        UPD_DL["error"] = "下载失败：%s" % exc
        UPD_DL["phase"] = "失败"
        dl_log("✗ %s" % exc)
    finally:
        UPD_DL["running"] = False


def _apply_worker(info):
    """一键更新：下载（如需要）→ 校验 → 调 appcenter-cli 安装。
       安装会停掉当前进程，所以这是整个流程的最后一步。"""
    try:
        with UPD_LOCK:
            path, verified = UPD_DL["path"], UPD_DL["verified"]
        alive = bool(path) and os.path.isfile(path) and (
            (info.get("version") or "") in os.path.basename(path))
        if not (verified and alive):
            ok, res = _download_and_verify(info)
            if not ok:
                UPD_DL.update(error=res, phase="失败")
                return
            path = res
        else:
            # 复用已有文件时再校验一次，防止两次操作之间文件被换掉
            ok, err = verify_fpk(path, (info.get("sha256") or "").strip().lower())
            if not ok:
                UPD_DL.update(error=err, phase="失败", verified=False)
                dl_log("✗ " + err)
                return
            dl_log("复用已下载的安装包 %s" % os.path.basename(path))
            UPD_DL["progress"] = UPD_DL["total"] = os.path.getsize(path)

        UPD_DL["phase"] = "安装中"
        UPD_DL["install_started"] = time.time()
        dl_log("调用 appcenter-cli 安装 %s" % os.path.basename(path))
        ok, res = start_install(path, info.get("version") or "")
        if not ok:
            UPD_DL.update(error=res, phase="失败")
            dl_log("✗ " + res)
            return
        dl_log("安装命令已启动，本应用即将重启…")
    except Exception as exc:
        UPD_DL["error"] = "更新失败：%s" % exc
        UPD_DL["phase"] = "失败"
        dl_log("✗ %s" % exc)
    finally:
        UPD_DL["running"] = False


def _start_update_task(info, kind):
    with UPD_LOCK:
        if UPD_DL["running"]:
            return False, "已有更新任务在进行"
        if kind == "download" and not (info.get("direct_url") or ""):
            return False, "更新管理器没有提供直链，只有网盘链接，请在浏览器里手动下载"
        UPD_DL.update(running=True, phase="准备中", error="", log=[], install_started=0.0)
        # 已经下载并校验过的同一个版本要保留下来，供「安装并重启」直接复用
        reusable = (UPD_DL["verified"] and UPD_DL["path"]
                    and os.path.isfile(UPD_DL["path"])
                    and (info.get("version") or "") in os.path.basename(UPD_DL["path"]))
        if not reusable:
            UPD_DL.update(progress=0, total=0, file="", path="", verified=False)
    fn = _apply_worker if kind == "apply" else _download_worker
    threading.Thread(target=fn, args=(info,), daemon=True).start()
    return True, ""


def find_appcenter_cli():
    """定位飞牛自带的 appcenter-cli（也允许用 APPCENTER_CLI 环境变量指定）"""
    env = (os.environ.get("APPCENTER_CLI") or "").strip()
    if env and os.path.isfile(env):
        return env
    for c in UPD_CLI_PATHS:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("appcenter-cli") or ""


def start_install(path, version):
    """调用 fnOS 自带的 appcenter-cli 安装。必须脱离本进程启动——
       安装过程会先停掉正在运行的旧版本，也就是我们自己。"""
    cli = find_appcenter_cli()
    if not cli:
        return False, ("系统上没有找到 appcenter-cli，无法自动安装。"
                       "请到「应用中心 → 手动安装」选择 %s" % path)
    logf = os.path.join(VAR_DIR, "update-install.log")
    try:
        fh = open(logf, "ab")
        proc = subprocess.Popen(
            [cli, "install-fpk", path],
            stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, cwd=os.path.dirname(path) or UPD_DIR)
    except OSError as exc:
        return False, "启动安装命令失败：%s" % exc

    try:                                              # 记一笔，重启后界面能告诉用户结果
        with open(UPD_PENDING, "w", encoding="utf-8") as fh2:
            json.dump({"version": version, "file": path,
                       "at": int(time.time()), "log": logf}, fh2, ensure_ascii=False)
    except OSError:
        pass

    time.sleep(2.0)                                   # 给 CLI 一点时间暴露"手动安装未开启"这类错误
    rc = proc.poll()
    if rc is not None and rc != 0:
        return False, ("安装命令立刻退出（退出码 %s）：%s" % (rc, tail_log(logf)))
    return True, logf


def tail_log(path, n=1200):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-n:].strip()
    except OSError:
        return ""


def update_status():
    with UPD_LOCK:
        dl = json.loads(json.dumps(UPD_DL))
    # 「安装中」是个瞬时状态：正常情况下安装会让本应用重启，状态自然归零。
    # 如果迟迟没重启成新版本，说明安装没生效，别让它假装永远在装。
    started = dl.get("install_started") or 0.0
    if dl.get("phase") == "安装中" and started and (time.time() - started) > INSTALL_TIMEOUT:
        dl["phase"] = "失败"
        dl["error"] = ("安装命令已执行，但应用没有重启到新版本。"
                       "可到「应用中心 → 手动安装」选择 updates 目录里的安装包重试。")
        dl["timed_out"] = True
    pend = None
    try:
        with open(UPD_PENDING, "r", encoding="utf-8") as fh:
            pend = json.load(fh)
    except (OSError, ValueError):
        pass
    # 重启后如果版本已经追平待更新版本，说明装成功了，清掉标记
    if pend and pend.get("version") and pend["version"] == cur_version():
        try:
            os.unlink(UPD_PENDING)
        except OSError:
            pass
        pend = None
    dl["pending"] = pend
    dl["current_version"] = cur_version()
    dl["cli"] = find_appcenter_cli()
    dl["install_log"] = tail_log(os.path.join(VAR_DIR, "update-install.log"))
    dl["config"] = public_update_cfg()
    return dl


# ------------------------------------------------------------------ HTTP
# /images/ 下现在既有图标也有捐赠二维码，不能一律按 image/png 发
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "fpk-extractor"

    def log_message(self, fmt, *args):                       # 静音访问日志
        pass

    # ---------------------------------------------------------- 响应
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, OSError):
            return {}

    # ---------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        base, path = split_base(u.path)
        if path in ("", "/", "/index.html"):
            return self._send_index(base)
        if path.startswith("/images/"):
            return self._send_icon(path)
        if path == "/api/apps":
            scan_sizes_async()
            return self._json({"apps": scan_apps(), "out": OUT_DIR, "custom": out_is_custom(),
                               "self": SELF,
                               "engine": os.path.isfile(ENGINE), "bash": BASH,
                               "bash_ok": os.path.isfile(BASH), "python": sys.executable})
        if path == "/api/job":
            with JOB_LOCK:
                snap = json.loads(json.dumps(JOB))
            snap["files"] = list_results()
            return self._json(snap)
        if path == "/api/files":
            return self._json({"out": OUT_DIR, "custom": out_is_custom(),
                               "files": list_results()})
        if path == "/api/update":
            q = parse_qs(u.query)
            force = (q.get("force") or ["0"])[0] in ("1", "true", "yes")
            return self._json(check_update(force))
        if path == "/api/update/status":
            return self._json(update_status())
        if path == "/api/download":
            q = parse_qs(u.query)
            fn = unquote((q.get("f") or [""])[0])
            return self._download(fn)
        return self._json({"error": "not found"}, 404)

    # ---------------------------------------------------------- POST
    def do_POST(self):
        u = urlparse(self.path)
        _base, path = split_base(u.path)
        if path == "/api/extract":
            data = self._read_json()
            known = {a["name"] for a in scan_apps()}
            want = data.get("apps") or []
            if want:
                bad = [w for w in want if w not in known]
                if bad:
                    return self._json({"ok": False, "error": "未知应用：%s" % ", ".join(bad)}, 400)
            if not known:
                return self._json({"ok": False, "error": "没有扫描到任何已安装应用"}, 400)
            ok, err = start_job(want)
            return self._json({"ok": ok, "error": err})
        if path == "/api/cancel":
            return self._json({"ok": cancel_job()})
        if path == "/api/setout":
            data = self._read_json()
            ok, res = set_out_dir(data.get("dir") or "")
            if not ok:
                return self._json({"ok": False, "error": res, "out": OUT_DIR,
                                   "custom": out_is_custom()}, 400)
            return self._json({"ok": True, "error": "", "out": OUT_DIR,
                               "custom": out_is_custom()})
        if path == "/api/update/check":
            return self._json(check_update(True))
        if path == "/api/update/download":
            ok, err = _start_update_task(check_update(True), "download")
            return self._json({"ok": ok, "error": err, "status": update_status()})
        if path == "/api/update/apply":
            ok, err = _start_update_task(check_update(True), "apply")
            return self._json({"ok": ok, "error": err, "status": update_status()})
        return self._json({"error": "not found"}, 404)

    # ---------------------------------------------------------- 文件
    def _send_file(self, fp, ctype):
        try:
            with open(fp, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._send(404, "UI 文件缺失：%s" % fp, "text/plain; charset=utf-8")
        self._send(200, data, ctype)

    def _send_index(self, base):
        """首页必须把访问前缀注入进去，否则网关下接口全 404"""
        fp = os.path.join(WWW_DIR, "index.html")
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                html = fh.read()
        except OSError:
            return self._send(404, "UI 文件缺失：%s" % fp, "text/plain; charset=utf-8")
        return self._send(200, html.replace("__BASE__", base),
                          "text/html; charset=utf-8")

    def _send_icon(self, path):
        fn = os.path.basename(path)                      # 只取文件名，防目录穿越
        for root in (os.path.join(WWW_DIR, "images"), ICON_DIR):
            fp = os.path.join(root, fn)
            if os.path.isfile(fp):
                return self._send_file(fp, MIME.get(
                    os.path.splitext(fn)[1].lower(), "application/octet-stream"))
        return self._send(404, "no icon", "text/plain; charset=utf-8")

    def _download(self, fn):
        fn = os.path.basename(fn or "")
        if not fn or not fn.lower().endswith(".fpk"):
            return self._json({"error": "文件名不合法"}, 400)
        fp = os.path.join(OUT_DIR, fn)
        if not os.path.isfile(fp):
            return self._json({"error": "文件不存在"}, 404)
        try:
            with open(fp, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._json({"error": "读取失败"}, 500)
        self._send(200, data, "application/octet-stream", {
            "Content-Disposition": "attachment; filename=\"%s\"" % fn,
        })


if getattr(socket, "AF_UNIX", None) is not None and hasattr(socketserver, "UnixStreamServer"):

    class UnixHTTPServer(ThreadingMixIn, socketserver.UnixStreamServer):
        """统一网关用的 Unix Socket HTTP 服务（飞牛 nginx 反向转发到这里）"""
        daemon_threads = True
        allow_reuse_address = False
        server_name = "fpk-extractor"
        server_port = 0

else:                                                 # Windows 等没有 AF_UNIX 的环境
    UnixHTTPServer = None


def serve_gateway():
    """在 target/app.sock 上监听，供 https 域名（统一网关）访问"""
    if UnixHTTPServer is None:
        sys.stderr.write("当前环境不支持 Unix Socket，跳过统一网关监听（飞牛上会正常启用）\n")
        sys.stderr.flush()
        return
    try:
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
    except OSError:
        pass
    try:
        srv = UnixHTTPServer(SOCK_PATH, Handler)
    except OSError as exc:
        sys.stderr.write("统一网关 Socket 无法监听 %s：%s\n" % (SOCK_PATH, exc))
        sys.stderr.flush()
        return
    try:
        os.chmod(SOCK_PATH, 0o666)                       # nginx 转发进程需要能连上
    except OSError:
        pass
    sys.stderr.write("统一网关 Socket 就绪 %s\n" % SOCK_PATH)
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except Exception:
        pass


def _on_term(_signum, _frame):
    """收到 SIGTERM 时走正常退出流程，好把 socket 文件清掉"""
    raise SystemExit(0)


def main():
    if not os.path.isdir(WWW_DIR):
        sys.stderr.write("缺少目录：%s\n" % WWW_DIR)
    if not os.path.isfile(ENGINE):
        sys.stderr.write("缺少打包引擎：%s\n" % ENGINE)

    signal.signal(signal.SIGTERM, _on_term)

    threading.Thread(target=serve_gateway, daemon=True).start()

    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        sys.stderr.write("端口 %d 无法监听：%s\n" % (PORT, exc))
        sys.exit(1)
    sys.stderr.write("应用提取器已启动 http://%s:%d  输出目录 %s\n" % (HOST, PORT, OUT_DIR))
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        srv.server_close()
        try:
            if os.path.exists(SOCK_PATH):
                os.unlink(SOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
