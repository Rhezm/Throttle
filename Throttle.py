"""
Holds the right trigger of a virtual Xbox 360 controller at a chosen pressure
(99% by default) while a configurable key ("<" on ISO keyboards) is held, or
toggles it on and off with that key. Hotkeys and the mouse wheel can change
the pressure on the fly.

Dependencies: pip install vgamepad keyboard mouse customtkinter pystray pillow

Build (icon.ico next to Throttle.py):
    python -m PyInstaller --onefile --noconsole --uac-admin --icon icon.ico --add-data "icon.ico;." --hidden-import pystray._win32 --collect-all vgamepad --collect-all customtkinter --exclude-module numpy Throttle.py
"""

import ctypes
import json
import os
import queue
import sys
import threading

import customtkinter as ctk
import keyboard
import mouse
import pystray
from PIL import Image

APP_NAME = "Throttle"
WIDTH = 380
CANCEL_KEY = "esc"
QUIT_HOTKEY = "ctrl+shift+q"
RETRY_MS = 2000
CONFIG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME, "config.json")

DEFAULT_CONFIG = {
    "key": {"scan_code": 86, "name": "<"},
    "mode": "hold",
    "percent": 99,
    "hotkeys": [],
    "wheel": {"enabled": False, "step": 5, "only_while_active": True},
}

BACKGROUND = "#0F0F11"
CARD = "#18181B"
BORDER = "#27272A"
HOVER = "#3F3F46"
TEXT = "#ECEDEE"
TEXT_MUTED = "#A1A1AA"
TEXT_FAINT = "#52525B"
BLUE = "#006FEE"
BLUE_HOVER = "#005BC4"
BLUE_DARK = "#0A2540"
BLUE_LIGHT = "#45A0FF"
RED = "#F31260"

STATES = {
    "idle": ("Idle", "#27272A", "#A1A1AA"),
    "active": ("Accelerating", "#0B2E1A", "#17C964"),
    "binding": ("Waiting", BLUE_DARK, BLUE_LIGHT),
    "error": ("Error", "#3A0D14", RED),
}

GLYPH_CLOSE, GLYPH_MINIMIZE, GLYPH_PIN = "\uE8BB", "\uE921", "\uE718"
GLYPH_BACK, GLYPH_DELETE = "\uE72B", "\uE74D"
GLYPH_MINUS, GLYPH_PLUS = "\uE738", "\uE710"

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


ICON_PATH = resource("icon.ico")


#Pressure and hotkey logic

def clamp(percent):
    return max(0, min(100, percent))


def percent_to_trigger(percent):
    return round(percent * 255 / 100)


def apply_hotkey(hotkey, percent):
    action = hotkey["action"]
    if action == "set":
        return hotkey["value"]
    if action == "toggle":
        return hotkey["b"] if percent == hotkey["a"] else hotkey["a"]
    return clamp(percent + hotkey["delta"])


def describe_hotkey(hotkey):
    action = hotkey["action"]
    if action == "set":
        return f"Set to {hotkey['value']}%"
    if action == "toggle":
        return f"Toggle {hotkey['a']}% ↔ {hotkey['b']}%"
    delta = hotkey["delta"]
    return f"{'Increase' if delta > 0 else 'Decrease'} by {abs(delta)}%"


def key_label(name):
    return name.upper() if len(name) == 1 else name.title()


def create_gamepad():
    import vgamepad
    try:
        return vgamepad.VX360Gamepad()
    except Exception:
        from vgamepad.win import virtual_gamepad
        virtual_gamepad.VBUS = virtual_gamepad.VBus()
        return vgamepad.VX360Gamepad()
z    
#Config

