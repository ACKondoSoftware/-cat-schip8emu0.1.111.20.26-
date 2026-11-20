#!/usr/bin/env python3
"""
cat's chip 8 emu 0.1x — A.C Holdings / Team Flames
Single-file CHIP-8 emulator, tkinter, mGBA-style GUI.
Built-in ROM: "CATCATCH" — original paddle game, assembled at startup (public domain).

Keys (CHIP-8 hex pad -> keyboard):
  1 2 3 C        1 2 3 4
  4 5 6 D   ->   Q W E R
  7 8 9 E        A S D F
  A 0 B F        Z X C V
  Arrows Left/Right also map to 4/6. CATCATCH: Q/E or arrows move the paddle.
"""
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import winsound
except ImportError:
    winsound = None

APP_NAME = "cat's chip 8 emu 0.1x"

# ── palette ────────────────────────────────────────────────────────────────
BG = "#000000"
PANEL = "#05070f"
BLUE = "#3fa9ff"
BLUE_DIM = "#1a4f80"
BTN = "#000000"
BTN_ACTIVE = "#0b1a2e"
PIX_ON = "#3fa9ff"
PIX_OFF = "#00040a"
MONO = ("Consolas", 10) if sys.platform == "win32" else ("Menlo", 10) if sys.platform == "darwin" else ("DejaVu Sans Mono", 10)
UI = ("Segoe UI", 9) if sys.platform == "win32" else ("Helvetica", 10)

W, H = 64, 32
WIN_W, WIN_H = 600, 400
FONT_ADDR = 0x50
FONT = bytes([
    0xF0, 0x90, 0x90, 0x90, 0xF0, 0x20, 0x60, 0x20, 0x20, 0x70,
    0xF0, 0x10, 0xF0, 0x80, 0xF0, 0xF0, 0x10, 0xF0, 0x10, 0xF0,
    0x90, 0x90, 0xF0, 0x10, 0x10, 0xF0, 0x80, 0xF0, 0x10, 0xF0,
    0xF0, 0x80, 0xF0, 0x90, 0xF0, 0xF0, 0x10, 0x20, 0x40, 0x40,
    0xF0, 0x90, 0xF0, 0x90, 0xF0, 0xF0, 0x90, 0xF0, 0x10, 0xF0,
    0xF0, 0x90, 0xF0, 0x90, 0x90, 0xE0, 0x90, 0xE0, 0x90, 0xE0,
    0xF0, 0x80, 0x80, 0x80, 0xF0, 0xE0, 0x90, 0x90, 0x90, 0xE0,
    0xF0, 0x80, 0xF0, 0x80, 0xF0, 0xF0, 0x80, 0xF0, 0x80, 0x80,
])

KEYMAP = {
    "1": 0x1, "2": 0x2, "3": 0x3, "4": 0xC,
    "q": 0x4, "w": 0x5, "e": 0x6, "r": 0xD,
    "a": 0x7, "s": 0x8, "d": 0x9, "f": 0xE,
    "z": 0xA, "x": 0x0, "c": 0xB, "v": 0xF,
    "left": 0x4, "right": 0x6, "up": 0x2, "down": 0x8,
}

# ── mini assembler (Cowgod syntax) ─────────────────────────────────────────
def _reg(t):
    t = t.strip().upper()
    if len(t) == 2 and t[0] == "V":
        return int(t[1], 16)
    return None


