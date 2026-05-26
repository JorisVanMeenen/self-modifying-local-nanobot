import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceProjectDialog } from "@/components/WorkspaceProjectDialog";
import type { WorkspaceScopePayload } from "@/lib/types";

const DEFAULT_SCOPE: WorkspaceScopePayload = {
  project_path: "/Users/test/.nanobot/workspace",
  project_name: "workspace",
  access_mode: "restricted",
  restrict_to_workspace: true,
};

function renderDialog(overrides: Partial<Parameters<typeof WorkspaceProjectDialog>[0]> = {}) {
  const onApply = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <WorkspaceProjectDialog
      open
      scope={DEFAULT_SCOPE}
      defaultScope={DEFAULT_SCOPE}
      recentProjects={[{ project_path: "/Users/test/project-alpha", project_name: "project-alpha" }]}
      disabled={false}
      onOpenChange={onOpenChange}
      onApply={onApply}
      {...overrides}
    />,
  );
  return { onApply, onOpenChange };
}

describe("WorkspaceProjectDialog", () => {
  it("shows default and recent projects in a centered dialog", () => {
    renderDialog();

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(screen.getByText("Default workspace")).toBeInTheDocument();
    expect(screen.getByText("project-alpha")).toBeInTheDocument();
  });

  it("applies project changes without changing access mode", () => {
    const { onApply } = renderDialog();

    fireEvent.click(screen.getByText("project-alpha"));

    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      project_path: "/Users/test/project-alpha",
      access_mode: DEFAULT_SCOPE.access_mode,
      restrict_to_workspace: DEFAULT_SCOPE.restrict_to_workspace,
    }));
  });

  it("keeps manual paths honest before sending them to the gateway", () => {
    const { onApply } = renderDialog();

    fireEvent.click(screen.getByText("Paste path"));
    fireEvent.change(screen.getByPlaceholderText("/Users/name/project"), {
      target: { value: "relative/project" },
    });
    fireEvent.click(screen.getByText("Use Path"));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter an absolute folder path on this machine.",
    );
    expect(onApply).not.toHaveBeenCalled();
  });

  it("surfaces gateway rejections inline", () => {
    renderDialog({
      serverError: "Nanobot kept the previous workspace.",
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Nanobot kept the previous workspace.");
  });
});