def load_config():
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        if "key" in saved:
            config["key"] = {"scan_code": int(saved["key"]["scan_code"]), "name": str(saved["key"]["name"])}
        if saved.get("mode") in ("hold", "toggle"):
            config["mode"] = saved["mode"]
        if "percent" in saved:
            config["percent"] = clamp(int(saved["percent"]))
        if "wheel" in saved:
            wheel = saved["wheel"]
            config["wheel"] = {
                "enabled": bool(wheel["enabled"]),
                "step": max(1, clamp(int(wheel["step"]))),
                "only_while_active": bool(wheel["only_while_active"]),
            }
        for hotkey in saved.get("hotkeys", []):
            describe_hotkey(hotkey)
            apply_hotkey(hotkey, 0)
            config["hotkeys"].append(hotkey)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return config


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


class ThrottleApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.configure(fg_color=BORDER)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.after(250, lambda: self.iconbitmap(ICON_PATH))

        self.config_data = load_config()
        self.pad = None
        self.pad_lock = threading.Lock()
        self.pressed = False
        self.key_down = False
        self.hooks = []
        self.hotkeys_down = set()
        self.capture_hook = None
        self.capture_target = None
        self.form_key = None
        self.events = queue.SimpleQueue()
        self.save_job = None
        self.pinned = False
        self.drag_offset = (0, 0)
        self.retry_job = None

        self._build_ui()
        self._create_tray_icon()
        self.show_page("main", center=True)
        self.after(10, self._setup_window)
        self._update()

        keyboard.add_hotkey(QUIT_HOTKEY, lambda: self.events.put(("quit",)))
        mouse.hook(self._on_mouse_event)
        self.connect_pad()

    #Virtual controller

    def connect_pad(self):
        if self.retry_job:
            self.after_cancel(self.retry_job)
            self.retry_job = None
        try:
            pad = create_gamepad()
        except Exception as e:
            self._show_error(
                "Couldn't connect to the ViGEmBus driver.\n"
                f"Retrying every {RETRY_MS // 1000} s, or press Retry.\n({e})"
            )
            self.retry_job = self.after(RETRY_MS, self.connect_pad)
            return
        with self.pad_lock:
            self.pad = pad
        self._hide_error()
        self._bind_keys()

    def _on_pad_lost(self):
        if not self.pad:
            return
        self._unbind_keys()
        if self.capture_hook:
            keyboard.unhook(self.capture_hook)
            self.capture_hook = None
            self.capture_target = None
            self.key_button.configure(text="Change key", fg_color=BORDER, text_color=TEXT)
            self.form_key_button.configure(text="Choose key", fg_color=BORDER, text_color=TEXT)
        with self.pad_lock:
            self.pad = None
        self.pressed = False
        self.key_down = False
        self.show_page("main")
        self.connect_pad()

    #Window

    def _fit_height(self, center=False):
        self.update_idletasks()
        scale = self._get_window_scaling()
        height = round(self.container.winfo_reqheight() / scale) + 2
        if center:
            x = (self.winfo_screenwidth() - round(WIDTH * scale)) // 2
            y = (self.winfo_screenheight() - round(height * scale)) // 2
            self.geometry(f"{WIDTH}x{height}+{x}+{y}")
        else:
            self.geometry(f"{WIDTH}x{height}")

    def _setup_window(self):
        hwnd = user32.GetParent(self.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)

        corners = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corners), ctypes.sizeof(corners)
        )

        self.withdraw()
        self.after(10, self.deiconify)

    def show_page(self, page, center=False):
        self.main_page.pack_forget()
        self.hotkeys_page.pack_forget()
        target = self.main_page if page == "main" else self.hotkeys_page
        target.pack(fill="both", expand=True, padx=12, pady=12)
        self._fit_height(center)

    #System tray

    def _create_tray_icon(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.events.put(("show",)), default=True),
            pystray.MenuItem("Quit", lambda: self.events.put(("quit",))),
        )
        self.tray = pystray.Icon("throttle", Image.open(ICON_PATH), self._tray_title(), menu)
        self.tray.run_detached()

    def _tray_title(self):
        return f"{APP_NAME} – {self.config_data['percent']}%"

    def hide(self):
        self.withdraw()

    def show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    #Widget helpers

    def _button(self, parent, text, command, width=72, primary=False, **kwargs):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, height=28, corner_radius=10,
            fg_color=BLUE if primary else BORDER, hover_color=BLUE_HOVER if primary else HOVER,
            text_color="#FFFFFF" if primary else TEXT, font=("Segoe UI", 12, "bold"), **kwargs,
        )

    def _icon_button(self, parent, glyph, command, hover_color=BORDER):
        return ctk.CTkButton(
            parent, text=glyph, command=command, width=34, height=28, corner_radius=8,
            fg_color="transparent", hover_color=hover_color, text_color=TEXT_MUTED,
            font=("Segoe MDL2 Assets", 11),
        )

    def _entry(self, parent, placeholder, width=56):
        return ctk.CTkEntry(
            parent, width=width, height=28, corner_radius=8, justify="center",
            fg_color=BACKGROUND, border_color=BORDER, text_color=TEXT,
            placeholder_text=placeholder, placeholder_text_color=TEXT_FAINT, font=("Segoe UI", 12),
        )

    def _segmented(self, parent, values, command=None):
        widget = ctk.CTkSegmentedButton(
            parent, values=values, command=command, height=28, corner_radius=8,
            fg_color=BORDER, selected_color=BLUE, selected_hover_color=BLUE_HOVER,
            unselected_color=BORDER, unselected_hover_color=HOVER, text_color=TEXT,
            font=("Segoe UI", 12),
        )
        widget.set(values[0])
        return widget

    def _label(self, parent, text="", size=12, color=TEXT_MUTED, bold=False):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=("Segoe UI", size, "bold" if bold else "normal"))

    def _card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color=CARD, border_width=1, border_color=BORDER)
        card.grid_columnconfigure(0, weight=1)
        return card

    #UI

    def _build_ui(self):
        self.container = ctk.CTkFrame(self, corner_radius=0, fg_color=BACKGROUND)
        self.container.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_title_bar(self.container)
        ctk.CTkFrame(self.container, height=1, corner_radius=0, fg_color=BORDER).pack(fill="x")
        self.main_page = self._build_main_page(self.container)
        self.hotkeys_page = self._build_hotkeys_page(self.container)

    def _build_title_bar(self, parent):
        bar = ctk.CTkFrame(parent, height=40, corner_radius=0, fg_color=BACKGROUND)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        logo = ctk.CTkImage(Image.open(ICON_PATH), size=(20, 20))
        icon = ctk.CTkLabel(bar, text="", image=logo)
        icon.pack(side="left", padx=(12, 0))

        title = self._label(bar, APP_NAME, size=14, color=TEXT, bold=True)
        title.place(relx=0.5, rely=0.5, anchor="center")

        self._icon_button(bar, GLYPH_CLOSE, self.quit_app, "#C42B1C").pack(side="right", padx=(2, 8))
        self._icon_button(bar, GLYPH_MINIMIZE, self.hide).pack(side="right", padx=2)
        self.pin_button = self._icon_button(bar, GLYPH_PIN, self.toggle_pin)
        self.pin_button.pack(side="right", padx=2)

        for widget in (bar, icon, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

    def _build_main_page(self, parent):
        card = self._card(parent)

        self._label(card, APP_NAME, size=18, color=TEXT, bold=True).grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        self.status_label = ctk.CTkLabel(card, width=110, height=26, corner_radius=13,
                                         font=("Segoe UI", 12, "bold"))
        self.status_label.grid(row=0, column=1, sticky="e", padx=18, pady=(16, 0))

        self.description = self._label(card, size=13)
        self.description.grid(row=1, column=0, sticky="w", padx=18, pady=(4, 0))
        self.key_button = self._button(card, "Change key", lambda: self._start_capture("throttle"), width=96)
        self.key_button.grid(row=1, column=1, sticky="e", padx=18, pady=(4, 0))

        mode_label = self._label(card, "Key mode", size=12)
        mode_label.grid(row=2, column=0, sticky="w", padx=18, pady=(12, 0))
        self.mode_switch = self._segmented(card, ["Hold", "Toggle"], lambda value: self.set_mode(value.lower()))
        self.mode_switch.set(self.config_data["mode"].title())
        self.mode_switch.grid(row=2, column=1, sticky="e", padx=18, pady=(12, 0))

        pressure_label = self._label(card, "Pressure", size=12)
        pressure_label.grid(row=3, column=0, sticky="w", padx=18, pady=(12, 0))
        self.percent_label = self._label(card, size=16, color=TEXT, bold=True)
        self.percent_label.grid(row=3, column=1, sticky="e", padx=18, pady=(12, 0))

        slider_row = ctk.CTkFrame(card, fg_color="transparent")
        slider_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=(2, 0))
        slider_row.grid_columnconfigure(1, weight=1)
        self._icon_button(slider_row, GLYPH_MINUS, lambda: self.set_percent(self.config_data["percent"] - 1)).grid(
            row=0, column=0)
        self.slider = ctk.CTkSlider(
            slider_row, from_=0, to=100, number_of_steps=100, height=16,
            fg_color=BORDER, progress_color=BLUE, button_color=TEXT, button_hover_color="#FFFFFF",
            command=lambda value: self.set_percent(int(round(value))),
        )
        self.slider.grid(row=0, column=1, sticky="ew", padx=4)
        self._icon_button(slider_row, GLYPH_PLUS, lambda: self.set_percent(self.config_data["percent"] + 1)).grid(
            row=0, column=2)

        self.trigger_bar = ctk.CTkProgressBar(card, height=6, corner_radius=3, fg_color=BORDER,
                                              progress_color=BLUE_LIGHT)
        self.trigger_bar.grid(row=5, column=0, columnspan=2, sticky="ew", padx=18, pady=(12, 0))
        self.trigger_label = self._label(card, size=11)
        self.trigger_label.grid(row=6, column=0, sticky="w", padx=18, pady=(4, 0))
        quit_hint = self._label(card, "Ctrl+Shift+Q to quit", size=11, color=TEXT_FAINT)
        quit_hint.grid(row=6, column=1, sticky="e", padx=18, pady=(4, 0))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.grid(row=7, column=0, columnspan=2, sticky="ew", padx=18, pady=(12, 16))
        self.hotkeys_button = self._button(footer, "", lambda: self.show_page("hotkeys"), width=150)
        self.hotkeys_button.pack(side="left")
        self.retry_button = self._button(footer, "Retry", self.connect_pad, primary=True)
        self._button(footer, "Quit", self.quit_app).pack(side="right")

        self.error_hidden = [
            self.key_button, mode_label, self.mode_switch, pressure_label, self.percent_label, slider_row,
            self.trigger_bar, self.trigger_label, quit_hint,
        ]
        self._refresh_percent()
        self._render_live()
        return card

    def _build_hotkeys_page(self, parent):
        card = self._card(parent)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 4))
        self._icon_button(header, GLYPH_BACK, lambda: self.show_page("main")).pack(side="left")
        self._label(header, "Hotkeys & wheel", size=18, color=TEXT, bold=True).pack(side="left", padx=(4, 0))

        self._build_wheel_section(card).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.hotkey_list = ctk.CTkScrollableFrame(card, height=110, fg_color="transparent",
                                                  scrollbar_button_color=BORDER,
                                                  scrollbar_button_hover_color=HOVER)
        self.hotkey_list.grid(row=2, column=0, sticky="ew", padx=10)
        self.hotkey_list.grid_columnconfigure(1, weight=1)

        form = ctk.CTkFrame(card, corner_radius=12, fg_color=BACKGROUND, border_width=1, border_color=BORDER)
        form.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 14))
        form.grid_columnconfigure(1, weight=1)

        self._label(form, "New hotkey", size=12, color=TEXT, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 6))

        self.form_key_button = self._button(form, "Choose key", lambda: self._start_capture("hotkey"), width=96)
        self.form_key_button.grid(row=1, column=0, sticky="w", padx=(12, 6))
        self.form_mode = self._segmented(form, ["Set", "Toggle", "Step"], lambda _: self._render_form_fields())
        self.form_mode.grid(row=1, column=1, sticky="ew", padx=(0, 12))

        self.form_fields = ctk.CTkFrame(form, fg_color="transparent", height=28)
        self.form_fields.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))

        self.form_error = self._label(form, size=11, color=RED)
        self.form_error.grid(row=3, column=0, sticky="w", padx=12, pady=(6, 10))
        self._button(form, "Add", self._add_hotkey, primary=True).grid(
            row=3, column=1, sticky="e", padx=12, pady=(6, 10))

        self._render_form_fields()
        self._refresh_hotkey_list()
        return card

    def _build_wheel_section(self, parent):
        wheel = self.config_data["wheel"]
        section = ctk.CTkFrame(parent, corner_radius=12, fg_color=BACKGROUND, border_width=1, border_color=BORDER)
        section.grid_columnconfigure(0, weight=1)

        self.wheel_switch = ctk.CTkSwitch(
            section, text="Mouse wheel changes pressure", command=self._save_wheel_settings,
            fg_color=BORDER, progress_color=BLUE, button_color=TEXT, button_hover_color="#FFFFFF",
            text_color=TEXT, font=("Segoe UI", 12, "bold"),
        )
        self.wheel_switch.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        if wheel["enabled"]:
            self.wheel_switch.select()

        step_row = ctk.CTkFrame(section, fg_color="transparent")
        step_row.grid(row=1, column=0, sticky="w", padx=12, pady=(8, 0))
        self._label(step_row, "Each notch: up adds, down subtracts").pack(side="left")
        self.wheel_step = self._entry(step_row, "5", width=48)
        self.wheel_step.insert(0, str(wheel["step"]))
        self.wheel_step.pack(side="left", padx=6)
        self._label(step_row, "%").pack(side="left")
        for event in ("<Return>", "<FocusOut>"):
            self.wheel_step.bind(event, lambda _: self._save_wheel_settings())

        self.wheel_only_active = ctk.CTkCheckBox(
            section, text="Only while accelerating", command=self._save_wheel_settings,
            checkbox_width=18, checkbox_height=18, corner_radius=5, border_width=2,
            fg_color=BLUE, hover_color=BLUE_HOVER, border_color=HOVER, checkmark_color="#FFFFFF",
            text_color=TEXT_MUTED, font=("Segoe UI", 12),
        )
        self.wheel_only_active.grid(row=2, column=0, sticky="w", padx=12, pady=(8, 10))
        if wheel["only_while_active"]:
            self.wheel_only_active.select()
        return section

    def _render_form_fields(self):
        for widget in self.form_fields.winfo_children():
            widget.destroy()
        mode = self.form_mode.get()

        if mode == "Set":
            self._label(self.form_fields, "Set pressure to").pack(side="left")
            self.form_value = self._entry(self.form_fields, "20")
            self.form_value.pack(side="left", padx=6)
        elif mode == "Toggle":
            self._label(self.form_fields, "Toggle between").pack(side="left")
            self.form_a = self._entry(self.form_fields, "99")
            self.form_a.pack(side="left", padx=6)
            self._label(self.form_fields, "and").pack(side="left")
            self.form_b = self._entry(self.form_fields, "100")
            self.form_b.pack(side="left", padx=6)
        else:
            self.form_direction = self._segmented(self.form_fields, ["Decrease", "Increase"])
            self.form_direction.pack(side="left")
            self._label(self.form_fields, "by").pack(side="left", padx=(8, 0))
            self.form_value = self._entry(self.form_fields, "1")
            self.form_value.pack(side="left", padx=6)
        self._label(self.form_fields, "%").pack(side="left")
        self.form_error.configure(text="")

    def _refresh_hotkey_list(self):
        for widget in self.hotkey_list.winfo_children():
            widget.destroy()
        hotkeys = self.config_data["hotkeys"]

        if not hotkeys:
            self._label(self.hotkey_list, "No hotkeys yet. Add one below.", size=12, color=TEXT_FAINT).grid(
                row=0, column=0, columnspan=3, sticky="w", padx=6, pady=8)

        for i, hotkey in enumerate(hotkeys):
            chip = ctk.CTkLabel(self.hotkey_list, text=key_label(hotkey["key"]["name"]), width=56, height=26,
                                corner_radius=8, fg_color=BORDER, text_color=TEXT,
                                font=("Segoe UI", 12, "bold"))
            chip.grid(row=i, column=0, sticky="w", padx=(4, 10), pady=3)
            self._label(self.hotkey_list, describe_hotkey(hotkey), size=12, color=TEXT).grid(
                row=i, column=1, sticky="w")
            self._icon_button(self.hotkey_list, GLYPH_DELETE, lambda i=i: self._delete_hotkey(i), "#3A0D14").grid(
                row=i, column=2, sticky="e")

        count = len(hotkeys)
        self.hotkeys_button.configure(text=f"Hotkeys & wheel ({count})" if count else "Hotkeys & wheel")

    def _refresh_percent(self):
        percent = self.config_data["percent"]
        self.slider.set(percent)
        self.percent_label.configure(text=f"{percent}%")

    def _render_live(self):
        active = self.pressed
        self._set_status("active" if active else "idle")
        key = key_label(self.config_data["key"]["name"])
        if self.config_data["mode"] == "toggle":
            self.description.configure(text=f"Press  {key}  to start / stop")
        else:
            self.description.configure(text=f"Hold  {key}  to accelerate")
        value = percent_to_trigger(self.config_data["percent"]) if active else 0
        self.trigger_bar.set(value / 255)
        self.trigger_label.configure(text=f"Right trigger: {value} / 255")

    def _set_status(self, state):
        text, background, color = STATES[state]
        self.status_label.configure(text=f"● {text}", fg_color=background, text_color=color)

    def _show_error(self, message):
        self._set_status("error")
        self.description.configure(text=message, font=("Segoe UI", 11), wraplength=300, justify="left")
        if self.retry_button.winfo_manager():
            return
        for widget in self.error_hidden:
            widget.grid_remove()
        self.hotkeys_button.pack_forget()
        self.retry_button.pack(side="left")
        self._fit_height()

    def _hide_error(self):
        if not self.retry_button.winfo_manager():
            return
        self.description.configure(font=("Segoe UI", 13), wraplength=0)
        for widget in self.error_hidden:
            widget.grid()
        self.retry_button.pack_forget()
        self.hotkeys_button.pack(side="left")
        self._render_live()
        self._fit_height()

    #Pressure

    def set_percent(self, percent):
        percent = clamp(percent)
        if percent == self.config_data["percent"]:
            return
        self.config_data["percent"] = percent
        if self.pressed:
            self._send_trigger()
        self._refresh_percent()
        self._render_live()
        self.tray.title = self._tray_title()
        self._schedule_save()

    def set_mode(self, mode):
        self.config_data["mode"] = mode
        self.key_down = False
        self._engage(False)
        self._render_live()
        self._schedule_save()

    def _save_wheel_settings(self):
        wheel = self.config_data["wheel"]
        text = self.wheel_step.get().strip().rstrip("%").strip()
        if text.isdigit() and 1 <= int(text) <= 100:
            wheel["step"] = int(text)
        self.wheel_step.delete(0, "end")
        self.wheel_step.insert(0, str(wheel["step"]))
        wheel["enabled"] = bool(self.wheel_switch.get())
        wheel["only_while_active"] = bool(self.wheel_only_active.get())
        self._schedule_save()

    def _schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(400, self._save)

    def _save(self):
        self.save_job = None
        try:
            save_config(self.config_data)
        except OSError:
            pass

    #Hotkey editing

    def _add_hotkey(self):
        if not self.form_key:
            return self.form_error.configure(text="Choose a key first.")
        code = self.form_key["scan_code"]
        if code == self.config_data["key"]["scan_code"]:
            return self.form_error.configure(text="That's the throttle key.")
        if any(h["key"]["scan_code"] == code for h in self.config_data["hotkeys"]):
            return self.form_error.configure(text="That key already has a hotkey.")

        try:
            hotkey = self._read_form()
        except ValueError as e:
            return self.form_error.configure(text=str(e))

        hotkey["key"] = self.form_key
        self.config_data["hotkeys"].append(hotkey)
        self._after_hotkeys_changed()
        self.form_key = None
        self.form_key_button.configure(text="Choose key")
        self._render_form_fields()

    def _read_form(self):
        def number(entry, low, high):
            text = entry.get().strip().rstrip("%").strip()
            if not text.isdigit() or not low <= int(text) <= high:
                raise ValueError(f"Use whole numbers from {low} to {high}.")
            return int(text)

        mode = self.form_mode.get()
        if mode == "Set":
            return {"action": "set", "value": number(self.form_value, 0, 100)}
        if mode == "Toggle":
            a, b = number(self.form_a, 0, 100), number(self.form_b, 0, 100)
            if a == b:
                raise ValueError("Pick two different values.")
            return {"action": "toggle", "a": a, "b": b}
        amount = number(self.form_value, 1, 100)
        sign = 1 if self.form_direction.get() == "Increase" else -1
        return {"action": "step", "delta": sign * amount}

    def _delete_hotkey(self, index):
        del self.config_data["hotkeys"][index]
        self._after_hotkeys_changed()

    def _after_hotkeys_changed(self):
        self._refresh_hotkey_list()
        if self.pad:
            self._bind_keys()
        self._schedule_save()

    def _run_hotkey(self, index):
        hotkeys = self.config_data["hotkeys"]
        if index < len(hotkeys):
            self.set_percent(apply_hotkey(hotkeys[index], self.config_data["percent"]))

    #Key hooks

    def _bind_keys(self):
        self._unbind_keys()
        self.hooks = [keyboard.hook_key(self.config_data["key"]["scan_code"], self._on_throttle_event)]
        for i, hotkey in enumerate(self.config_data["hotkeys"]):
            self.hooks.append(keyboard.hook_key(hotkey["key"]["scan_code"],
                                                lambda e, i=i: self._on_hotkey_event(i, e)))

    def _unbind_keys(self):
        hooks, self.hooks = self.hooks, []
        for hook in hooks:
            try:
                keyboard.unhook(hook)
            except (KeyError, ValueError):
                pass
        self.hotkeys_down.clear()

    def _start_capture(self, target):
        if self.capture_target or not self.pad:
            return
        self.key_down = False
        self._engage(False)
        self._unbind_keys()
        self.capture_target = target

        if target == "throttle":
            self._set_status("binding")
            self.description.configure(text="Press any key (Esc to cancel)")
            button = self.key_button
        else:
            self.form_error.configure(text="Press any key (Esc to cancel)", text_color=BLUE_LIGHT)
            button = self.form_key_button
        button.configure(text="Listening…", fg_color=BLUE_DARK, text_color=BLUE_LIGHT)

        self.capture_hook = keyboard.on_press(
            lambda e: self.events.put(("captured", e.scan_code, e.name or f"key {e.scan_code}")))

    def _finish_capture(self, scan_code, name):
        keyboard.unhook(self.capture_hook)
        self.capture_hook = None
        target, self.capture_target = self.capture_target, None
        key = {"scan_code": scan_code, "name": name}
        cancelled = name == CANCEL_KEY
        used_by_hotkey = any(h["key"]["scan_code"] == scan_code for h in self.config_data["hotkeys"])

        if target == "throttle":
            self.key_button.configure(text="Change key", fg_color=BORDER, text_color=TEXT)
            if not cancelled and not used_by_hotkey:
                self.config_data["key"] = key
                self._schedule_save()
            self._render_live()
        else:
            self.form_error.configure(text="", text_color=RED)
            if not cancelled:
                self.form_key = key
            label = key_label(self.form_key["name"]) if self.form_key else "Choose key"
            self.form_key_button.configure(text=label, fg_color=BORDER, text_color=TEXT)

        self._bind_keys()
        if target == "throttle" and used_by_hotkey and not cancelled:
            self.description.configure(text="That key is used by a hotkey.")
            self.after(1500, self._render_live)

    #Keyboard and tray callbacks

    def _send_trigger(self):
        value = percent_to_trigger(self.config_data["percent"]) if self.pressed else 0
        with self.pad_lock:
            if not self.pad:
                return
            try:
                self.pad.right_trigger(value=value)
                self.pad.update()
            except Exception:
                self.events.put(("pad_lost",))

    def _engage(self, on):
        self.pressed = on
        self._send_trigger()

    def _on_throttle_event(self, event):
        toggle = self.config_data["mode"] == "toggle"
        if event.event_type == keyboard.KEY_DOWN:
            if self.key_down:
                return
            self.key_down = True
            self._engage(not self.pressed if toggle else True)
        else:
            self.key_down = False
            if not toggle:
                self._engage(False)

    def _on_mouse_event(self, event):
        wheel = self.config_data["wheel"]
        if not self.pad or not isinstance(event, mouse.WheelEvent) or not wheel["enabled"] or self.capture_target:
            return
        if wheel["only_while_active"] and not self.pressed:
            return
        direction = 1 if event.delta > 0 else -1
        self.events.put(("wheel", direction * wheel["step"]))

    def _on_hotkey_event(self, index, event):
        if event.event_type != keyboard.KEY_DOWN:
            self.hotkeys_down.discard(event.scan_code)
            return
        if event.scan_code in self.hotkeys_down:
            return
        self.hotkeys_down.add(event.scan_code)
        self.events.put(("hotkey", index))

    #Title bar actions

    def _start_drag(self, event):
        self.drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag(self, event):
        dx, dy = self.drag_offset
        self.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.attributes("-topmost", self.pinned)
        self.pin_button.configure(
            text_color=BLUE if self.pinned else TEXT_MUTED,
            fg_color=BLUE_DARK if self.pinned else "transparent",
        )

    #Main loop

    def _update(self, last_state=False):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "quit":
                self.quit_app()
                return
            if kind == "show":
                self.show()
            elif kind == "captured" and self.capture_hook:
                self._finish_capture(*event[1:])
            elif kind == "wheel":
                self.set_percent(self.config_data["percent"] + event[1])
            elif kind == "hotkey":
                self._run_hotkey(event[1])
            elif kind == "pad_lost":
                self._on_pad_lost()

        state = self.pressed
        if state != last_state and not self.capture_target:
            self._render_live()
        self.after(30, self._update, state)

    def quit_app(self):
        if self.save_job:
            self.after_cancel(self.save_job)
            self._save()
        if self.retry_job:
            self.after_cancel(self.retry_job)
        keyboard.unhook_all()
        mouse.unhook_all()
        self.tray.stop()
        with self.pad_lock:
            if self.pad:
                try:
                    self.pad.reset()
                    self.pad.update()
                except Exception:
                    pass
        self.destroy()


if __name__ == "__main__":
    ThrottleApp().mainloop()
