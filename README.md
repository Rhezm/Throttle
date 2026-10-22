<p align="center">
  <img src="icon.ico" width="96" alt="Throttle icon">
</p>

<h1 align="center">Throttle</h1>

<p align="center">
  Bind partial, adjustable throttle to a single keyboard key.<br>
  Made for the heavy-vehicle acceleration trick in GTA Online, and handy as cruise throttle in games like Euro Truck Simulator 2.
</p>

---

## Why

On a keyboard, throttle is either 0% or 100%. Some tricks — like the heavy-vehicle acceleration glitch in GTA Online — need the throttle held *just below* full, which normally means using a controller's analog trigger.

Throttle creates a virtual Xbox 360 controller and holds its right trigger at a pressure you choose (**99%** by default) while you hold a key. You keep steering and aiming with your keyboard and mouse as usual.

No game files are modified and nothing is injected into the game process: the input comes from a virtual controller driver, the same approach used by Steam Input and DS4Windows.

## Features

- Partial throttle on a single key — `<` by default on ISO keyboards
- **Hold** mode (accelerate while the key is held) or **Toggle** mode (press once to start, again to stop)
- Adjustable pressure from 0% to 100% (99% by default)
- Hotkeys to change the pressure in game: set a value, toggle between two values, or step up/down
- Mouse wheel control: each notch adds or subtracts a chosen amount
- Rebind keys from inside the app; all settings are saved
- Minimizes to the system tray, next to the clock
- Pin button to keep the window on top
- Small, dark UI that starts instantly
- `Ctrl+Shift+Q` to quit from anywhere

## Requirements

- Windows 10 or 11
- [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) driver — **required**, install it once before running the app

## Usage

1. Install **ViGEmBus** and restart if asked.
2. Download `Throttle.exe` from the [Releases](../../releases) page and run it. It asks for administrator rights so the key works while the game window is focused.
3. Hold the key (`<` by default) in game to accelerate at the chosen pressure.

To change the key, click **Change key** and press the key you want. Press `Esc` to cancel.

Choose a **Key mode**:
- **Hold** — the trigger is pressed only while you hold the key. Best for GTA Online.
- **Toggle** — press the key once to keep the trigger pressed, press it again to release. Best for cruising in Euro Truck Simulator 2 and similar games.

Use the **Pressure** slider (or the − / + buttons) to choose how far the trigger is pressed.

### Hotkeys

Open **Hotkeys & wheel**, click **Choose key**, pick an action and click **Add**. Each hotkey fires once per press:

| Action | Example | Effect |
|---|---|---|
| **Set** | `F1` → set to 20% | Pressure becomes 20% |
| **Toggle** | `L` → toggle 99% ↔ 100% | Switches between the two values on each press |
| **Step** | `F2` → increase by 1% | 99% → 100%; a decrease of 3% goes 99% → 96% → 93%… |

Changes apply instantly, even while you're holding the throttle key. Hotkey keys still reach the game, so pick keys the game doesn't use.

### Mouse wheel

In **Hotkeys & wheel**, turn on **Mouse wheel changes pressure** and set how much each notch changes it (5% by default): scrolling up adds, scrolling down subtracts.

With **Only while accelerating** checked (the default), the wheel only changes the pressure while the throttle is engaged, so it doesn't interfere when you're not driving. The wheel still reaches the game too — in games that use it for zoom or weapon selection, both will happen.

Example for Euro Truck Simulator 2: Toggle mode, wheel enabled with a 5% step. Tap the key to start driving, then scroll to speed up or slow down.

All settings are stored in `%APPDATA%\Throttle\config.json`.

The minimize button hides the window in the system tray. Double-click the tray icon to bring it back, or right-click it for **Show** / **Quit**.

## Known behavior

- **The camera recenters while accelerating.** While the trigger is held, the game treats you as a controller player and applies controller camera behavior. Release the key and the mouse camera goes back to normal. This is done by the game, not by the app.
- **"Get an app to open this 'ms-gamebar' link" popup.** Windows tries to open Xbox Game Bar when a controller connects. If Game Bar is uninstalled, run these in a command prompt and sign out and back in:
  ```
  reg add HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR /f /t REG_DWORD /v AppCaptureEnabled /d 0
  reg add HKCU\System\GameConfigStore /f /t REG_DWORD /v GameDVR_Enabled /d 0
  ```
- **The "<" key doesn't exist on US keyboards.** Use **Change key** to pick any other key.
- **"Couldn't connect to the ViGEmBus driver."** Throttle retries automatically every 3 seconds, so there's no need to restart it: install the driver or wait for it to start and the window connects by itself. You can also press **Retry**. If the driver stops while the app is running, it reconnects the same way.

## Build from source

```
pip install vgamepad keyboard mouse customtkinter pystray pillow pyinstaller
python Throttle.py
```

To build the executable (with `icon.ico` in the same folder):

```
python -m PyInstaller --onefile --noconsole --uac-admin --icon icon.ico --add-data "icon.ico;." --hidden-import pystray._win32 --collect-all vgamepad --collect-all customtkinter --exclude-module numpy Throttle.py
```

The executable is written to `dist\`.

## Disclaimer

This tool only emulates a controller; it does not read or modify game memory. Even so, use in online games is at your own risk — I can't guarantee how any game's anti-cheat will treat virtual controllers.

## Credits

- [vgamepad](https://github.com/yannbouteiller/vgamepad) and [ViGEm](https://github.com/nefarius/ViGEmBus) for virtual controller emulation
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) for the UI
- [pystray](https://github.com/moses-palmer/pystray) for the tray icon
- [keyboard](https://github.com/boppreh/keyboard) and [mouse](https://github.com/boppreh/mouse) for global input hooks
