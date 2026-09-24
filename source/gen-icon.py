#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「应用提取器」的图标（纯标准库，无第三方依赖）。
输出 RGBA PNG：ICON.PNG(64) / ICON_256.PNG(256)

用法: python gen-icon.py <输出目录>
"""
import os
import struct
import sys
import zlib

SS = 4  # 超采样倍数（抗锯齿）


# ---------------------------------------------------------------- PNG 输出
def write_png(path, w, h, rows):
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0
        for px in rows[y]:
            raw.extend(px)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------- 几何判定
def inside_rrect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= r * r


def inside_poly(x, y, pts):
    n = len(pts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------- 绘制
def render(size):
    # 归一化坐标 0..1 下的形状定义
    ARROW = [
        (0.430, 0.720), (0.430, 0.430), (0.318, 0.430),
        (0.500, 0.175), (0.682, 0.430), (0.570, 0.430),
        (0.570, 0.720),
    ]
    BOX = (0.215, 0.640, 0.785, 0.845)      # 外框
    BOX_R = 0.060
    BOX_W = 0.070                            # 描边宽度
    BG = (0.055, 0.055, 0.945, 0.945)
    BG_R = 0.215
    C_TOP = (0.235, 0.478, 0.949)            # 渐变上色
    C_BOT = (0.106, 0.706, 0.855)            # 渐变下色
    WHITE = (1.0, 1.0, 1.0)

    rows = []
    inv = 1.0 / size
    offs = [(i + 0.5) / SS for i in range(SS)]

    for py in range(size):
        row = []
        for px in range(size):
            bg_cov = 0
            white_cov = 0
            samples = SS * SS
            for oy in offs:
                y = (py + oy) * inv
                for ox in offs:
                    x = (px + ox) * inv
                    if inside_rrect(x, y, BG[0], BG[1], BG[2], BG[3], BG_R):
                        bg_cov += 1
                        in_white = inside_poly(x, y, ARROW)
                        if not in_white:
                            if inside_rrect(x, y, BOX[0], BOX[1], BOX[2], BOX[3], BOX_R):
                                # 外框内、内框外 => 描边
                                in_white = not inside_rrect(
                                    x, y,
                                    BOX[0] + BOX_W, BOX[1] + BOX_W,
                                    BOX[2] - BOX_W, BOX[3] - BOX_W,
                                    max(BOX_R - BOX_W, 0.001),
                                )
                        if in_white:
                            white_cov += 1
            a_bg = bg_cov / samples
            if a_bg <= 0:
                row.append((0, 0, 0, 0))
                continue
            t = py / max(size - 1, 1)
            base = (
                lerp(C_TOP[0], C_BOT[0], t),
                lerp(C_TOP[1], C_BOT[1], t),
                lerp(C_TOP[2], C_BOT[2], t),
            )
            w = white_cov / samples
            rgb = (
                int(round(lerp(base[0], WHITE[0], w) * 255)),
                int(round(lerp(base[1], WHITE[1], w) * 255)),
                int(round(lerp(base[2], WHITE[2], w) * 255)),
            )
            row.append((rgb[0], rgb[1], rgb[2], int(round(a_bg * 255))))
        rows.append(row)
    return rows


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    targets = [(64, "ICON.PNG"), (256, "ICON_256.PNG")]
    for size, name in targets:
        rows = render(size)
        path = os.path.join(out, name)
        write_png(path, size, size, rows)
        print("generated %s (%dx%d, %d bytes)" % (path, size, size, os.path.getsize(path)))


if __name__ == "__main__":
    main()
