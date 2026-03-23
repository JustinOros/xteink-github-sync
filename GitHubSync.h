#pragma once

#include <Arduino.h>
#include <string>

struct GitHubSyncConfig {
    std::string username;
    std::string pat;
    std::string repo;
    std::string branch;
};

enum class GitHubSyncResult {
    OK,
    NOT_CONFIGURED,
    NO_WIFI,
    AUTH_ERROR,
    REPO_NOT_FOUND,
    API_ERROR,
    SD_ERROR,
    PARSE_ERROR
};

class GitHubSync {
public:
    static bool loadConfig(GitHubSyncConfig &cfg);
    static void saveConfig(const GitHubSyncConfig &cfg);
    static bool isConfigured();
    static GitHubSyncResult sync();
    static const char* resultMessage(GitHubSyncResult r);

private:
    static bool fetchFileList(const GitHubSyncConfig &cfg, std::string &outJson, GitHubSyncResult &err);
    static bool downloadFile(const GitHubSyncConfig &cfg, const std::string &path, const std::string &sha, GitHubSyncResult &err);
    static std::string loadLocalSha(const std::string &filename);
    static void saveLocalSha(const std::string &filename, const std::string &sha);
    static std::string shaFilePath(const std::string &filename);
};
