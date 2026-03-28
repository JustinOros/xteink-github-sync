#pragma once

#include "activities/Activity.h"
#include "GitHubSync.h"
#include "util/ButtonNavigator.h"

class GitHubSyncSettingsActivity final : public Activity {
public:
  explicit GitHubSyncSettingsActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
      : Activity("GitHubSync", renderer, mappedInput) {}

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

private:
  ButtonNavigator buttonNavigator;
  int selectedIndex = 0;
  std::string syncStatus;

  static constexpr int MENU_ITEMS = 7;

  void handleSelection();
  void doSync();
  std::string getMasked(const std::string& s) const;
};