def assemble(src, origin=0x200):
    lines = []
    for raw in src.splitlines():
        line = raw.split(";")[0].strip()
        if line:
            lines.append(line)
    labels, pc = {}, origin
    for line in lines:                                   # pass 1: addresses
        if line.endswith(":"):
            labels[line[:-1].strip().lower()] = pc
            continue
        op, _, rest = line.partition(" ")
        pc += len(rest.split(",")) if op.upper() == "DB" else 2
    out = bytearray()

    def num(t):
        t = t.strip()
        if t.lower() in labels:
            return labels[t.lower()]
        return int(t, 0)

    for line in lines:                                   # pass 2: encode
        if line.endswith(":"):
            continue
        op, _, rest = line.partition(" ")
        op = op.upper()
        a = [x.strip() for x in rest.split(",")] if rest.strip() else []
        A = [x.upper() for x in a]
        if op == "DB":
            out += bytes(num(x) & 0xFF for x in a)
            continue
        x = _reg(a[0]) if a else None
        y = _reg(a[1]) if len(a) > 1 else None
        if op == "CLS": w = 0x00E0
        elif op == "RET": w = 0x00EE
        elif op == "JP" and A[0] == "V0": w = 0xB000 | num(a[1])
        elif op == "JP": w = 0x1000 | num(a[0])
        elif op == "CALL": w = 0x2000 | num(a[0])
        elif op in ("SE", "SNE"):
            if y is not None:
                w = (0x5000 if op == "SE" else 0x9000) | x << 8 | y << 4
            else:
                w = (0x3000 if op == "SE" else 0x4000) | x << 8 | (num(a[1]) & 0xFF)
        elif op in ("OR", "AND", "XOR", "SUB", "SUBN", "SHR", "SHL"):
            n = {"OR": 1, "AND": 2, "XOR": 3, "SUB": 5, "SHR": 6, "SUBN": 7, "SHL": 0xE}[op]
            w = 0x8000 | x << 8 | ((y or 0) << 4) | n
        elif op == "ADD":
            if A[0] == "I": w = 0xF01E | _reg(a[1]) << 8
            elif y is not None: w = 0x8004 | x << 8 | y << 4
            else: w = 0x7000 | x << 8 | (num(a[1]) & 0xFF)
        elif op == "RND": w = 0xC000 | x << 8 | (num(a[1]) & 0xFF)
        elif op == "DRW": w = 0xD000 | x << 8 | y << 4 | (num(a[2]) & 0xF)
        elif op == "SKP": w = 0xE09E | x << 8
        elif op == "SKNP": w = 0xE0A1 | x << 8
        elif op == "LD":
            d, s = A
            if d == "I": w = 0xA000 | num(a[1])
            elif d == "DT": w = 0xF015 | _reg(s) << 8
            elif d == "ST": w = 0xF018 | _reg(s) << 8
            elif d == "F": w = 0xF029 | _reg(s) << 8
            elif d == "B": w = 0xF033 | _reg(s) << 8
            elif d == "[I]": w = 0xF055 | _reg(s) << 8
            elif s == "DT": w = 0xF007 | x << 8
            elif s == "K": w = 0xF00A | x << 8
            elif s == "[I]": w = 0xF065 | x << 8
            elif y is not None: w = 0x8000 | x << 8 | y << 4
            else: w = 0x6000 | x << 8 | (num(a[1]) & 0xFF)
        else:
            raise SyntaxError(f"bad op: {line}")
        out += bytes((w >> 8, w & 0xFF))
    return bytes(out)


# CATCATCH — original game by Team Flames, public domain.
# VA/VB paddle x/y, VC/VD ball x/y, VE/V9 ball dx/dy, V6 score, V0-V4 scratch for BCD draw.
CATCATCH_ASM = """
start:
  CLS
  LD VA, 28
  LD VB, 30
  LD VC, 32
  LD VD, 4
  LD VE, 1
  LD V9, 1
  LD V6, 0
  LD I, paddle
  DRW VA, VB, 1
  LD I, ball
  DRW VC, VD, 1
  CALL score
loop:
  LD V7, 2          ; 30 Hz game tick
  LD DT, V7
wait:
  LD V7, DT
  SE V7, 0
  JP wait
  LD I, paddle      ; erase paddle
  DRW VA, VB, 1
  LD V7, 4
  SKNP V7
  ADD VA, 0xFE      ; left 2px
  LD V7, 6
  SKNP V7
  ADD VA, 2         ; right 2px
  LD V8, 56         ; clamp 0..56
  SUB V8, VA
  SE VF, 0
  JP padok
  LD V8, 0x80
  AND V8, VA
  LD VA, 56
  SE V8, 0
  LD VA, 0
padok:
  LD I, paddle
  DRW VA, VB, 1
  LD I, ball        ; erase ball
  DRW VC, VD, 1
  ADD VC, VE
  ADD VD, V9
  SNE VC, 0
  LD VE, 1
  SNE VC, 63
  LD VE, 0xFF
  SNE VD, 0
  LD V9, 1
  SE VD, 29         ; paddle row?
  JP nopad
  LD V8, VC
  SUB V8, VA        ; bx - px >= 0 ?
  SE VF, 1
  JP nopad
  LD V7, 7
  SUB V7, V8        ; 7 >= bx - px ?
  SE VF, 1
  JP nopad
  LD V9, 0xFF       ; bounce + score
  CALL score
  ADD V6, 1
  CALL score
  LD V7, 3
  LD ST, V7
nopad:
  SE VD, 31         ; floor = miss
  JP drawb
  CALL score
  LD V6, 0
  CALL score
  RND VC, 0x1F
  ADD VC, 16
  LD VD, 2
  LD V9, 1
  LD V7, 12
  LD ST, V7
drawb:
  LD I, ball
  DRW VC, VD, 1
  JP loop
score:              ; XOR-draw two-digit score at (1,1)
  LD I, bcd
  LD B, V6
  LD V2, [I]
  LD V3, 1
  LD V4, 1
  LD F, V1
  DRW V3, V4, 5
  ADD V3, 5
  LD F, V2
  DRW V3, V4, 5
  RET
paddle:
  DB 0xFF
ball:
  DB 0x80
bcd:
  DB 0, 0, 0
"""


