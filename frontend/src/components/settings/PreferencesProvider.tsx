"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { DEFAULT_PREFERENCES, getPreferences, updatePreferences, type UserPreferences } from "@/lib/preferencesApi";

interface PreferencesState {
  prefs: UserPreferences;
  /** True once the server copy was loaded (or loading failed and defaults are in use). */
  loaded: boolean;
  loadError: string | null;
  save: (patch: Partial<UserPreferences>) => Promise<{ ok: boolean; error?: string }>;
  reload: () => Promise<void>;
}

const PreferencesContext = createContext<PreferencesState>({
  prefs: DEFAULT_PREFERENCES,
  loaded: false,
  loadError: null,
  save: async () => ({ ok: false, error: "Preferences are not available." }),
  reload: async () => undefined,
});

export const usePreferences = () => useContext(PreferencesContext);

/** Loads the user's saved preferences from the backend (database) and keeps them in sync after saves. */
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setPrefs(await getPreferences());
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : "Could not load your settings.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(async (patch: Partial<UserPreferences>) => {
    try {
      setPrefs(await updatePreferences(patch));
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error instanceof ApiError ? error.message : "Could not save your settings." };
    }
  }, []);

  const value = useMemo(() => ({ prefs, loaded, loadError, save, reload }), [prefs, loaded, loadError, save, reload]);
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}
