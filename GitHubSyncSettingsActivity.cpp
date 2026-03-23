#include "GitHubSyncSettingsActivity.h"

#include <GfxRenderer.h>
#include <I18n.h>

#include "MappedInputManager.h"
#include "activities/util/KeyboardEntryActivity.h"
#include "components/UITheme.h"
#include "fontIds.h"

namespace {
constexpr int MENU_ITEMS = 5;
const char* menuNames[MENU_ITEMS] = {
    "Username",
    "Token (PAT)",
    "Repo",
    "Branch",
    "Save"
};
}

void GitHubSyncSettingsActivity::onEnter() {
    Activity::onEnter();
    selectedIndex = 0;
    requestUpdate();
}

void GitHubSyncSettingsActivity::onExit() {
    Activity::onExit();
}

std::string GitHubSyncSettingsActivity::getMasked(const std::string &s) const {
    return s.empty() ? "" : "••••••••";
}

void GitHubSyncSettingsActivity::handleSelection() {
    GitHubSyncConfig cfg;
    GitHubSync::loadConfig(cfg);

    if (selectedIndex == 0) {
        startActivityForResult(
            std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, "GitHub Username",
                                                   cfg.username, 64, false),
            [](const ActivityResult &result) {
                if (!result.isCancelled) {
                    GitHubSyncConfig c;
                    GitHubSync::loadConfig(c);
                    c.username = std::get<KeyboardResult>(result.data).text;
                    GitHubSync::saveConfig(c);
                }
            });
    } else if (selectedIndex == 1) {
        startActivityForResult(
            std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, "Personal Access Token",
                                                   "", 128, false),
            [](const ActivityResult &result) {
                if (!result.isCancelled) {
                    const auto &text = std::get<KeyboardResult>(result.data).text;
                    if (!text.empty()) {
                        GitHubSyncConfig c;
                        GitHubSync::loadConfig(c);
                        c.pat = text;
                        GitHubSync::saveConfig(c);
                    }
                }
            });
    } else if (selectedIndex == 2) {
        startActivityForResult(
            std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, "Repo Name",
                                                   cfg.repo, 64, false),
            [](const ActivityResult &result) {
                if (!result.isCancelled) {
                    GitHubSyncConfig c;
                    GitHubSync::loadConfig(c);
                    c.repo = std::get<KeyboardResult>(result.data).text;
                    GitHubSync::saveConfig(c);
                }
            });
    } else if (selectedIndex == 3) {
        startActivityForResult(
            std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, "Branch",
                                                   cfg.branch, 32, false),
            [](const ActivityResult &result) {
                if (!result.isCancelled) {
                    GitHubSyncConfig c;
                    GitHubSync::loadConfig(c);
                    c.branch = std::get<KeyboardResult>(result.data).text;
                    GitHubSync::saveConfig(c);
                }
            });
    } else if (selectedIndex == 4) {
        finish();
    }
}

void GitHubSyncSettingsActivity::loop() {
    if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
        finish();
        return;
    }

    if (mappedInput.wasPressed(MappedInputManager::Button::Confirm)) {
        handleSelection();
        return;
    }

    buttonNavigator.onNext([this] {
        selectedIndex = (selectedIndex + 1) % MENU_ITEMS;
        requestUpdate();
    });

    buttonNavigator.onPrevious([this] {
        selectedIndex = (selectedIndex + MENU_ITEMS - 1) % MENU_ITEMS;
        requestUpdate();
    });
}

void GitHubSyncSettingsActivity::render(RenderLock &&) {
    renderer.clearScreen();

    const auto &metrics = UITheme::getInstance().getMetrics();
    const auto pageWidth = renderer.getScreenWidth();
    const auto pageHeight = renderer.getScreenHeight();

    GUI.drawHeader(renderer, Rect{0, metrics.topPadding, pageWidth, metrics.headerHeight}, "GitHub Sync");

    GitHubSyncConfig cfg;
    GitHubSync::loadConfig(cfg);

    const int contentTop = metrics.topPadding + metrics.headerHeight + metrics.verticalSpacing;
    const int contentHeight = pageHeight - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing * 2;

    GUI.drawList(
        renderer, Rect{0, contentTop, pageWidth, contentHeight}, MENU_ITEMS,
        selectedIndex,
        [](int index) { return std::string(menuNames[index]); },
        nullptr, nullptr,
        [this, &cfg](int index) -> std::string {
            if (index == 0) return cfg.username.empty() ? "(not set)" : cfg.username;
            if (index == 1) return cfg.pat.empty()      ? "(not set)" : getMasked(cfg.pat);
            if (index == 2) return cfg.repo.empty()     ? "xteink"    : cfg.repo;
            if (index == 3) return cfg.branch.empty()   ? "main"      : cfg.branch;
            return "";
        },
        true);

    const auto labels = mappedInput.mapLabels(tr(STR_BACK), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
    GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);

    renderer.displayBuffer();
}
