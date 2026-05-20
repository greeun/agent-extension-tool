import React from "react";
import { Confirm } from "../components/Confirm.js";
import { PATHS } from "../../core/paths.js";
import { removeInstalledPlugin } from "../../core/plugin.js";
import { removePluginFromSettings } from "../../core/settings.js";
import { rm } from "fs/promises";

interface Props {
  pluginId: string;
  installPath: string;
  onDone: () => void;
  onCancel: () => void;
}

export function RemoveWizard({ pluginId, installPath, onDone, onCancel }: Props) {
  const handleConfirm = async () => {
    await rm(installPath, { recursive: true, force: true });
    await removeInstalledPlugin(PATHS.installedPlugins, pluginId);
    await removePluginFromSettings(PATHS.settings, pluginId);
    onDone();
  };

  return (
    <Confirm
      message={`Remove "${pluginId}"? This will delete ${installPath}`}
      onConfirm={handleConfirm}
      onCancel={onCancel}
    />
  );
}
