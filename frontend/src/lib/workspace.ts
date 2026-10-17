import { apiJson } from "./api";

export type WorkspaceVersion = {
  id: string;
  title: string;
  content: string;
  created_at: string;
  kind?: "generated" | "edit" | "imported";
  model?: string;
  parent_id?: string;
  evidence_revision?: number | null;
};
export type WorkspaceTranscript = {
  full_text: string;
  segments: {
    start: number;
    end: number;
    text: string;
    speaker_id?: string;
    speaker_label?: string;
  }[];
  aliases?: Record<string, string>;
};
export type WorkspaceSummary = {
  key: string;
  title: string;
  source_type: string;
  source_device: string;
  revision: number;
  updated_at: string;
  created_at: string;
  deleted: boolean;
  version_count: number;
  archived: boolean;
};
export type WorkspaceNote = WorkspaceSummary & {
  content: string;
  transcript: WorkspaceTranscript | null;
  metadata: Record<string, unknown>;
  versions: WorkspaceVersion[];
  next_versions_offset: number | null;
  acknowledged_revision?: number;
};
export type WorkspaceWrite = {
  base_revision: number;
  operation_id: string;
  title: string;
  content: string;
  source_type: string;
  source_device: string;
  archived?: boolean;
  transcript?: WorkspaceTranscript | null;
  metadata?: Record<string, unknown>;
  versions?: WorkspaceVersion[];
};
export type WorkspaceStatus = {
  service_id?: string;
  configured: boolean;
  mode: "local" | "shared";
  owner: string;
  media_sync: boolean;
  capabilities: { notes: boolean; versions: boolean; conflicts: boolean };
  server_time: string;
};
export const workspacePath = (key: string) =>
  `/api/workspace/notes/${encodeURIComponent(key)}`;
export const workspaceStatus = () =>
  apiJson<WorkspaceStatus>("/api/workspace/status");
export const listWorkspacePage = (offset = 0) =>
  apiJson<{ items: WorkspaceSummary[]; next_offset: number | null }>(
    `/api/workspace/notes?offset=${offset}&limit=50&include_deleted=true`,
  );
export const getWorkspaceNote = (key: string, offset = 0) =>
  apiJson<WorkspaceNote>(
    `${workspacePath(key)}?versions_offset=${offset}&versions_limit=50`,
  );
export const putWorkspaceNote = (key: string, body: WorkspaceWrite) =>
  apiJson<WorkspaceNote>(workspacePath(key), {
    method: "PUT",
    body: JSON.stringify({
      ...body,
      // Evidence links are server-owned read metadata, not version write fields.
      versions: body.versions?.map((version) => ({
        id: version.id,
        title: version.title,
        content: version.content,
        created_at: version.created_at,
        kind: version.kind ?? "imported",
        model: version.model ?? "",
        parent_id: version.parent_id ?? "",
      })),
    }),
  });

// Only text and explicit portable metadata enter the shared workspace.
export function portableMarkdown(content: string) {
  return content.replace(
    /!?\[([^\]]*)\]\(([^)]+)\)/g,
    (match, label: string, target: string) => {
      const url = target.trim().replace(/^<|>$/g, "");
      if (/^attachment:\/\/[a-f0-9]{64}$/.test(url)) return match;
      if (
        /^(?:file:|blob:|data:|[a-z]:[\\/]|\\\\|\/(?:api|data|output)\/)/i.test(
          url,
        )
      )
        return label || "本机附件";
      try {
        const parsed = new URL(url);
        if (
          /^(localhost|127\..*|0\.0\.0\.0|\[::1\]|192\.168\..*|10\..*|172\.(1[6-9]|2\d|3[01])\..*)$/i.test(
            parsed.hostname,
          )
        )
          return label || "本机附件";
      } catch {
        if (
          !url.startsWith("#") &&
          !url.startsWith("https://") &&
          !url.startsWith("http://")
        )
          return label || "本机附件";
      }
      return match;
    },
  );
}
