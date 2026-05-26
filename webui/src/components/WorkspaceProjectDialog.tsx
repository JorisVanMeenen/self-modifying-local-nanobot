import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, Folder, Keyboard } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

interface WorkspaceProjectDialogProps {
  open: boolean;
  scope: WorkspaceScopePayload | null;
  defaultScope: WorkspaceScopePayload | null;
  recentProjects: WorkspacesPayload["recent_projects"];
  disabled?: boolean;
  serverError?: string | null;
  onOpenChange: (open: boolean) => void;
  onApply: (scope: WorkspaceScopePayload) => void;
}

export function WorkspaceProjectDialog({
  open,
  scope,
  defaultScope,
  recentProjects,
  disabled = false,
  serverError = null,
  onOpenChange,
  onApply,
}: WorkspaceProjectDialogProps) {
  const { t } = useTranslation();
  const hasExplicitScope = scope !== null;
  const current = scope ?? defaultScope;
  const [manualPath, setManualPath] = useState(current?.project_path ?? "");
  const [manualOpen, setManualOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accessMode = current?.access_mode ?? "restricted";

  useEffect(() => {
    if (!open) return;
    setManualPath(current?.project_path ?? "");
    setManualOpen(false);
    setError(null);
  }, [current?.project_path, open]);

  const projects = useMemo(() => {
    const seen = new Set<string>();
    const rows: Array<{ project_path: string; project_name?: string; kind: "default" | "recent" }> = [];
    if (defaultScope) {
      rows.push({
        project_path: defaultScope.project_path,
        project_name: defaultScope.project_name,
        kind: "default",
      });
      seen.add(defaultScope.project_path);
    }
    for (const project of recentProjects) {
      if (seen.has(project.project_path)) continue;
      seen.add(project.project_path);
      rows.push({ ...project, kind: "recent" });
    }
    return rows.slice(0, 8);
  }, [defaultScope, recentProjects]);

  const applyProject = (
    projectPath: string,
    projectName?: string,
  ) => {
    if (!projectPath.trim() || !isAbsolutePath(projectPath)) {
      setError(t("workspace.dialog.absolutePathRequired"));
      return;
    }
    onApply({
      project_path: projectPath.trim(),
      project_name: projectName || projectNameFromPath(projectPath),
      access_mode: accessMode,
      restrict_to_workspace: accessMode === "restricted",
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[430px] rounded-[26px] border-border/55 bg-background p-0 shadow-[0_24px_80px_rgba(15,23,42,0.20)] dark:border-white/10">
        <DialogHeader className="px-5 pb-2 pt-5 text-left">
          <DialogTitle className="text-[17px] font-semibold tracking-[-0.01em]">
            {t("workspace.dialog.title")}
          </DialogTitle>
          <DialogDescription className="max-w-[22rem] text-[12.5px] leading-5">
            {t("workspace.dialog.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2.5 px-5 pb-5">
          <section className="overflow-hidden rounded-[18px] border border-border/50 bg-card">
            {projects.map((project) => {
              const selected = hasExplicitScope && current?.project_path === project.project_path;
              return (
                <button
                  key={`${project.kind}:${project.project_path}`}
                  type="button"
                  disabled={disabled}
                  onClick={() => applyProject(project.project_path, project.project_name)}
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border/45 px-3.5 py-3 text-left last:border-b-0",
                    "transition-colors hover:bg-muted/40 disabled:pointer-events-none disabled:opacity-60",
                  )}
                >
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[13px] bg-muted text-foreground/82">
                    <Folder className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-semibold tracking-[-0.01em]">
                      {project.project_name || projectNameFromPath(project.project_path)}
                    </span>
                    <span className="block truncate text-[12.5px] text-muted-foreground">
                      {project.kind === "default"
                        ? t("workspace.dialog.defaultProject")
                        : shortPath(project.project_path)}
                    </span>
                  </span>
                  {selected ? <Check className="h-4 w-4 text-primary" /> : null}
                </button>
              );
            })}
          </section>

          <section className="overflow-hidden rounded-[18px] border border-border/50 bg-card">
            <button
              type="button"
              disabled={disabled}
              onClick={() => setManualOpen((value) => !value)}
              className="flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-muted/40 disabled:pointer-events-none disabled:opacity-60"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[13px] bg-muted text-foreground/82">
                <Keyboard className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-semibold tracking-[-0.01em]">
                  {t("workspace.dialog.manual")}
                </span>
                <span className="block truncate text-[12.5px] text-muted-foreground">
                  {manualPath ? shortPath(manualPath) : t("workspace.dialog.manualPlaceholder")}
                </span>
              </span>
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform",
                  manualOpen && "rotate-180",
                )}
              />
            </button>

            {manualOpen ? (
              <div className="flex flex-col gap-2 border-t border-border/45 px-3.5 pb-3 pt-2 sm:flex-row">
                <Input
                  value={manualPath}
                  onChange={(event) => {
                    setManualPath(event.target.value);
                    setError(null);
                  }}
                  disabled={disabled}
                  placeholder={t("workspace.dialog.manualPlaceholder")}
                  className="h-10 rounded-full border-border/55 bg-background px-4"
                />
                <Button
                  type="button"
                  disabled={disabled || !manualPath.trim()}
                  onClick={() => applyProject(manualPath)}
                  className="h-10 rounded-full px-4"
                >
                  {t("workspace.dialog.usePath")}
                </Button>
              </div>
            ) : null}
          </section>

          {error || serverError ? (
            <p className="px-1 text-[12px] font-medium text-destructive" role="alert">
              {error ?? serverError}
            </p>
          ) : null}
        </div>

        <DialogFooter className="border-t border-border/40 px-5 py-3.5">
          <Button
            type="button"
            variant="ghost"
            className="h-9 rounded-full px-4"
            onClick={() => onOpenChange(false)}
          >
            {t("workspace.dialog.done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
function isAbsolutePath(path: string): boolean {
  const trimmed = path.trim();
  return trimmed.startsWith("/") || /^[A-Za-z]:[\\/]/.test(trimmed);
}

function projectNameFromPath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() || path;
}

function shortPath(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 3) return path;
  return `…/${parts.slice(-3).join("/")}`;
}
