import { apiJson } from "./api";
export type MCPConnection = {
  id: string;
  name: string;
  url: string;
  authType: "none" | "token" | "vinote-session";
  managed?: boolean;
  providerId?: string | null;
  hasCredential: boolean;
  enabled: boolean;
  status: "unverified" | "connected" | "error";
  lastError: string | null;
  discoveredAt: string | null;
};
export type MCPTool = {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  enabled: boolean;
  definitionHash: string;
  requiresConfirmation: true;
  annotations: Record<string, unknown>;
};
export type MCPRun = {
  id: string;
  connectionId: string;
  requestId: string;
  toolName: string;
  status:
    | "awaiting_confirmation"
    | "running"
    | "succeeded"
    | "failed"
    | "unknown"
    | "cancelled";
  arguments: Record<string, unknown>;
  result: unknown;
  error: { code: string; message: string } | null;
  confirmationToken: string | null;
  confirmationExpiresAt: string | null;
  createdAt: string;
  updatedAt: string;
};
export const mcpBase = "/api/mcp-connections";
export const listMCPConnections = () =>
  apiJson<{ connections: MCPConnection[] }>(mcpBase);
export const listMCPRuns = (offset = 0) =>
  apiJson<{ runs: MCPRun[] }>(`${mcpBase}/runs?limit=50&offset=${offset}`);
export const mcpRunLabel: Record<MCPRun["status"], string> = {
  awaiting_confirmation: "等待确认",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  unknown: "结果未知",
  cancelled: "已取消待执行请求",
};


export const cloudTranslationProvider = "vinote-cloud-translation";
export const cloudTranslationTool = "vinote_translate_text";
export type MCPTranslationProvision = {
  connection: MCPConnection;
  provider: {
    id: string; name: string; toolName: string; textParameter: string;
    languageParameter: string; targetLanguages: string[]; modelSource: string; configured: boolean;
  };
};
export const provisionMCPTranslation = () => apiJson<MCPTranslationProvision>(
  `${mcpBase}/first-party/translation`, { method: "POST", body: "{}" });
export const isCloudTranslation = (connection: MCPConnection | undefined) =>
  !!connection?.managed && connection.authType === "vinote-session" && connection.providerId === cloudTranslationProvider;
export function cloudTranslationSchema(tool: MCPTool): boolean {
  const schema = tool.inputSchema;
  if (tool.name !== cloudTranslationTool || schema.type !== "object" || schema.additionalProperties !== false
    || !Array.isArray(schema.required) || schema.required.length !== 2
    || !schema.required.includes("text") || !schema.required.includes("target_language")
    || !schema.properties || typeof schema.properties !== "object" || Array.isArray(schema.properties)) return false;
  const props = schema.properties as Record<string, Record<string, unknown>>;
  return Object.keys(props).length === 3 && props.text?.type === "string" && props.target_language?.type === "string" && props.model?.type === "string"
    && Array.isArray(props.target_language.enum) && props.target_language.enum.length === 2
    && props.target_language.enum.includes("zh") && props.target_language.enum.includes("en")
    && !['$ref', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else'].some(key => key in schema || key in props.text || key in props.target_language || key in props.model);
}
