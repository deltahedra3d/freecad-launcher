# FreeCAD Launcher

A desktop helper for Linux to manage FreeCAD AppImages, test GitHub pull requests, and browse local projects, all from one window.

> ⚠️ AppImages are downloaded directly from the official [FreeCAD GitHub releases](https://github.com/FreeCAD/FreeCAD).
> 
<img width="1278" height="846" alt="DARK" src="https://github.com/user-attachments/assets/a4ad4011-6299-48d5-a29e-7a5f3558bafb" />
<img width="1280" height="848" alt="LIGHT" src="https://github.com/user-attachments/assets/b9510acb-e0bb-4a46-b25d-d926fc78f740" />

## Features

- **AppImage management** — detect, download, launch, and delete FreeCAD **stable** and **weekly** builds automatically.
- **Pull request testing** — fetch open PRs from `FreeCAD/FreeCAD`, view the conversation/comments, compile a PR with `cmake`/`ninja` (or with [`pixi`](https://pixi.sh) if that's how you build FreeCAD), and launch the resulting build directly.
- **Guided full build with pixi** — no existing FreeCAD source tree? The **"Compile FreeCAD with pixi…"** button clones `FreeCAD/FreeCAD` (or reuses a folder you already have), then walks you through `pixi run configure` and `pixi run build` step by step, with a confirmation before each stage and a live progress dialog. `git` and `pixi` are installed automatically if missing (`git` via your distro's package manager with a privilege prompt; `pixi` via its official user-level installer, no root needed).
- **Project library** — scan folders for CAD files, keep a recent-files list, and launch a project with a chosen FreeCAD version (including inside an already-running instance).
- **3D preview** — quick preview of `.FCStd`, `.step`/`.stp`, `.iges`/`.igs`, `.stl`, and `.brep` files using [F3D](https://f3d.app/) (recommended), with `vtk` as a fallback and `cadquery-ocp` used to tessellate STEP/IGES files.
- **Desktop integration** — create `.desktop` menu entries for installed versions.
- **Usage statistics** — track time spent and launch counts per FreeCAD version (and per tested PR build). Sessions are recorded even when **Close launcher on launch** is enabled.
- **Single-instance lock** — prevents opening the launcher twice at once.

## Download

Download the latest AppImage from the [Releases](../../releases) page, make it executable, and run it:

```bash
chmod +x FreeCAD_Smart_Launcher-<version>-linux-x86_64.AppImage
./FreeCAD_Smart_Launcher-<version>-linux-x86_64.AppImage
```

If the AppImage refuses to start with a FUSE error (some Ubuntu/Linux Mint installs don't ship it), install `libfuse2` (`libfuse2t64` on Ubuntu 24.04 / Mint 22), or run it with `--appimage-extract-and-run`. The FreeCAD AppImages downloaded by the launcher have the same requirement.

No Python, PySide6, or other installation is required — everything the app needs is bundled inside the AppImage.

The only tools that are **not** bundled — you don't need to pre-install them, though:

| Tool | Needed for | Auto-install |
|---|---|---|
| `git` | Compiling/testing a PR, or a full pixi build | ✅ launcher offers to install it via your distro's package manager (asks for admin privileges) |
| [pixi](https://pixi.sh) | Building FreeCAD with pixi instead of cmake/ninja | ✅ launcher offers to install it via the official user-level installer (no root needed) |
| `cmake` (and ideally `ninja`) | Compiling a PR the classic way | ❌ install manually if you don't use pixi |
| [F3D](https://f3d.app/) | 3D preview of project files | ❌ install manually |

On first run, the launcher creates its install folder at `~/Applications/FreeCAD` (configurable from the app), where it stores downloaded AppImages, `launcher_config.json`, and `time_tracker.json`.

## Running from source

If you'd rather run the Python script directly (e.g. to contribute):

- **Linux** (uses `.desktop` files and AppImages; not intended for Windows/macOS)
- **Python 3.9+**

```bash
pip install PySide6
python freecad_smart_launcher.py
```

Optional, for the 3D preview panel (used as fallbacks/tessellation if F3D isn't picking up the file):

```bash
pip install vtk cadquery-ocp
```

To test and build FreeCAD pull requests, you'll also need a full FreeCAD build toolchain (`git`, `cmake`, `ninja` recommended — or `git` and [`pixi`](https://pixi.sh) if you build with pixi) and a cloned `FreeCAD/FreeCAD` source folder. See [Compile on Linux](https://wiki.freecad.org/Compile_on_Linux) on the FreeCAD wiki.

### Testing a pull request

1. Point **"TEST A GITHUB PULL REQUEST"** at your local `FreeCAD/FreeCAD` git clone.
2. Enter a PR number (or search/browse open PRs from within the app).
3. Click **Build** — the launcher runs `git fetch origin pull/<PR>/head`, configures with `cmake` (using `ninja` if available), and builds with your machine's CPU core count.
4. Click **Launch** to run the compiled build, optionally opening a project from your library with it.

**Building with pixi.** If you compile FreeCAD with [pixi](https://pixi.sh), tick **Use pixi to build PRs** in the PR section. This is separate from the **"Compile FreeCAD with pixi…"** button described above under Features, which does a full guided clone + build rather than testing a specific PR. The launcher then runs `pixi run configure` and `pixi run build` in your source folder instead of calling `cmake` directly. The option is off by default: upstream FreeCAD always ships a `pixi.toml`, so its presence alone doesn't switch the build. If `cmake` isn't installed but `pixi` and a `pixi.toml` are available, the launcher falls back to pixi automatically. The compiled executable is looked up in `build/debug/bin`, `build/release/bin` and `build/bin`.

**Your local changes are stashed.** Before checking out the PR branch, the launcher runs `git stash push -u` if your clone has uncommitted changes (untracked files included). You can get them back afterwards with `git stash list` / `git stash pop`. The build output is also logged to `~/.freecad_launcher_build.log`.

## Notes

- All GitHub API calls are unauthenticated by default and therefore subject to GitHub's standard [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) for anonymous requests.
- Config and stats files from older versions (`~/.freecad_launcher_config.json`, `~/.freecad_time_tracker.json`) are migrated automatically into the install folder on first run.
- Time tracking only counts sessions started from the launcher (not from a `.desktop` entry) that last more than 5 seconds. With **Close launcher on launch** enabled, the window closes but the launcher process stays alive in the background until FreeCAD exits, so opening a second launcher in the meantime shows the "already open" message.
- On systems without FUSE, the launcher retries with `--appimage-extract-and-run`; sessions started through that fallback are not counted in the statistics.

## License

MIT

## Donation
Want to help the project? Please consider a donation. Thanks in advance!

<a href="https://ko-fi.com/deltahedra">
  <img width="400"  alt="kofi_logo" src="https://github.com/user-attachments/assets/183d4e06-f538-4d3b-a6d3-f0c314681f38" />
</a>

  
  
