# GitHub Sync — Manual Integration (Advanced)

If you prefer not to use the auto-patcher (`patch.py`), follow these steps to integrate GitHub Sync into a CrossPoint/xteink firmware tree manually.

## Files to copy into your CrossPoint repo

Copy the files from this repository into your CrossPoint firmware repo at the following destinations:

| Source (this repo) | Destination (CrossPoint repo) |
|---|---|
| `GitHubSync.h` | `include/GitHubSync.h` |
| `GitHubSync.cpp` | `src/github_sync/GitHubSync.cpp` |
| `GitHubSyncSettingsActivity.h` | `include/GitHubSyncSettingsActivity.h` |
| `GitHubSyncSettingsActivity.cpp` | `src/activities/settings/GitHubSyncSettingsActivity.cpp` |

Notes:
- Ensure the destination folders exist (`src/github_sync/`, `src/activities/settings/`).
- Your CrossPoint repo may use slightly different folder names; the important part is that your build system compiles the `.cpp` files and that includes resolve from `include/`.

## 1) `platformio.ini` dependency

Make sure ArduinoJson v7 is available in `lib_deps`:

```ini
bblanchon/ArduinoJson @ ^7
```

If your project already depends on ArduinoJson, do not duplicate it.

## 2) Call sync after WiFi connects (boot/startup path)

Find your boot path after WiFi is connected (often near where OTA update checks happen) and add:

```cpp
#include "GitHubSync.h"

// After WiFi is up:
if (GitHubSync::isConfigured()) {
    GitHubSyncResult result = GitHubSync::sync();
    if (result != GitHubSyncResult::OK) {
        // Replace this with your project's preferred UI/logging mechanism.
        // (Some CrossPoint forks use LOG_ERR; others use Serial; some show a toast.)
        LOG_ERR("SYNC", "%s", GitHubSync::resultMessage(result));
        // Or: Serial.printf("[SYNC] %s\n", GitHubSync::resultMessage(result));
    }
}
```

Important:
- The return type is **`GitHubSyncResult`** (not `SyncResult`).
- If your firmware does not define `LOG_ERR`, use whatever logging you already use (or `Serial.printf`).

## 3) Add a Settings entry ("GitHub Sync")

In your settings menu implementation (commonly something like `SettingsActivity.cpp`):

1. Include the activity:

```cpp
#include "GitHubSyncSettingsActivity.h"
```

2. Add a new item in the settings list that navigates to the activity.

The exact code depends on your UI framework, but the action should instantiate/push:

```cpp
std::make_unique<GitHubSyncSettingsActivity>(renderer, mappedInput)
```

3. Add a translation string (if your project uses translations):
- Add a string ID similar to `STR_GITHUB_SYNC`
- Map it to the label `GitHub Sync` in your translation files

## 4) (Optional) Web settings editor schema

If your CrossPoint fork has a web settings editor that can read/write NVS keys, add these keys:

```json
{ "ns": "github_sync", "key": "username", "label": "GitHub Username", "type": "text" },
{ "ns": "github_sync", "key": "pat",      "label": "GitHub PAT",      "type": "password" },
{ "ns": "github_sync", "key": "repo",     "label": "Repo name",       "type": "text" },
{ "ns": "github_sync", "key": "branch",   "label": "Branch",          "type": "text" }
```

Namespace/keys used by firmware:
- Namespace: `github_sync`
- Keys: `username`, `pat`, `repo`, `branch`

## 5) GitHub repo setup (for content)

1. Create a GitHub repo (private recommended)
2. Add `.epub` files to the **repo root**
3. Optionally add `sleep.bmp` to the repo root (152x152 grayscale BMP)
4. Create a PAT with permission to read repository contents
5. On device: Settings → GitHub Sync:
   - username
   - PAT
   - repo
   - branch

## Behavior summary

- On boot (after WiFi connects), the device calls the GitHub Contents API for the repo root.
- For each `*.epub` and `sleep.bmp` found:
  - Compare GitHub blob SHA to cached SHA stored in `/.crosspoint/github_sha/` on the SD card
  - Download only when SHA differs or is missing locally
- Download destinations:
  - `sleep.bmp` → `/sleep.bmp`
  - `*.epub` → `/<filename>.epub` (SD card root)
- No automatic deletions are performed.

## RAM note

The GitHub Contents API directory listing is small (one JSON object per file). Downloads are streamed directly to SD using a small buffer.

