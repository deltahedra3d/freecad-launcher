# FreeCAD Smart Launcher

A desktop helper for **Linux** and **Windows** to manage FreeCAD builds, test GitHub pull requests, and browse local projects, all from one window.

> ⚠️ FreeCAD builds are downloaded directly from the official [FreeCAD GitHub releases](https://github.com/FreeCAD/FreeCAD).
> This is an unofficial launcher, not affiliated with the FreeCAD project.

<img width="1278" height="846" alt="DARK" src="https://github.com/user-attachments/assets/a4ad4011-6299-48d5-a29e-7a5f3558bafb" />
<img width="1280" height="848" alt="LIGHT" src="https://github.com/user-attachments/assets/b9510acb-e0bb-4a46-b25d-d926fc78f740" />

## Features

- **Version management**: detect, download, launch, and delete FreeCAD **stable** and **weekly** builds automatically.
  - Linux: single-file `.AppImage`.
  - Windows: portable `.7z` / `.zip` archive, extracted into its own folder.
- **Pull request testing**: fetch open PRs from `FreeCAD/FreeCAD`, view the conversation/comments, compile a PR with `cmake`/`ninja` (or with [`pixi`](https://pixi.sh) if that's how you build FreeCAD), and launch the resulting build directly.
- **Guided full build with pixi**: no existing FreeCAD source tree? The **"Compile FreeCAD with pixi…"** button clones `FreeCAD/FreeCAD` (or reuses a folder you already have), then walks you through `pixi run configure` and `pixi run build` step by step, with a confirmation before each stage and a live progress dialog. `git` and `pixi` are installed automatically if missing (see [Requirements](#requirements)).
- **Project library**: scan folders for CAD files, keep a recent-files list, and launch a project with a chosen FreeCAD version (including inside an already-running instance).
- **Project preview**: thumbnail preview of the selected project in the launcher. On Linux, an interactive **3D view** of `.FCStd`, `.step`/`.stp`, `.iges`/`.igs`, `.stl`, and `.brep` files is also available using [F3D](https://f3d.app/) (recommended), with `vtk` as a fallback and `cadquery-ocp` used to tessellate STEP/IGES files.
- **Desktop integration**: create menu entries for installed versions (`.desktop` files on Linux, Start Menu shortcuts on Windows).
- **Usage statistics**: track time spent and launch counts per FreeCAD version (and per tested PR build). Sessions are recorded even when **Close launcher on launch** is enabled.
- **Single-instance lock**: prevents opening the launcher twice at once.

### Linux vs Windows at a glance

| | Linux | Windows |
|---|---|---|
| Installed version format | `.AppImage` file | Folder ending in `.FreeCADPortable` (extracted from the official `.7z`/`.zip`) |
| Menu entries | `.desktop` files | `.lnk` shortcuts in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\FreeCAD Launcher` |
| Interactive 3D view (F3D) | ✅ | ❌ (thumbnail preview only) |
| "Launch with HiDPI scale" and "Vanilla launch" options | ✅ | ❌ |
| PR builds with `cmake` | `cmake` (+ `ninja` recommended) | `cmake` + **`ninja` required**, plus Visual Studio Build Tools |
| Auto-install of `git` | via your distro's package manager | via `winget`, `choco` or `scoop` |
| Auto-install of `pixi` | official `install.sh` | official `install.ps1` (PowerShell) |
| FUSE fallback (`--appimage-extract-and-run`) | ✅ | not applicable |

## Download

Download the latest build for your system from the [Releases](../../releases) page.

### Linux

Make the AppImage executable and run it:

```bash
chmod +x FreeCAD_Smart_Launcher-<version>-linux-x86_64.AppImage
./FreeCAD_Smart_Launcher-<version>-linux-x86_64.AppImage
```

If the AppImage refuses to start with a FUSE error (some Ubuntu/Linux Mint installs don't ship it), install `libfuse2` (`libfuse2t64` on Ubuntu 24.04 / Mint 22), or run it with `--appimage-extract-and-run`. The FreeCAD AppImages downloaded by the launcher have the same requirement.

No Python, PySide6, or other installation is required: everything the app needs is bundled inside the AppImage.

### Windows

Download the Windows build from the Releases page and run it. No Python or PySide6 installation is required.

FreeCAD is distributed for Windows as a portable `.7z` archive. The launcher downloads it and extracts it for you, using **7-Zip** if it finds it (fastest, handles very long paths) and falling back to the built-in `py7zr` library otherwise.

> 💡 If extraction fails with a "path too long" error, enable Windows long paths or set the install folder closer to the drive root (e.g. `C:\FC`).

### First run

On first run, the launcher creates its install folder at `~/Applications/FreeCAD` (`C:\Users\<you>\Applications\FreeCAD` on Windows, configurable from the app), where it stores downloaded FreeCAD versions, `launcher_config.json`, and `time_tracker.json`.

## Requirements

The only tools that are **not** bundled are listed below. You don't need to pre-install `git` or `pixi`: the launcher offers to do it for you.

| Tool | Needed for | Linux | Windows |
|---|---|---|---|
| `git` | Compiling/testing a PR, or a full pixi build | ✅ auto-install via your distro's package manager (asks for admin privileges) | ✅ auto-install via `winget`, `choco` or `scoop`. Otherwise install [Git for Windows](https://git-scm.com/download/win) |
| [pixi](https://pixi.sh) | Building FreeCAD with pixi instead of cmake/ninja | ✅ official user-level installer (no root needed) | ✅ official PowerShell installer (no admin needed) |
| `cmake` + `ninja` | Compiling a PR the classic way | ❌ install manually (`ninja` recommended) | ❌ install manually (`ninja` **required**, e.g. `pip install ninja`) |
| Visual Studio Build Tools | Compiling on Windows | n/a | ❌ install manually. Located automatically with `vswhere` |
| [7-Zip](https://www.7-zip.org/) | Extracting FreeCAD `.7z` archives | n/a | Optional (recommended). Falls back to `py7zr` |
| [F3D](https://f3d.app/) | 3D view of project files | ❌ install manually | n/a |

## Running from source

If you'd rather run the Python script directly (e.g. to contribute):

- **Python 3.9+**
- Linux: uses `.desktop` files and AppImages
- Windows: uses portable archives and Start Menu shortcuts

**Linux**

```bash
pip install PySide6
python freecad_smart_launcher_linux.py
```

Optional, for the 3D preview panel (used as fallbacks/tessellation if F3D isn't picking up the file):

```bash
pip install vtk cadquery-ocp
```

**Windows**

```powershell
pip install PySide6 py7zr
python freecad_smart_launcher_windows.py
```

To test and build FreeCAD pull requests, you'll also need a full FreeCAD build toolchain and a cloned `FreeCAD/FreeCAD` source folder:

- **Linux**: `git`, `cmake`, `ninja` recommended, or `git` and [`pixi`](https://pixi.sh) if you build with pixi. See [Compile on Linux](https://wiki.freecad.org/Compile_on_Linux).
- **Windows**: `git`, Visual Studio Build Tools, and either `cmake` + `ninja` or [`pixi`](https://pixi.sh). See [Compile on Windows](https://wiki.freecad.org/Compile_on_Windows).

### Testing a pull request

1. Point **"TEST A GITHUB PULL REQUEST"** at your local `FreeCAD/FreeCAD` git clone.
2. Enter a PR number (or search/browse open PRs from within the app).
3. Click **Build**: the launcher runs `git fetch origin pull/<PR>/head`, configures with `cmake` (using `ninja` if available), and builds with your machine's CPU core count.
4. Click **Launch** to run the compiled build, optionally opening a project from your library with it.

**Building with pixi.** If you compile FreeCAD with [pixi](https://pixi.sh), tick **Use pixi to build PRs** in the PR section. This is separate from the **"Compile FreeCAD with pixi…"** button described above under Features, which does a full guided clone + build rather than testing a specific PR. The launcher then runs `pixi run configure` and `pixi run build` in your source folder instead of calling `cmake` directly. The option is off by default: upstream FreeCAD always ships a `pixi.toml`, so its presence alone doesn't switch the build. If `cmake` isn't installed but `pixi` and a `pixi.toml` are available, the launcher falls back to pixi automatically. The compiled executable is looked up in `build/debug/bin`, `build/release/bin` and `build/bin`.

**Your local changes are stashed.** Before checking out the PR branch, the launcher runs `git stash push -u` if your clone has uncommitted changes (untracked files included). You can get them back afterwards with `git stash list` / `git stash pop`. The build output is also logged to `~/.freecad_launcher_build.log`.

#### Windows build notes

- **Use a source folder path without spaces** (e.g. `C:\FC\FreeCAD`). The pixi build fails on Windows when the path contains a space, and the launcher warns you before starting. If you already tried once, delete the old `build` folder.
- **Visual Studio Build Tools** are located with `vswhere`, and the launcher loads the x64 compiler environment (`vcvarsall.bat x64`) before configuring and building.
- **`ninja` is required** for the classic `cmake` build on Windows (the default Visual Studio generator isn't supported by the launcher).
- **pixi is updated automatically** with `pixi self-update` if it is older than the `requires-pixi` version in FreeCAD's `pixi.toml`.
- **Stale build folders are cleaned up.** If a previous failed configure cached the wrong Python, that build folder is deleted so the retry starts clean.
- The launcher's own Python environment (`VIRTUAL_ENV`, `PYTHONHOME`, …) is stripped from the build environment, so it can't be picked up by CMake instead of the pixi environment's Python.

## Notes

- All GitHub API calls are unauthenticated by default and therefore subject to GitHub's standard [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) for anonymous requests.
- Config and stats files from older versions (`~/.freecad_launcher_config.json`, `~/.freecad_time_tracker.json`) are migrated automatically into the install folder on first run.
- Time tracking only counts sessions started from the launcher (not from a menu entry or shortcut). Linux ignores sessions shorter than 5 seconds; on Windows every launch is counted and time is added for sessions longer than 2 seconds.
- With **Close launcher on launch** enabled, the window closes but the launcher process stays alive in the background until FreeCAD exits, so opening a second launcher in the meantime shows the "already open" message.
- On Linux systems without FUSE, the launcher retries with `--appimage-extract-and-run`; sessions started through that fallback are not counted in the statistics.
- On Windows, if the FreeCAD process you started exits right after spawning the real GUI, the launcher keeps watching for `FreeCAD.exe` in the same install folder so the session time is still recorded.

## License

MIT

## Donation
Want to help the project? Please consider a donation. Thanks in advance!

<a href="https://ko-fi.com/deltahedra">
  <img width="400"  alt="kofi_logo" src="https://github.com/user-attachments/assets/183d4e06-f538-4d3b-a6d3-f0c314681f38" />
</a>
