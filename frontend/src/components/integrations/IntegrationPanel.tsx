"use client";

import { FlaskConical, Workflow } from "lucide-react";

import { CalendarEventReview } from "@/components/calendar/CalendarEventReview";
import { DownloadedFiles } from "@/components/files/DownloadedFiles";
import { EmailDraftPreview } from "@/components/gmail/EmailDraftPreview";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { YouTubeResults } from "@/components/youtube/YouTubeResults";
import { useCalendar } from "@/hooks/useCalendar";
import { useDownloads } from "@/hooks/useDownloads";
import { useEmailDraft } from "@/hooks/useEmailDraft";
import { useIntegrations } from "@/hooks/useIntegrations";
import { useWorkflow } from "@/hooks/useWorkflow";
import { useYouTube } from "@/hooks/useYouTube";
import { cn } from "@/lib/utils";

import { DomainStatusCard } from "./DomainStatusCard";
import { IntegrationActivity } from "./IntegrationActivity";
import { WorkflowSummary } from "./WorkflowSummary";

import type { IntegrationsState } from "@/context/taskPilotReducer";
import { INTEGRATION_ACTION_TYPES, type IntegrationActionType } from "@/types/integration";
import type { TaskPlan } from "@/types/plan";

export interface IntegrationPanelProps {
  sessionId: string | null;
  plan: TaskPlan;
  integrations: IntegrationsState | null;
  connected: boolean;
  className?: string;
}

export function planUsesIntegrations(plan: TaskPlan | null): boolean {
  return !!plan && plan.steps.some((s) => (INTEGRATION_ACTION_TYPES as readonly string[]).includes(s.action.type));
}

/**
 * YouTube / Gmail drafts / Calendar / safe downloads of the ACTIVE task. Every value comes from
 * the backend (validated plan before Run Plan, observed browser state afterwards).
 */
export function IntegrationPanel({ sessionId, plan, integrations, connected, className }: IntegrationPanelProps) {
  const taskId = plan.task_id;
  const types = new Set(plan.steps.map((s) => s.action.type as IntegrationActionType));
  const ran = integrations?.taskId === taskId;
  const revision = ran ? integrations.revision : 0;
  const on = connected && !!sessionId;
  const common = { sessionId, taskId, revision };
  const status = useIntegrations({ sessionId, enabled: on, revision });
  const wf = useWorkflow({ ...common, enabled: on });
  const yt = useYouTube({ ...common, enabled: on && ran && (types.has("youtube_search") || types.has("youtube_play")) });
  const mail = useEmailDraft({ ...common, enabled: on && types.has("gmail_create_draft") });
  const cal = useCalendar({ ...common, enabled: on && types.has("calendar_create_event") });
  const files = useDownloads({ sessionId, enabled: on && types.has("file_download"), revision });
  const usedDomains = new Set(wf.workflow?.domains ?? []);
  const fixture = plan.assumptions.some((a) => a.includes("LOCAL TEST FIXTURE"));

  return (
    <Card className={cn("flex flex-col", className)} aria-labelledby="integration-panel-title" data-testid="integration-panel">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle id="integration-panel-title">
          <Workflow className="h-3.5 w-3.5" aria-hidden /> Integrations
        </CardTitle>
        {fixture && (
          <Badge variant="violet" title="Local test fixture — not the real website">
            <FlaskConical className="h-3 w-3" aria-hidden /> Test fixture
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status.statuses && (
          <div className="grid gap-2 sm:grid-cols-2" data-testid="domain-status-grid">
            {status.statuses.filter((s) => usedDomains.size === 0 || usedDomains.has(s.domain)).map((s) => (
              <DomainStatusCard key={s.domain} entry={s} />
            ))}
          </div>
        )}
        {wf.workflow && <WorkflowSummary workflow={wf.workflow} onChoose={wf.choose} />}
        {yt.results && yt.results.results.length > 0 && <YouTubeResults data={yt.results} />}
        {mail.draft && <EmailDraftPreview view={mail.draft} saving={mail.saving} onSave={mail.save} />}
        {cal.review && <CalendarEventReview review={cal.review} />}
        {files.files && <DownloadedFiles files={files.files} urlFor={files.urlFor} deleting={files.deleting} onDelete={files.remove} />}
        {ran && <IntegrationActivity activity={integrations.activity} />}
      </CardContent>
    </Card>
  );
}
