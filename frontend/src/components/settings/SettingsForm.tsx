"use client";

import { Check, Loader2, Settings as SettingsIcon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthGate";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTaskPilotActions, useTaskPilotState } from "@/hooks/useTaskPilot";
import { DEFAULT_PREFERENCES, type UserPreferences } from "@/lib/preferencesApi";

import { usePreferences } from "./PreferencesProvider";

const LANGUAGES: { value: UserPreferences["language"]; label: string }[] = [
  { value: "auto", label: "Match my language (auto)" },
  { value: "hinglish", label: "Hinglish" },
  { value: "en", label: "English" },
  { value: "hi", label: "हिन्दी (Hindi)" },
];

function Toggle({ id, label, hint, checked, onChange, disabled }: {
  id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <label htmlFor={id} className="flex items-start justify-between gap-4 rounded-md border border-white/[0.06] px-3 py-2.5">
      <span className="flex flex-col gap-0.5">
        <span className="text-sm text-foreground">{label}</span>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </span>
      <input id={id} type="checkbox" role="switch" className="mt-1 h-4 w-4 accent-cyan-500" checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</legend>
      {children}
    </fieldset>
  );
}

/** Settings page: edits are saved to the backend (database) and restored after refresh or sign-in. */
export function SettingsForm() {
  const { prefs, loaded, loadError, save } = usePreferences();
  const { agentInfo } = useTaskPilotState();
  const { setVoiceReplies } = useTaskPilotActions();
  const { user, authRequired, signOut } = useAuth();
  const [draft, setDraft] = useState<UserPreferences>(prefs);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => setDraft(prefs), [prefs]);

  const set = <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setStatus(null);
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(prefs);

  const onSave = async () => {
    setSaving(true);
    const result = await save(draft);
    setSaving(false);
    if (result.ok && !draft.voice_output_enabled) setVoiceReplies(false); // turning voice output off silences replies too
    setStatus(result.ok ? { ok: true, text: "Saved. Your settings apply right away and are kept after refresh." } : { ok: false, text: result.error ?? "Not saved." });
  };

  return (
    <Card aria-labelledby="settings-title" data-testid="settings-form">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle id="settings-title"><SettingsIcon className="h-3.5 w-3.5" aria-hidden /> Settings</CardTitle>
        {!loaded && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading settings" />}
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {loadError && <p role="alert" className="text-xs text-level-error">{loadError} Showing defaults.</p>}

        <Section title="Conversation">
          <label htmlFor="pref-name" className="flex flex-col gap-1 text-sm">
            What should Kamlesh Bhai call you?
            <input id="pref-name" type="text" maxLength={40} value={draft.display_name} placeholder="e.g. Kartik"
              onChange={(e) => set("display_name", e.target.value)}
              className="rounded-md border border-border bg-transparent px-3 py-2 text-sm" />
            <span className="text-[11px] text-muted-foreground">Used in greetings (“Arey Kartik bhai!”). Leave empty for just “bhai”.</span>
          </label>
          <label htmlFor="pref-language" className="flex flex-col gap-1 text-sm">
            Reply language
            <select id="pref-language" value={draft.language} onChange={(e) => set("language", e.target.value as UserPreferences["language"])}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm">
              {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
            <span className="text-[11px] text-muted-foreground">Also sets the speech-recognition language in voice mode (Hindi → hi-IN, otherwise en-IN).</span>
          </label>
        </Section>

        <Section title="Voice">
          <Toggle id="pref-voice-in" label="Voice input (microphone)" hint="Show the microphone in the Command Center."
            checked={draft.voice_input_enabled} onChange={(v) => set("voice_input_enabled", v)} />
          <Toggle id="pref-auto-submit" label="Hands-free voice mode" disabled={!draft.voice_input_enabled}
            hint="The mic starts a conversation: what you say is sent automatically after a short pause. Off = the mic only types into the box."
            checked={draft.voice_auto_submit} onChange={(v) => set("voice_auto_submit", v)} />
          <Toggle id="pref-continuous" label="Keep listening after each reply" disabled={!draft.voice_auto_submit}
            hint="Talk back and forth without clicking the mic again. Stop any time with “Stop voice”."
            checked={draft.voice_continuous} onChange={(v) => set("voice_continuous", v)} />
          <Toggle id="pref-auto-exec" label="Auto-run low-risk voice requests" disabled={!draft.voice_auto_submit}
            hint="Opening sites, searching and adding to cart start without Run Plan. Orders, payments, sending and deleting never auto-run and always ask."
            checked={draft.voice_auto_execute} onChange={(v) => set("voice_auto_execute", v)} />
          <Toggle id="pref-voice-out" label="Spoken replies in voice mode" hint="Kamlesh Bhai answers out loud using your browser's voices."
            checked={draft.voice_output_enabled} onChange={(v) => set("voice_output_enabled", v)} />
          <label htmlFor="pref-rate" className="flex flex-col gap-1 text-sm">
            Speaking speed: {draft.speech_rate.toFixed(2)}×
            <input id="pref-rate" type="range" min={0.5} max={1.5} step={0.05} value={draft.speech_rate}
              onChange={(e) => set("speech_rate", Number(e.target.value))} />
          </label>
        </Section>

        <Section title="Shopping">
          <label htmlFor="pref-store" className="flex flex-col gap-1 text-sm">
            Preferred store (suggestions only — Kamlesh Bhai still asks when a request is unclear)
            <select id="pref-store" value={draft.preferred_store} onChange={(e) => set("preferred_store", e.target.value as UserPreferences["preferred_store"])}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm">
              <option value="none">No preference</option>
              <option value="blinkit">Blinkit</option>
              <option value="amazon">Amazon India</option>
            </select>
          </label>
        </Section>

        <Section title="Planner">
          <p className="text-sm" data-testid="settings-planner">
            {agentInfo ? (agentInfo.is_mock ? "Offline rule-based planner (no AI)" : `${agentInfo.provider} · ${agentInfo.model}`) : "Unknown (backend offline)"}
          </p>
          {agentInfo?.setup_hint && <p className="text-[11px] text-level-warning">{agentInfo.setup_hint}</p>}
        </Section>

        {authRequired && user && (
          <Section title="Account">
            <p className="text-sm">{user.email} · {user.role.toLowerCase().replace("_", " ")}</p>
            <div><Button variant="outline" size="sm" onClick={() => void signOut()}>Sign out</Button></div>
          </Section>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-white/[0.06] pt-4">
          <Button onClick={() => void onSave()} disabled={!dirty || saving || !loaded} data-testid="settings-save">
            {saving ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />} Save settings
          </Button>
          <Button variant="ghost" onClick={() => setDraft(DEFAULT_PREFERENCES)} disabled={saving}>Reset to defaults</Button>
          {status && <p role="status" className={status.ok ? "text-xs text-level-success" : "text-xs text-level-error"}>{status.text}</p>}
        </div>
      </CardContent>
    </Card>
  );
}
