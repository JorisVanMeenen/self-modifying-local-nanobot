import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import type { ChatSummary } from "@/lib/types";

function session(overrides: Partial<ChatSummary>): ChatSummary {
  const chatId = overrides.chatId ?? "chat";
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: "2026-05-20T10:00:00Z",
    updatedAt: "2026-05-20T10:00:00Z",
    preview: "",
    ...overrides,
  };
}

describe("ChatList", () => {
  it("groups WebUI chats by workspace project while preserving in-project sorting and activity", () => {
    const sessions = [
      session({
        chatId: "zeta",
        title: "Zeta task",
        updatedAt: "2026-05-20T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "alpha",
        title: "Alpha task",
        updatedAt: "2026-05-20T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "bench",
        title: "Bench task",
        updatedAt: "2026-05-21T09:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot-bench",
          project_name: "nanobot-bench",
          access_mode: "full",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:alpha"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        sort="title_asc"
        showTimestamps
        runningChatIds={["zeta"]}
      />,
    );

    const nanobotSection = screen.getByRole("region", { name: "nanobot" });
    const nanobotText = nanobotSection.textContent ?? "";

    expect(screen.getByRole("region", { name: "nanobot-bench" })).toBeInTheDocument();
    expect(within(nanobotSection).getByText("Alpha task")).toBeInTheDocument();
    expect(within(nanobotSection).getByText("Zeta task")).toBeInTheDocument();
    expect(nanobotText.indexOf("Alpha task")).toBeLessThan(nanobotText.indexOf("Zeta task"));
    expect(within(nanobotSection).getByLabelText("Agent running")).toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });
});