# ── core ───────────────────────────────────────────────────────────────────
class Chip8:
    def __init__(self):
        self.rom = b""
        self.reset()

    def reset(self):
        self.mem = bytearray(4096)
        self.mem[FONT_ADDR:FONT_ADDR + len(FONT)] = FONT
        self.mem[0x200:0x200 + len(self.rom)] = self.rom
        self.V = [0] * 16
        self.I = 0
        self.pc = 0x200
        self.stack = []
        self.dt = self.st = 0
        self.gfx = bytearray(W * H)
        self.keys = [False] * 16
        self.wait_reg = None
        self.dirty = True
        self.cycles = 0

    def load(self, data):
        if len(data) > 4096 - 0x200:
            raise ValueError(f"ROM too large ({len(data)} bytes, max 3584)")
        self.rom = bytes(data)
        self.reset()

    def key(self, k, down):
        self.keys[k] = down
        if not down and self.wait_reg is not None:   # Fx0A completes on release
            self.V[self.wait_reg] = k
            self.wait_reg = None

    def timers(self):
        if self.dt: self.dt -= 1
        if self.st: self.st -= 1

    def step(self):
        if self.wait_reg is not None:
            return
        m, V = self.mem, self.V
        op = m[self.pc] << 8 | m[self.pc + 1]
        self.pc = (self.pc + 2) & 0xFFF
        self.cycles += 1
        x, y = op >> 8 & 0xF, op >> 4 & 0xF
        n, kk, nnn = op & 0xF, op & 0xFF, op & 0xFFF
        h = op >> 12
        if op == 0x00E0:
            self.gfx[:] = bytes(W * H); self.dirty = True
        elif op == 0x00EE:
            self.pc = self.stack.pop()
        elif h == 0x0:
            pass                                    # SYS ignored
        elif h == 0x1:
            self.pc = nnn
        elif h == 0x2:
            if len(self.stack) >= 16: raise RuntimeError("stack overflow")
            self.stack.append(self.pc); self.pc = nnn
        elif h == 0x3:
            if V[x] == kk: self.pc += 2
        elif h == 0x4:
            if V[x] != kk: self.pc += 2
        elif h == 0x5:
            if V[x] == V[y]: self.pc += 2
        elif h == 0x6:
            V[x] = kk
        elif h == 0x7:
            V[x] = (V[x] + kk) & 0xFF
        elif h == 0x8:
            vx, vy = V[x], V[y]
            if n == 0x0: V[x] = vy
            elif n == 0x1: V[x] = vx | vy
            elif n == 0x2: V[x] = vx & vy
            elif n == 0x3: V[x] = vx ^ vy
            elif n == 0x4: r = vx + vy; V[x] = r & 0xFF; V[0xF] = int(r > 0xFF)
            elif n == 0x5: V[x] = (vx - vy) & 0xFF; V[0xF] = int(vx >= vy)
            elif n == 0x6: V[x] = vx >> 1; V[0xF] = vx & 1
            elif n == 0x7: V[x] = (vy - vx) & 0xFF; V[0xF] = int(vy >= vx)
            elif n == 0xE: V[x] = (vx << 1) & 0xFF; V[0xF] = vx >> 7
            else: self._bad(op)
        elif h == 0x9:
            if V[x] != V[y]: self.pc += 2
        elif h == 0xA:
            self.I = nnn
        elif h == 0xB:
            self.pc = (nnn + V[0]) & 0xFFF
        elif h == 0xC:
            V[x] = random.randint(0, 255) & kk
        elif h == 0xD:
            ox, oy = V[x] % W, V[y] % H
            V[0xF] = 0
            g = self.gfx
            for row in range(n):
                py = oy + row
                if py >= H: break
                bits = m[(self.I + row) & 0xFFF]
                for col in range(8):
                    px = ox + col
                    if px >= W: break
                    if bits & (0x80 >> col):
                        i = py * W + px
                        if g[i]: V[0xF] = 1
                        g[i] ^= 1
            self.dirty = True
        elif h == 0xE:
            if kk == 0x9E:
                if self.keys[V[x] & 0xF]: self.pc += 2
            elif kk == 0xA1:
                if not self.keys[V[x] & 0xF]: self.pc += 2
            else: self._bad(op)
        elif h == 0xF:
            if kk == 0x07: V[x] = self.dt
            elif kk == 0x0A: self.wait_reg = x
            elif kk == 0x15: self.dt = V[x]
            elif kk == 0x18: self.st = V[x]
            elif kk == 0x1E: self.I = (self.I + V[x]) & 0xFFFF
            elif kk == 0x29: self.I = FONT_ADDR + (V[x] & 0xF) * 5
            elif kk == 0x33:
                v = V[x]; i = self.I
                m[i], m[i + 1], m[i + 2] = v // 100, v // 10 % 10, v % 10
            elif kk == 0x55: m[self.I:self.I + x + 1] = bytes(V[:x + 1])
            elif kk == 0x65: V[:x + 1] = list(m[self.I:self.I + x + 1])
            else: self._bad(op)

    def _bad(self, op):
        raise RuntimeError(f"unknown opcode {op:04X} at {(self.pc - 2) & 0xFFF:03X}")


