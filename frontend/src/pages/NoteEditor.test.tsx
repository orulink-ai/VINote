import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, Link, useLocation } from "react-router-dom";
import { I18nProvider } from "../lib/i18n";
import { NoteEditor } from "./NoteEditor";
import { useWorkspaceStore } from "../stores/workspaceStore";

const noteStoreMock = vi.hoisted(() => ({
  loadNoteById: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
  createShareLink: vi.fn(),
  getShareLink: vi.fn(),
  disableShareLink: vi.fn(),
}));

const apiMock = vi.hoisted(() => ({
  apiJson: vi.fn(),
  apiFetch: vi.fn(),
}));

vi.mock("../lib/api", () => ({ apiJson: apiMock.apiJson, apiFetch: apiMock.apiFetch }));
vi.mock("../stores/languageStore", () => ({
  useLanguageStore: () => ({
    language: "en",
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}));
vi.mock("../stores/noteLibraryStore", () => ({
  useNoteLibraryStore: () => noteStoreMock,
}));
vi.mock("../components/Notes/RecordingRetryBar", () => ({
  RecordingRetryBar: () => null,
}));

const transcriptEvidence = {
  language: "en",
  full_text: "We agree to active Sort former.",
  aliases: {},
  metadata: { asr_model: "sensevoice-small" },
  segments: [
    {
      start: 62,
      end: 72,
      text: "We agreed to activate Sortformer.",
      raw_text: "We agree to active Sort former.",
      cleaned_text: "We agreed to activate Sortformer.",
      speaker_id: "speaker_01",
      speaker_label: "Speaker 1",
    },
  ],
};

function ContextDestination() {
  const location = useLocation();
  return <><output aria-label="Destination">{location.pathname + location.search + location.hash}</output><output aria-label="Context return">{location.state?.returnTo}</output><Link to={location.state?.returnTo || "/notes"}>Return to content</Link></>;
}

function renderEditor(
  initialEntry:
    | string
    | { pathname: string; search?: string; hash?: string; state: { returnTo: string } } = "/note/note-1",
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route
          path="/note/:id"
          element={
            <I18nProvider>
              <NoteEditor />
            </I18nProvider>
          }
        />
        <Route path="/workspace/:id" element={<ContextDestination />} />
        <Route path="/settings/mcp" element={<ContextDestination />} />
        <Route path="/files" element={<ContextDestination />} />
        <Route path="/notes" element={<div>Notes</div>} />
        <Route path="/" element={<div>Recording workbench</div>} />
        <Route path="/assistant" element={<div>Meeting assistant</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function openContentActions() {
  const trigger = screen.getByRole("button", { name: "Content actions" });
  if (!trigger.closest("details")?.open) fireEvent.click(trigger);
}

async function openDeleteAction() {
  openContentActions();
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
}

describe("NoteEditor transcript evidence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({ mappings: {}, items: [], changeDeleted: vi.fn(async key => ({ key, deleted: true }) as never) });
    Object.defineProperty(window.HTMLMediaElement.prototype, "play", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
    Object.defineProperty(window.HTMLMediaElement.prototype, 'load', { configurable: true, value: vi.fn() });
    apiMock.apiFetch.mockResolvedValue(new Response(null, { status: 206 }));
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    apiMock.apiJson.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith('/recording')) return Promise.resolve({ available: true, deleted: false, can_delete: false, filename: 'sample.webm', size_bytes: 1000 });
      if (path.endsWith("/speakers") && init?.method === "PATCH") {
        return Promise.resolve({ aliases: { speaker_01: "Susan Wang" } });
      }
      return Promise.resolve(transcriptEvidence);
    });
    noteStoreMock.loadNoteById.mockResolvedValue({
      id: "note-1",
      title: "Meeting note",
      content: "# Meeting minutes\n\nMinutes only.",
      sourceType: "meeting_recording",
      taskId: "task-1",
      status: "done",
      scope: "personal",
      createdAt: "2026-07-01T00:00:00Z",
      updatedAt: "2026-07-01T00:00:00Z",
    });
    noteStoreMock.getShareLink.mockResolvedValue(null);
  });

  it("keeps a static title with visible edit/export/share/delete actions and Feishu publication", async () => {
    renderEditor();
    await screen.findByText("Minutes only.");
    expect(screen.getAllByRole("heading", { name: "Meeting note", level: 1 })).toHaveLength(1);
    expect(screen.queryByRole("textbox", { name: "Meeting title" })).not.toBeInTheDocument();
    const primary = screen.getByRole("group", { name: "Primary content actions" });
    expect(within(primary).getAllByRole("button")).toHaveLength(5);
    expect(within(primary).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(primary).getByRole("button", { name: "发布到飞书" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "历史版本" })).not.toBeVisible();
    openContentActions();
    expect(screen.getByRole("button", { name: "历史版本" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出 Markdown" })).toBeInTheDocument();
    expect(within(primary).getByRole("button", { name: "Share" })).toBeVisible();
    expect(within(primary).getByRole("button", { name: "Delete" })).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("merges an exactly matching body title only in reading and exports unchanged saved Markdown", async () => {
    const note = await noteStoreMock.loadNoteById();
    noteStoreMock.loadNoteById.mockResolvedValue({ ...note, content: "# Meeting note\n\nMinutes only." });
    renderEditor();
    await screen.findByText("Minutes only.");
    expect(screen.getAllByRole("heading", { name: "Meeting note", level: 1 })).toHaveLength(1);
    openContentActions();
    fireEvent.click(screen.getByRole("button", { name: "导出 Markdown" }));
    expect(screen.getByRole("dialog").querySelector("pre")).toHaveTextContent("# Meeting note");
    expect(noteStoreMock.updateNote).not.toHaveBeenCalled();
  });

  it("retains a distinct body heading and uses a labelled title input only after editing", async () => {
    renderEditor();
    await screen.findByRole("heading", { name: /Meeting minutes/, level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Meeting title")).toHaveValue("Meeting note");
    expect(screen.queryByRole("heading", { name: "Meeting note", level: 1 })).not.toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Back to reading" })); });
    expect(screen.getByRole("heading", { name: "Meeting note", level: 1 })).toBeInTheDocument();
    expect(screen.queryByLabelText("Meeting title")).not.toBeInTheDocument();
  });

  it("uses note title wording for document content without a transcript tab", async () => {
    const note = await noteStoreMock.loadNoteById();
    noteStoreMock.loadNoteById.mockResolvedValue({ ...note, sourceType: "document", taskId: undefined });
    renderEditor();
    await screen.findByText("Minutes only.");
    expect(screen.queryByRole("radio", { name: "Transcript" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Note title")).toHaveValue("Meeting note");
    expect(screen.queryByLabelText("Meeting title")).not.toBeInTheDocument();
  });

  it("keeps saved versions and MCP translation separate from version history with contextual return", async () => {
    useWorkspaceStore.setState({ mappings: { "note-1": { key: "real-shared-key", revision: 3, fingerprint: "saved" } } });
    renderEditor("/note/note-1?view=summary");
    await screen.findByText("Minutes only.");
    openContentActions();
    expect(screen.getByText("Version history")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View saved versions" })).toHaveAttribute("href", "/workspace/real-shared-key");
    const translation = screen.getByRole("link", { name: "Full-text translation · MCP" });
    expect(translation).toHaveAttribute("href", "/settings/mcp?mode=translation&note=real-shared-key");
    expect(within(screen.getByRole("group", { name: "Primary content actions" })).getByRole("button", { name: "Delete" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Meeting title"), { target: { value: "Draft title" } });
    expect(translation).toHaveAttribute("aria-disabled", "true");
    expect(translation).toHaveAttribute("tabindex", "-1");
    fireEvent.click(translation);
    expect(screen.getByLabelText("Meeting title")).toHaveValue("Draft title");
    expect(noteStoreMock.updateNote).not.toHaveBeenCalled();
  });

  it.each(["View original file", "View saved versions", "Full-text translation · MCP"])("preserves file filters, selected original and ancestor on a %s round trip", async action => {
    const parent = "/files?type=file&q=test&file=file-1&returnTo=%2Fprojects%3Fproject%3Dp1%26archive%3D1";
    useWorkspaceStore.setState({ mappings: { "note-1": { key: "real-shared-key", revision: 3, fingerprint: "saved" } } });
    renderEditor({ pathname: "/note/note-1", search: "?view=summary", hash: "#decision", state: { returnTo: parent } });
    await screen.findByText("Minutes only.");
    openContentActions();
    fireEvent.click(screen.getByRole("link", { name: action }));
    const context = screen.getByLabelText("Context return").textContent!;
    const url = new URL(context, "https://vinote.invalid");
    expect(url.searchParams.get("view")).toBe("summary");
    expect(url.searchParams.get("returnTo")).toBe(parent);
    expect(url.hash).toBe("#decision");
    fireEvent.click(screen.getByRole("link", { name: "Return to content" }));
    await screen.findByText("Minutes only.");
    fireEvent.click(screen.getByRole("button", { name: "Return to list" }));
    expect(screen.getByLabelText("Destination").textContent).toBe(parent);
  });

  it("routes document originals through the verified file index using only the actual note identity", async () => {
    const note = await noteStoreMock.loadNoteById();
    noteStoreMock.loadNoteById.mockResolvedValue({ ...note, sourceType: 'document', taskId: undefined });
    renderEditor({ pathname: '/note/note-1', search: '?view=summary', hash: '#section', state: { returnTo: '/files?type=file&q=pdf&file=real-original' } });
    await screen.findByText('Minutes only.');
    openContentActions();
    const group = screen.getByRole('region', { name: 'Versions and source' });
    const source = within(group).getByRole('link', { name: 'View original file' });
    const url = new URL(source.getAttribute('href')!, 'https://vinote.invalid');
    expect(url.pathname).toBe('/files');
    expect(url.searchParams.get('note')).toBe('note-1');
    expect(url.searchParams.has('file')).toBe(false);
    const detail = new URL(url.searchParams.get('returnTo')!, 'https://vinote.invalid');
    expect(detail.pathname).toBe('/note/note-1');
    expect(detail.searchParams.get('view')).toBe('summary');
    expect(detail.searchParams.get('returnTo')).toBe('/files?type=file&q=pdf&file=real-original');
    expect(detail.hash).toBe('#section');
    fireEvent.click(source);
    expect(screen.getByLabelText('Destination').textContent).toBe(url.pathname + url.search);
    expect(screen.getByLabelText('Context return').textContent).toBe(url.searchParams.get('returnTo'));
    expect(noteStoreMock.updateNote).not.toHaveBeenCalled();
  });

  it("explains why an unsaved draft cannot navigate to the original file", async () => {
    renderEditor();
    await screen.findByText('Minutes only.');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Meeting title'), { target: { value: 'Unsaved draft' } });
    openContentActions();
    const source = screen.getByRole('link', { name: 'View original file' });
    expect(source).toHaveAttribute('aria-disabled', 'true');
    expect(source).toHaveAttribute('tabindex', '-1');
    expect(source).toHaveAccessibleDescription('Save your changes before viewing the original file.');
    expect(screen.getByText('Save your changes before viewing the original file.')).toBeVisible();
    fireEvent.click(source);
    expect(screen.getByLabelText('Meeting title')).toHaveValue('Unsaved draft');
    expect(screen.queryByLabelText('Destination')).not.toBeInTheDocument();
    expect(noteStoreMock.updateNote).not.toHaveBeenCalled();
  });

  it("rejects an external query parent after returning to detail", async () => {
    renderEditor("/note/note-1?returnTo=https%3A%2F%2Funtrusted.invalid");
    await screen.findByText("Minutes only.");
    fireEvent.click(screen.getByRole("button", { name: "Return to list" }));
    expect(await screen.findByText("Notes")).toBeInTheDocument();
  });

  it("does not invent a synced object for content with no acknowledged mapping", async () => {
    renderEditor();
    await screen.findByText("Minutes only.");
    openContentActions();
    expect(screen.getByText(/This tool does not yet support this saved content/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View saved versions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Full-text translation · MCP" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Configure MCP tools" })).toHaveAttribute("href", "/settings/mcp");
    expect(apiMock.apiJson.mock.calls.some(([path]) => String(path).includes("/invoke"))).toBe(false);
  });

  it("opens the rendered summary and only shows Markdown when editing is requested", async () => {
    renderEditor();
    await screen.findByText("Minutes only.");
    expect(screen.queryByDisplayValue(/Minutes only/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const editor = await screen.findByDisplayValue(/Minutes only/);
    fireEvent.change(editor, {
      target: { value: "# Revised summary\n\nUpdated decision." },
    });
    fireEvent.click(screen.getByRole("radio", { name: "Preview" }));
    expect(await screen.findByText("Updated decision.")).toBeInTheDocument();
    expect(
      screen.queryByDisplayValue(/Updated decision/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Edit" }));
    fireEvent.click(screen.getByRole("radio", { name: "Split" }));
    expect(
      await screen.findByDisplayValue(/Updated decision/),
    ).toBeInTheDocument();
    expect(screen.getByText("Updated decision.")).toBeInTheDocument();
  });

  it.each([
    ["/", "Notes"],
    ["/assistant", "Notes"],
    ["https://untrusted.invalid", "Notes"],
  ])("returns to the supported entry point %s", async (returnTo, expected) => {
    renderEditor({ pathname: "/note/note-1", state: { returnTo } });
    await screen.findByText("Minutes only.");
    fireEvent.click(screen.getByRole("radio", { name: "Transcript" }));
    await screen.findByText("We agreed to activate Sortformer.");
    fireEvent.click(screen.getByRole("button", { name: "Return to list" }));
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("recovers from an initial note load failure without leaving the detail page", async () => {
    const note = await noteStoreMock.loadNoteById();
    noteStoreMock.loadNoteById
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(note);
    renderEditor();
    expect(await screen.findByText("offline")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload note" }));
    await waitFor(() =>
      expect(screen.getByText("Minutes only.")).toBeInTheDocument(),
    );
  });

  it("keeps edits after a failed save and enables delivery only after saving", async () => {
    const note = await noteStoreMock.loadNoteById();
    noteStoreMock.updateNote
      .mockRejectedValueOnce(new Error("Save unavailable"))
      .mockResolvedValueOnce({ ...note, title: "Updated meeting" });
    renderEditor();
    await screen.findByText("Minutes only.");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const title = screen.getByRole("textbox", { name: "Meeting title" });
    fireEvent.change(title, { target: { value: "Updated meeting" } });
    expect(screen.getByRole("button", { name: "发布到飞书" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Save unavailable",
    );
    expect(title).toHaveValue("Updated meeting");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Save" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "发布到飞书" })).toBeEnabled();
  });

  it("retries only the failed transcript load and keeps the summary and shared player", async () => {
    let failed = false;
    apiMock.apiJson.mockImplementation((path: string) => {
      if (path.endsWith('/recording')) return Promise.resolve({ available: true, deleted: false, can_delete: false, filename: 'sample.webm', size_bytes: 1000 });
      if (path.endsWith("/transcript") && !failed) {
        failed = true;
        return Promise.reject(new Error("offline"));
      }
      return Promise.resolve(transcriptEvidence);
    });
    renderEditor("/note/note-1?view=transcript");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Transcript failed to load: offline",
    );
    const audio = screen.getByTestId("source-audio");
    fireEvent.click(screen.getByRole("button", { name: "Reload transcript" }));
    expect(
      await screen.findByText("We agreed to activate Sortformer."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("source-audio")).toBe(audio);
    fireEvent.click(screen.getByRole("radio", { name: "Summary" }));
    expect(await screen.findByText("Minutes only.")).toBeInTheDocument();
  });

  it("requires confirmation and returns to the library only after deletion succeeds", async () => {
    renderEditor();
    await screen.findByText(/Minutes only/);
    await openDeleteAction();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(noteStoreMock.deleteNote).not.toHaveBeenCalled();
    await openDeleteAction();
    fireEvent.click(screen.getByRole("button", { name: "Confirm deletion" }));
    expect(await screen.findByText("Notes")).toBeInTheDocument();
    expect(useWorkspaceStore.getState().changeDeleted).toHaveBeenCalledWith("note-1", true);
    expect(noteStoreMock.deleteNote).not.toHaveBeenCalled();
  });

  it("keeps the note open when deletion fails", async () => {
    useWorkspaceStore.setState({ changeDeleted: vi.fn().mockRejectedValue(new Error("Access denied")) });
    renderEditor();
    await screen.findByText(/Minutes only/);
    await openDeleteAction();
    fireEvent.click(screen.getByRole("button", { name: "Confirm deletion" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Access denied");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("keeps summary and transcript separate while sharing one audio player", async () => {
    renderEditor();

    await waitFor(() =>
      expect(screen.getByText("Minutes only.")).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("source-audio")).toHaveLength(1);
    expect(
      screen.queryByText("We agreed to activate Sortformer."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Transcript" }));

    expect(
      await screen.findByText("We agreed to activate Sortformer."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Transcription model · sensevoice-small"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("source-audio")).toHaveLength(1);
    expect(screen.queryByDisplayValue(/Minutes only/)).not.toBeInTheDocument();
  });

  it("toggles raw evidence, seeks playback, follows time and saves speaker aliases", async () => {
    renderEditor("/note/note-1?view=transcript");
    const cleanedTurn = await screen.findByText(
      "We agreed to activate Sortformer.",
    );
    const audio = screen.getByTestId("source-audio") as HTMLAudioElement;

    fireEvent.click(cleanedTurn);
    expect(audio.currentTime).toBe(62);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Show raw ASR" }));
    expect(
      await screen.findByText("We agree to active Sort former."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rename speaker_01" }));
    fireEvent.change(screen.getByLabelText("Rename speaker_01"), {
      target: { value: "Susan Wang" },
    });
    fireEvent.click(screen.getByTitle("Save speaker name"));
    expect(await screen.findByText("Susan Wang")).toBeInTheDocument();

    audio.currentTime = 63;
    fireEvent.timeUpdate(audio);
    await waitFor(() => {
      expect(
        screen.getByText("We agree to active Sort former.").closest("button"),
      ).toHaveAttribute("aria-current", "true");
    });
  });

  it("previews saved Markdown and includes transcript evidence only when explicitly selected", async () => {
    const createObjectUrl = URL.createObjectURL;
    const revokeObjectUrl = URL.revokeObjectURL;
    const createUrl = vi.fn((_blob: Blob) => "blob:export");
    const revokeUrl = vi.fn();
    URL.createObjectURL = createUrl as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeUrl as typeof URL.revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    try {
      renderEditor("/note/note-1?view=transcript");
      await screen.findByText("We agreed to activate Sortformer.");
      openContentActions();
      fireEvent.click(screen.getByRole("button", { name: "导出 Markdown" }));
      const preview = screen.getByRole("dialog").querySelector("pre")!;
      expect(preview).toHaveTextContent("Minutes only.");
      expect(preview).not.toHaveTextContent(
        "We agreed to activate Sortformer.",
      );
      expect(createUrl).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("checkbox", { name: "附带逐字稿" }));
      expect(preview).toHaveTextContent("We agreed to activate Sortformer.");
      expect(preview).toHaveTextContent("Minutes only.");
      const expectedPayload = preview.textContent;

      vi.useFakeTimers();
      fireEvent.click(screen.getByRole("button", { name: "下载 Markdown" }));
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(clickSpy.mock.instances[0]?.download).toBe(
        "Meeting note-保存于 2026-07-01T00_00_00Z.md",
      );
      vi.advanceTimersByTime(1000);
      expect(revokeUrl).toHaveBeenCalledWith("blob:export");
      vi.useRealTimers();
      const blob = createUrl.mock.calls[0][0];
      expect(blob.type).toBe("text/markdown;charset=utf-8");
      const downloaded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(blob);
      });
      expect(downloaded).toBe(expectedPayload);
    } finally {
      vi.useRealTimers();
      URL.createObjectURL = createObjectUrl;
      URL.revokeObjectURL = revokeObjectUrl;
      clickSpy.mockRestore();
    }
  });

  it("plays a retained video-link audio track as audio without meeting recording actions", async () => {
    noteStoreMock.loadNoteById.mockResolvedValue({
      id: "note-1", title: "Video link", content: "# Audio-track summary",
      sourceType: "video", mediaKind: "audio", videoUrl: "https://www.bilibili.com/video/BV1234567890/",
      taskId: "task-1", status: "done", scope: "personal",
      createdAt: "2026-07-01T00:00:00Z", updatedAt: "2026-07-01T00:00:00Z",
    });
    renderEditor("/note/note-1?view=transcript");
    const turn = await screen.findByText("We agreed to activate Sortformer.");
    const audio = screen.getByTestId("source-audio") as HTMLAudioElement;
    expect(audio).toHaveAttribute('src', '/api/notes/note-1/media');
    expect(screen.queryByTestId("source-video")).not.toBeInTheDocument();
    expect(screen.queryByText("从笔记跳回录制现场")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", "https://www.bilibili.com/video/BV1234567890/");
    expect(apiMock.apiJson.mock.calls.some(([path]) => String(path).endsWith('/recording'))).toBe(false);
    fireEvent.click(turn);
    expect(audio.currentTime).toBe(62);
  });

  it('exposes the exact processing task as a read-only entrance while preserving detail return context', async () => {
    renderEditor('/note/note-1?view=transcript&returnTo=%2Fnotes%3Fq%3Dreview');
    await screen.findByText('We agreed to activate Sortformer.');
    openContentActions();
    const link = screen.getByRole('link', { name: 'View processing task' });
    const target = new URL(link.getAttribute('href')!, 'https://example.invalid');
    expect(target.searchParams.get('task')).toBe('task-1');
    expect(target.searchParams.get('meeting')).toBe('1');
    expect(target.searchParams.get('returnTo')).toContain('/note/note-1?');
    expect(target.searchParams.get('returnTo')).toContain('view=transcript');
    expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('uses the playback derivative for video only and reloads the same element at its retained position/rate', async () => {
    noteStoreMock.loadNoteById.mockResolvedValue({ id: 'note-1', title: 'Video', content: '# Review', sourceType: 'video', mediaKind: 'video', taskId: 'task-1', status: 'done', scope: 'personal', createdAt: '2026-07-01T00:00:00Z', updatedAt: '2026-07-01T00:00:00Z' });
    renderEditor();
    const video = await screen.findByTestId('source-video') as HTMLVideoElement;
    expect(video.getAttribute('src')).toBe('/api/notes/note-1/media?playback=true');
    video.currentTime = 93;
    video.playbackRate = 1.5;
    fireEvent.timeUpdate(video);
    apiMock.apiFetch.mockResolvedValueOnce(new Response(null, { status: 503, headers: { 'Retry-After': '2' } }));
    fireEvent.error(video);
    expect(await screen.findByRole('button', { name: 'Reload video' })).toBeEnabled();
    expect(screen.getByRole('alert')).not.toHaveTextContent(/deleted|removed|not found/i);
    fireEvent.click(screen.getByRole('button', { name: 'Reload video' }));
    expect(screen.getByTestId('source-video')).toBe(video);
    expect(video.load).toHaveBeenCalled();
    video.currentTime = 0;
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(93);
    expect(video.playbackRate).toBe(1.5);
    fireEvent.canPlay(video);
    expect(screen.queryByRole('button', { name: 'Reload video' })).toBeNull();
    expect(noteStoreMock.loadNoteById).toHaveBeenCalledTimes(1);
    expect(apiMock.apiFetch).toHaveBeenCalledWith('/api/notes/note-1/media?playback=true', expect.objectContaining({ headers: { Range: 'bytes=0-0' } }));
  });

  it.each([404, 500, 401])('distinguishes media HTTP %s without replacing the note or restarting generation', async status => {
    apiMock.apiFetch.mockResolvedValueOnce(new Response(null, { status }));
    renderEditor();
    const audio = await screen.findByTestId('source-audio');
    fireEvent.error(audio);
    const reload = await screen.findByRole('button', { name: 'Reload audio' });
    expect(reload).toBeEnabled();
    const message = reload.closest('[role="alert"]')!.textContent;
    if (status === 404) expect(message).toMatch(/unavailable/i);
    else expect(message).not.toMatch(/removed|deleted|missing|not found/i);
    if (status === 401) expect(message).toMatch(/sign in|permission/i);
    expect(await screen.findByText('Minutes only.')).toBeVisible();
    expect(screen.getByTestId('source-audio')).toBe(audio);
    expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it("keeps one shared local video player available from the transcript view", async () => {
    noteStoreMock.loadNoteById.mockResolvedValue({
      id: "note-1",
      title: "Video note",
      content: "# Video summary",
      sourceType: "video",
      taskId: "task-1",
      status: "done",
      scope: "personal",
      createdAt: "2026-07-01T00:00:00Z",
      updatedAt: "2026-07-01T00:00:00Z",
    });

    renderEditor("/note/note-1?view=transcript");
    const turn = await screen.findByText("We agreed to activate Sortformer.");
    const video = screen.getByTestId("source-video") as HTMLVideoElement;

    fireEvent.click(turn);

    expect(screen.getAllByTestId("source-video")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Source video" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Meeting video" })).not.toBeInTheDocument();
    expect(apiMock.apiJson.mock.calls.some(([path]) => String(path).endsWith('/recording'))).toBe(false);
    expect(video.currentTime).toBe(62);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Expand video" }));
    expect(screen.getByTestId("source-video")).toBe(video);
    expect(
      screen.getByRole("button", { name: "Back to notes" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(video.currentTime).toBe(62);
    fireEvent.click(screen.getByRole("button", { name: "Back to notes" }));
    expect(screen.getByTestId("source-video")).toBe(video);
    expect(video.currentTime).toBe(62);
  });
});
