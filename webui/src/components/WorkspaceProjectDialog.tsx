import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Check, ChevronDown, Folder, Keyboard, Shield } from "lucide-react";
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
import type { WorkspaceAccessMode, WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

interface WorkspaceProjectDialogProps {
  open: boolean;
  scope: WorkspaceScopePayload | null;
  defaultScope: WorkspaceScopePayload | null;
  recentProjects: WorkspacesPayload["recent_projects"];
  canUseFullAccess: boolean;
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
  canUseFullAccess,
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
    mode: WorkspaceAccessMode = accessMode,
  ) => {
    if (!projectPath.trim() || !isAbsolutePath(projectPath)) {
      setError(t("workspace.dialog.absolutePathRequired"));
      return;
    }
    onApply({
      project_path: projectPath.trim(),
      project_name: projectName || projectNameFromPath(projectPath),
      access_mode: mode,
      restrict_to_workspace: mode === "restricted",
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[480px] rounded-[28px] border-border/55 bg-card/96 p-0 shadow-[0_28px_90px_rgba(15,23,42,0.20)] backdrop-blur-xl dark:border-white/10">
        <DialogHeader className="px-5 pb-3 pt-5 text-left">
          <DialogTitle className="text-[17px] font-semibold tracking-[-0.01em]">
            {t("workspace.dialog.title")}
          </DialogTitle>
          <DialogDescription className="max-w-[25rem] text-[12.5px] leading-5">
            {t("workspace.dialog.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 px-5 pb-5">
          <section className="overflow-hidden rounded-[20px] border border-border/50 bg-background/72">
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
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[13px] bg-muted/60 text-foreground/82">
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

          <section className="rounded-[20px] border border-border/50 bg-background/72 p-1.5">
            <div className="mb-1 flex items-center justify-between px-2 py-1">
              <span className="text-[12px] font-medium text-muted-foreground">
                {t("workspace.dialog.access")}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <AccessButton
                active={accessMode === "restricted"}
                disabled={disabled}
                title={t("thread.composer.workspace.restricted")}
                description={t("thread.composer.workspace.restrictedDescription")}
                icon={<Shield className="h-4 w-4" />}
                onClick={() => current && onApply({ ...current, access_mode: "restricted", restrict_to_workspace: true })}
              />
              <AccessButton
                active={accessMode === "full"}
                disabled={!canUseFullAccess || disabled}
                warning
                title={t("thread.composer.workspace.full")}
                description={t("thread.composer.workspace.fullDescription")}
                icon={<AlertTriangle className="h-4 w-4" />}
                onClick={() => current && onApply({ ...current, access_mode: "full", restrict_to_workspace: false })}
              />
            </div>
          </section>

          <section className="overflow-hidden rounded-[20px] border border-border/50 bg-background/72">
            <button
              type="button"
              disabled={disabled}
              onClick={() => setManualOpen((value) => !value)}
              className="flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-muted/40 disabled:pointer-events-none disabled:opacity-60"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[13px] bg-muted/60 text-foreground/82">
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
                  className="h-10 rounded-full border-border/55 bg-card/80 px-4"
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

function AccessButton({
  active,
  disabled,
  warning,
  title,
  description,
  icon,
  onClick,
}: {
  active: boolean;
  disabled?: boolean;
  warning?: boolean;
  title: string;
  description: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex min-h-12 items-center gap-2 rounded-[15px] px-3 py-2 text-left",
        "transition-colors hover:bg-muted/45 disabled:pointer-events-none disabled:opacity-55",
        active
          ? warning
            ? "bg-orange-50 text-orange-700 shadow-[inset_0_0_0_1px_rgba(251,146,60,0.38)] dark:bg-orange-950/20 dark:text-orange-300"
            : "bg-muted text-foreground shadow-[inset_0_0_0_1px_rgba(15,23,42,0.04)]"
          : "text-foreground/86",
      )}
    >
      <span
        className={cn(
          "grid h-7 w-7 shrink-0 place-items-center rounded-[10px]",
          warning ? "bg-orange-500/10" : "bg-muted/65",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-semibold">{title}</span>
        <span className="mt-0.5 hidden text-[11.5px] leading-4 text-muted-foreground sm:block">
          {description}
        </span>
      </span>
    </button>
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