# ── GUI ────────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        self.cpu = Chip8()
        self.scale = 9
        self.ipf = 10
        self.paused = False
        self.muted = tk.BooleanVar(value=False)
        self.ipf_var = tk.IntVar(value=self.ipf)
        self.scale_var = tk.IntVar(value=self.scale)
        self.rom_name = "—"
        self.regwin = None
        self.prev_st = 0
        self.fps = 0.0
        self._frames = 0
        self._fps_t = time.perf_counter()

        root.title(APP_NAME)
        root.configure(bg=BG)
        root.resizable(False, False)
        self._build_menu()
        self._build_toolbar()
        self.status = tk.Label(root, anchor="w", bg=PANEL, fg=BLUE, font=MONO, padx=6)
        self.status.pack(fill="x", side="bottom")
        stage = tk.Frame(root, bg=BG)
        stage.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(stage, bg=PIX_OFF, highlightthickness=1,
                                highlightbackground=BLUE_DIM, bd=0)
        self.canvas.place(relx=0.5, rely=0.5, anchor="center")
        self._build_pixels()
        root.update_idletasks()
        sx = (root.winfo_screenwidth() - WIN_W) // 2
        sy = (root.winfo_screenheight() - WIN_H) // 2
        root.geometry(f"{WIN_W}x{WIN_H}+{sx}+{sy}")

        root.bind("<KeyPress>", self._kdown)
        root.bind("<KeyRelease>", self._kup)
        root.bind("<Control-o>", lambda e: self.open_rom())
        root.bind("<Control-p>", lambda e: self.toggle_pause())
        root.bind("<Control-r>", lambda e: self.reset())
        root.bind("<Control-n>", lambda e: self.frame_advance())
        root.bind("<F1>", lambda e: self.load_builtin())
        root.protocol("WM_DELETE_WINDOW", root.destroy)

        self.load_builtin()
        self._next = time.perf_counter()
        self.root.after(1, self._tick)

    # widgets
    def _menu(self, parent):
        return tk.Menu(parent, tearoff=0, bg=BG, fg=BLUE, activebackground=BTN_ACTIVE,
                       activeforeground=BLUE, selectcolor=BLUE, font=UI)

    def _build_menu(self):
        mb = self._menu(self.root)
        f = self._menu(mb)
        f.add_command(label="Load ROM...", accelerator="Ctrl+O", command=self.open_rom)
        f.add_command(label="Load built-in: CATCATCH", accelerator="F1", command=self.load_builtin)
        f.add_separator()
        f.add_command(label="Export built-in ROM...", command=self.export_builtin)
        f.add_separator()
        f.add_command(label="Exit", command=self.root.destroy)
        mb.add_cascade(label="File", menu=f)

        e = self._menu(mb)
        e.add_command(label="Pause / Resume", accelerator="Ctrl+P", command=self.toggle_pause)
        e.add_command(label="Reset", accelerator="Ctrl+R", command=self.reset)
        e.add_command(label="Frame advance", accelerator="Ctrl+N", command=self.frame_advance)
        e.add_separator()
        sp = self._menu(e)
        for v, lbl in ((5, "Slow (300 Hz)"), (10, "Normal (600 Hz)"), (15, "Fast (900 Hz)"),
                       (20, "1200 Hz"), (50, "Turbo (3000 Hz)")):
            sp.add_radiobutton(label=lbl, variable=self.ipf_var, value=v, command=self._set_ipf)
        e.add_cascade(label="Speed", menu=sp)
        mb.add_cascade(label="Emulation", menu=e)

        av = self._menu(mb)
        sc = self._menu(av)
        for s in (5, 6, 7, 8, 9):                       # 9x = 576x288, max that fits 600x400
            sc.add_radiobutton(label=f"{s}x  ({W * s}x{H * s})", variable=self.scale_var,
                               value=s, command=self._set_scale)
        av.add_cascade(label="Frame size", menu=sc)
        av.add_checkbutton(label="Mute", variable=self.muted)
        mb.add_cascade(label="Audio/Video", menu=av)

        t = self._menu(mb)
        t.add_command(label="View registers...", command=self.show_regs)
        mb.add_cascade(label="Tools", menu=t)

        h = self._menu(mb)
        h.add_command(label="Controls", command=self.show_controls)
        h.add_command(label="About", command=self.show_about)
        mb.add_cascade(label="Help", menu=h)
        self.root.config(menu=mb)

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=6, pady=4)
        for txt, cmd in (("Open", self.open_rom), ("CATCATCH", self.load_builtin),
                         ("Pause", self.toggle_pause), ("Reset", self.reset),
                         ("Step", self.frame_advance), ("Regs", self.show_regs)):
            b = tk.Button(bar, text=txt, command=cmd, bg=BTN, fg=BLUE, activebackground=BTN_ACTIVE,
                          activeforeground=BLUE, relief="flat", bd=0, padx=10, pady=3, font=UI,
                          highlightthickness=1, highlightbackground=BLUE_DIM, takefocus=0)
            b.pack(side="left", padx=(0, 4))
            if txt == "Pause":
                self.pause_btn = b

    def _build_pixels(self):
        s = self.scale
        self.canvas.config(width=W * s, height=H * s)
        self.canvas.delete("all")
        self.rects = [self.canvas.create_rectangle(x * s, y * s, x * s + s, y * s + s,
                                                   fill=PIX_OFF, width=0)
                      for y in range(H) for x in range(W)]
        self.shown = bytearray(W * H)
        self.cpu.dirty = True
        self._render(force=True)

    # actions
    def load_builtin(self):
        self._load(assemble(CATCATCH_ASM), "CATCATCH (built-in)")

    def open_rom(self):
        p = filedialog.askopenfilename(title="Load ROM", filetypes=[
            ("CHIP-8 ROMs", "*.ch8 *.c8 *.rom *.sc8"), ("All files", "*.*")])
        if p:
            with open(p, "rb") as fh:
                self._load(fh.read(), os.path.basename(p))

    def export_builtin(self):
        p = filedialog.asksaveasfilename(defaultextension=".ch8", initialfile="catcatch.ch8",
                                         filetypes=[("CHIP-8 ROM", "*.ch8")])
        if p:
            with open(p, "wb") as fh:
                fh.write(assemble(CATCATCH_ASM))

    def _load(self, data, name):
        try:
            self.cpu.load(data)
        except ValueError as ex:
            messagebox.showerror(APP_NAME, str(ex)); return
        self.rom_name = name
        self.paused = False
        self.pause_btn.config(text="Pause")
        self.root.title(f"{APP_NAME} - {name}")

    def reset(self):
        self.cpu.reset()
        self.paused = False
        self.pause_btn.config(text="Pause")

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.config(text="Resume" if self.paused else "Pause")

    def frame_advance(self):
        if not self.paused:
            self.toggle_pause()
        self._run_frame()
        self._render()

    def _set_ipf(self):
        self.ipf = self.ipf_var.get()

    def _set_scale(self):
        self.scale = self.scale_var.get()
        self._build_pixels()

    # input
    def _kdown(self, e):
        k = KEYMAP.get(e.keysym.lower())
        if k is not None:
            self.cpu.key(k, True)

    def _kup(self, e):
        k = KEYMAP.get(e.keysym.lower())
        if k is not None:
            self.cpu.key(k, False)

    # main loop — fixed 60 Hz, perf_counter-paced
    def _run_frame(self):
        cpu = self.cpu
        try:
            for _ in range(self.ipf):
                cpu.step()
        except Exception as ex:
            self.paused = True
            self.pause_btn.config(text="Resume")
            self.status.config(text=f"HALT: {ex}")
            return
        cpu.timers()
        if cpu.st and not self.prev_st:
            self._beep()
        self.prev_st = cpu.st

    def _tick(self):
        if not self.paused:
            self._run_frame()
            self._render()
        self._frames += 1
        now = time.perf_counter()
        if now - self._fps_t >= 0.5:
            self.fps = self._frames / (now - self._fps_t)
            self._frames, self._fps_t = 0, now
            if not self.status.cget("text").startswith("HALT"):
                state = "Paused" if self.paused else ("Wait key" if self.cpu.wait_reg is not None else "Running")
                self.status.config(text=f" {self.rom_name}  |  {self.fps:5.1f} FPS  |  "
                                        f"{self.ipf * 60} Hz  |  {state}")
            elif not self.paused:
                self.status.config(text="")
        if self.regwin is not None:
            self._update_regs()
        self._next += 1 / 60
        if now - self._next > 0.25:
            self._next = now
        self.root.after(max(1, int((self._next - time.perf_counter()) * 1000)), self._tick)

    def _render(self, force=False):
        cpu = self.cpu
        if not (cpu.dirty or force):
            return
        cpu.dirty = False
        g, shown, rects, cfg = cpu.gfx, self.shown, self.rects, self.canvas.itemconfigure
        if g == shown:
            return
        for i in range(W * H):
            v = g[i]
            if v != shown[i]:
                shown[i] = v
                cfg(rects[i], fill=PIX_ON if v else PIX_OFF)

    def _beep(self):
        if self.muted.get():
            return
        if winsound:
            threading.Thread(target=winsound.Beep, args=(880, 70), daemon=True).start()
        else:
            self.root.bell()

    # tool windows
    def show_regs(self):
        if self.regwin is not None:
            self.regwin.lift(); return
        w = tk.Toplevel(self.root, bg=BG)
        w.title("Registers")
        w.resizable(False, False)
        self.reglbl = tk.Label(w, bg=BG, fg=BLUE, font=MONO, justify="left", padx=10, pady=8)
        self.reglbl.pack()

        def close():
            self.regwin = None
            w.destroy()
        w.protocol("WM_DELETE_WINDOW", close)
        self.regwin = w
        self._update_regs()

    def _update_regs(self):
        c = self.cpu
        op = c.mem[c.pc] << 8 | c.mem[(c.pc + 1) & 0xFFF]
        rows = [f"PC  {c.pc:03X}   OP  {op:04X}", f"I   {c.I:03X}   SP  {len(c.stack):X}",
                f"DT  {c.dt:02X}    ST  {c.st:02X}", ""]
        rows += [f"V{i:X} {c.V[i]:02X}   V{i + 8:X} {c.V[i + 8]:02X}" for i in range(8)]
        rows += ["", "stack: " + " ".join(f"{a:03X}" for a in c.stack[-6:]), f"cycles: {c.cycles}"]
        self.reglbl.config(text="\n".join(rows))

    def show_controls(self):
        messagebox.showinfo("Controls",
                            "CHIP-8 pad -> keyboard\n\n"
                            "1 2 3 C   ->   1 2 3 4\n4 5 6 D   ->   Q W E R\n"
                            "7 8 9 E   ->   A S D F\nA 0 B F   ->   Z X C V\n\n"
                            "Arrows: Left=4 Right=6 Up=2 Down=8\n\n"
                            "CATCATCH: Q/E or Left/Right moves the paddle.\n"
                            "Ctrl+O open  Ctrl+P pause  Ctrl+R reset  Ctrl+N frame advance  F1 built-in")

    def show_about(self):
        messagebox.showinfo("About", f"{APP_NAME}\nA.C Holdings / Team Flames\n\n"
                                     "Built-in ROM: CATCATCH (original, public domain)")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--export":
        with open(sys.argv[2], "wb") as fh:
            fh.write(assemble(CATCATCH_ASM))
        return
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        with open(sys.argv[1], "rb") as fh:
            app._load(fh.read(), os.path.basename(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
