#include "GitHubSync.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <SD.h>
#include <WiFi.h>

#define GH_PREFS_NS   "github_sync"
#define GH_KEY_USER   "username"
#define GH_KEY_PAT    "pat"
#define GH_KEY_REPO   "repo"
#define GH_KEY_BRANCH "branch"
#define GH_SHA_DIR    "/.crosspoint/github_sha/"
#define GH_BOOKS_DIR  "/"
#define GH_SLEEP_BMP  "sleep.bmp"
#define GH_SLEEP_PATH "/sleep.bmp"
#define GH_API_BASE   "https://api.github.com"

bool GitHubSync::loadConfig(GitHubSyncConfig &cfg) {
    Preferences prefs;
    prefs.begin(GH_PREFS_NS, true);
    cfg.username = prefs.getString(GH_KEY_USER, "").c_str();
    cfg.pat      = prefs.getString(GH_KEY_PAT,  "").c_str();
    cfg.repo     = prefs.getString(GH_KEY_REPO,   "xteink").c_str();
    cfg.branch   = prefs.getString(GH_KEY_BRANCH, "main").c_str();
    prefs.end();
    return !cfg.username.empty() && !cfg.pat.empty();
}

void GitHubSync::saveConfig(const GitHubSyncConfig &cfg) {
    Preferences prefs;
    prefs.begin(GH_PREFS_NS, false);
    prefs.putString(GH_KEY_USER,   cfg.username.c_str());
    prefs.putString(GH_KEY_PAT,    cfg.pat.c_str());
    prefs.putString(GH_KEY_REPO,   cfg.repo.c_str());
    prefs.putString(GH_KEY_BRANCH, cfg.branch.c_str());
    prefs.end();
}

bool GitHubSync::isConfigured() {
    GitHubSyncConfig cfg;
    return loadConfig(cfg);
}

const char* GitHubSync::resultMessage(GitHubSyncResult r) {
    switch (r) {
        case GitHubSyncResult::OK:             return "GitHub sync complete";
        case GitHubSyncResult::NOT_CONFIGURED: return "GitHub sync: not configured";
        case GitHubSyncResult::NO_WIFI:        return "GitHub sync: no WiFi";
        case GitHubSyncResult::AUTH_ERROR:     return "GitHub sync: auth failed (check PAT)";
        case GitHubSyncResult::REPO_NOT_FOUND: return "GitHub sync: repo not found";
        case GitHubSyncResult::API_ERROR:      return "GitHub sync: API error";
        case GitHubSyncResult::SD_ERROR:       return "GitHub sync: SD card error";
        case GitHubSyncResult::PARSE_ERROR:    return "GitHub sync: bad API response";
        default:                               return "GitHub sync: unknown error";
    }
}

std::string GitHubSync::shaFilePath(const std::string &filename) {
    std::string safe = filename;
    for (char &c : safe) if (c == '/') c = '_';
    return std::string(GH_SHA_DIR) + safe + ".sha";
}

std::string GitHubSync::loadLocalSha(const std::string &filename) {
    std::string path = shaFilePath(filename);
    File f = SD.open(path.c_str(), FILE_READ);
    if (!f) return "";
    String sha = f.readString();
    f.close();
    sha.trim();
    return sha.c_str();
}

void GitHubSync::saveLocalSha(const std::string &filename, const std::string &sha) {
    SD.mkdir(GH_SHA_DIR);
    std::string path = shaFilePath(filename);
    File f = SD.open(path.c_str(), FILE_WRITE);
    if (!f) return;
    f.print(sha.c_str());
    f.close();
}

bool GitHubSync::fetchFileList(const GitHubSyncConfig &cfg, std::string &outJson, GitHubSyncResult &err) {
    std::string url = std::string(GH_API_BASE) + "/repos/" + cfg.username + "/" +
                      cfg.repo + "/contents/?ref=" + cfg.branch;

    HTTPClient http;
    http.begin(url.c_str());
    http.addHeader("Authorization", ("token " + cfg.pat).c_str());
    http.addHeader("Accept", "application/vnd.github.v3+json");
    http.addHeader("User-Agent", "CrossPoint-X4");

    int code = http.GET();
    if (code == 401 || code == 403) { http.end(); err = GitHubSyncResult::AUTH_ERROR;     return false; }
    if (code == 404)                { http.end(); err = GitHubSyncResult::REPO_NOT_FOUND; return false; }
    if (code != 200)                { http.end(); err = GitHubSyncResult::API_ERROR;      return false; }

    outJson = http.getString().c_str();
    http.end();
    return true;
}

bool GitHubSync::downloadFile(const GitHubSyncConfig &cfg, const std::string &path, const std::string &sha, GitHubSyncResult &err) {
    std::string url = std::string(GH_API_BASE) + "/repos/" + cfg.username + "/" +
                      cfg.repo + "/contents/" + path + "?ref=" + cfg.branch;

    HTTPClient http;
    http.begin(url.c_str());
    http.addHeader("Authorization", ("token " + cfg.pat).c_str());
    http.addHeader("Accept", "application/vnd.github.v3.raw");
    http.addHeader("User-Agent", "CrossPoint-X4");

    int code = http.GET();
    if (code == 401 || code == 403) { http.end(); err = GitHubSyncResult::AUTH_ERROR; return false; }
    if (code != 200)                { http.end(); err = GitHubSyncResult::API_ERROR;  return false; }

    std::string destPath = (path == GH_SLEEP_BMP) ? GH_SLEEP_PATH : std::string(GH_BOOKS_DIR) + path;

    File f = SD.open(destPath.c_str(), FILE_WRITE);
    if (!f) { http.end(); err = GitHubSyncResult::SD_ERROR; return false; }

    WiFiClient *stream = http.getStreamPtr();
    uint8_t buf[512];
    int total = http.getSize();
    int remaining = total;

    while (http.connected() && (remaining > 0 || total == -1)) {
        size_t available = stream->available();
        if (available) {
            size_t read = stream->readBytes(buf, min(available, sizeof(buf)));
            f.write(buf, read);
            if (remaining > 0) remaining -= (int)read;
        }
        delay(1);
    }

    f.close();
    http.end();
    saveLocalSha(path, sha);
    return true;
}

GitHubSyncResult GitHubSync::sync() {
    GitHubSyncConfig cfg;
    if (!loadConfig(cfg)) return GitHubSyncResult::NOT_CONFIGURED;
    if (WiFi.status() != WL_CONNECTED) return GitHubSyncResult::NO_WIFI;

    std::string jsonStr;
    GitHubSyncResult err = GitHubSyncResult::OK;
    if (!fetchFileList(cfg, jsonStr, err)) return err;

    JsonDocument doc;
    DeserializationError jsonErr = deserializeJson(doc, jsonStr);
    if (jsonErr) return GitHubSyncResult::PARSE_ERROR;

    JsonArray files = doc.as<JsonArray>();
    for (JsonObject file : files) {
        std::string type = file["type"].as<const char*>();
        std::string name = file["name"].as<const char*>();
        std::string sha  = file["sha"].as<const char*>();

        if (type != "file") continue;

        bool isEpub  = name.size() > 5 && (name.substr(name.size()-5) == ".epub" || name.substr(name.size()-5) == ".EPUB");
        bool isSleep = (name == GH_SLEEP_BMP);

        if (!isEpub && !isSleep) continue;

        std::string localSha = loadLocalSha(name);
        if (localSha == sha) continue;

        if (!downloadFile(cfg, name, sha, err)) return err;
    }

    return GitHubSyncResult::OK;
}
