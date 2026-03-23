# xteink-github-sync

Sync `.epub` files (and an optional `sleep.bmp`) from a GitHub repository to your CrossPoint/xteink device at boot.

This repo contains:
1. The device-side C++ implementation (`GitHubSync.*`, `GitHubSyncSettingsActivity.*`)
2. A Python patcher (`patch.py`) that injects the feature into your CrossPoint Reader codebase and uploads the firmware (with a prompt to connect via USB first).

## What it syncs

- All files in the root of your GitHub repo ending in `.epub`
- `sleep.bmp` in the repo root (optional)

The device compares GitHub blob SHAs against cached SHAs stored on the SD card and downloads only what changed.

## GitHub repo setup

1. Create a **private** GitHub repo (example: `xteink`)
2. Add `.epub` files to the **root** of the repo
3. Optionally add `sleep.bmp` (152x152 grayscale BMP)
4. Create a Personal Access Token (PAT):
   - Token type: classic or a fine-grained token with equivalent access
   - Scopes/permissions: `contents: read-only` (or equivalent for reading repository contents)
5. In the device UI (or during initial setup), configure:
   - GitHub username
   - PAT
   - Repo name
   - Branch (default: `main`)

## How the sync works (device behavior)

- After WiFi connects, the firmware calls the GitHub Contents API
- For each candidate file in the repo root (`*.epub` and `sleep.bmp`), it:
  - Fetches the GitHub blob SHA
  - Compares it to the cached SHA stored at `/.crosspoint/github_sha/` on the SD card
  - Downloads the raw file if the SHA differs or is missing locally
- Download destinations on the SD card:
  - `/sleep.bmp` for the sleep image
  - `/<filename>.epub` for book files
- Files are **not** deleted automatically

## Requirements (local machine)

- `git`
- `platformio` (PlatformIO CLI, provides `pio`)
- `esptool.py` (used by PlatformIO for uploading)
- `esp-idf-nvs-partition-gen` (used to build an NVS partition for flashing credentials)
- Python packages the script may prompt to install (press `Enter` when asked):
  - `platformio`
  - `esptool`
  - `esp-idf-nvs-partition-gen`
  - `certifi` (recommended on macOS to avoid `CERTIFICATE_VERIFY_FAILED`)

## Usage

Run the patcher:

```bash
python3 patch.py
```

Optional arguments:

```bash
python3 patch.py /path/to/destination [usb_upload_port]
```

What it does:

1. Clones/updates `crosspoint-reader` into `destination/crosspoint-reader`
2. Copies the C++ files into the correct CrossPoint locations
3. Injects the startup sync call into the CrossPoint boot path
4. Adds a “GitHub Sync” entry to the settings menu
5. Optionally writes NVS credentials (username/PAT/repo/branch) into the device
6. Prompts you to connect the device via USB before uploading
7. Runs `pio run --target upload`

## Prompts and validation

During setup, `patch.py` will prompt for:

- GitHub username
  - Validates reachability via `GET https://api.github.com/users/{username}`
- PAT
  - Validates via `GET https://api.github.com/user`
- Repo name
  - Validates via `GET https://api.github.com/repos/{owner}/{repo}` using your PAT

Before uploading firmware, it prompts you to:
- Connect the xteink device via **USB data** (not charge-only)
- Press `Enter` once connected
- It then shows likely serial ports and PlatformIO’s device list to help you choose the correct upload port.

## Troubleshooting

### `CERTIFICATE_VERIFY_FAILED` talking to GitHub

On macOS, Python can miss the system CA bundle. Recommended fix:

```bash
pip3 install certifi
```

The script uses `certifi` automatically when available.

If you *must* bypass SSL verification (insecure), you can run:

```bash
export GITHUB_SYNC_SSL_NO_VERIFY=1
python3 patch.py
```

### Upload picks the wrong serial device (e.g. Bluetooth)

Make sure you use a **data** USB cable and that the device is connected.

Use the prompt (or pass the upload port explicitly) so PlatformIO/esptool doesn’t auto-detect a non-ESP32 serial device.

If you still have trouble, try:
- Unplugging Bluetooth devices temporarily
- Passing `usb_upload_port` explicitly to `patch.py`

## Integration details

See `INTEGRATION.md` for the file injection locations and the CrossPoint-side integration checklist.

