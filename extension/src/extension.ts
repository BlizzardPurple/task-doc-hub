import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

const DOC_ROOT = path.join(os.homedir(), "Nrepos", ".task-docs");

// ── Tree items ───────────────────────────────────────

type NodeKind = "task" | "folder" | "file";

class DocHubItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly kind: NodeKind,
    public readonly fsPath: string,
    public readonly collapsible: vscode.TreeItemCollapsibleState
  ) {
    super(label, collapsible);
    this.tooltip = fsPath;
    this.contextValue = kind;

    if (kind === "file") {
      this.command = {
        command: "docHub.openFile",
        title: "Open",
        arguments: [vscode.Uri.file(fsPath)],
      };
      this.iconPath = this.fileIcon(fsPath);
    } else if (kind === "task") {
      this.iconPath = new vscode.ThemeIcon("notebook");
      this.description = this.taskStatus(fsPath);
    } else {
      this.iconPath = vscode.ThemeIcon.Folder;
    }
  }

  private fileIcon(filePath: string): vscode.ThemeIcon {
    const ext = path.extname(filePath).toLowerCase();
    if ([".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff"].includes(ext)) {
      return new vscode.ThemeIcon("file-media");
    }
    if ([".mov", ".mp4", ".webm", ".mkv", ".avi"].includes(ext)) {
      return new vscode.ThemeIcon("play-circle");
    }
    if (ext === ".md") {
      return new vscode.ThemeIcon("markdown");
    }
    return vscode.ThemeIcon.File;
  }

  private taskStatus(taskDir: string): string {
    const indexPath = path.join(taskDir, "index.md");
    try {
      const text = fs.readFileSync(indexPath, "utf-8");
      const match = text.match(/^status:\s*(.+)$/m);
      return match ? match[1].trim() : "";
    } catch {
      return "";
    }
  }
}

// ── Tree provider ────────────────────────────────────

class DocHubTreeProvider implements vscode.TreeDataProvider<DocHubItem> {
  private _onDidChange = new vscode.EventEmitter<
    DocHubItem | undefined | null | void
  >();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(el: DocHubItem): vscode.TreeItem {
    return el;
  }

  getChildren(el?: DocHubItem): DocHubItem[] {
    if (!el) {
      return this.getTasks();
    }
    if (el.kind === "task" || el.kind === "folder") {
      return this.getDirectoryContents(el.fsPath);
    }
    return [];
  }

  private getTasks(): DocHubItem[] {
    if (!fs.existsSync(DOC_ROOT)) {
      return [];
    }
    const entries = fs.readdirSync(DOC_ROOT, { withFileTypes: true });
    return entries
      .filter((e) => e.isDirectory() && !e.name.startsWith("_"))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(
        (e) =>
          new DocHubItem(
            e.name,
            "task",
            path.join(DOC_ROOT, e.name),
            vscode.TreeItemCollapsibleState.Collapsed
          )
      );
  }

  private getDirectoryContents(dirPath: string): DocHubItem[] {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    const items: DocHubItem[] = [];

    // Folders first, then files
    const folders = entries
      .filter((e) => e.isDirectory())
      .sort((a, b) => a.name.localeCompare(b.name));
    const files = entries
      .filter((e) => e.isFile() && e.name !== ".gitkeep")
      .sort((a, b) => a.name.localeCompare(b.name));

    for (const f of folders) {
      items.push(
        new DocHubItem(
          f.name,
          "folder",
          path.join(dirPath, f.name),
          vscode.TreeItemCollapsibleState.Collapsed
        )
      );
    }
    for (const f of files) {
      items.push(
        new DocHubItem(
          f.name,
          "file",
          path.join(dirPath, f.name),
          vscode.TreeItemCollapsibleState.None
        )
      );
    }
    return items;
  }
}

// ── Extension activation ─────────────────────────────

export function activate(context: vscode.ExtensionContext) {
  const provider = new DocHubTreeProvider();

  const treeView = vscode.window.createTreeView("docHubLibrary", {
    treeDataProvider: provider,
    showCollapseAll: true,
  });

  context.subscriptions.push(
    treeView,
    vscode.commands.registerCommand("docHub.refresh", () => provider.refresh()),
    vscode.commands.registerCommand("docHub.openFile", (uri: vscode.Uri) => {
      vscode.commands.executeCommand("vscode.open", uri);
    }),
    vscode.commands.registerCommand(
      "docHub.revealInFinder",
      (item: DocHubItem) => {
        vscode.commands.executeCommand(
          "revealFileInOS",
          vscode.Uri.file(item.fsPath)
        );
      }
    )
  );

  // Auto-refresh when files change in the doc root
  const watcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(vscode.Uri.file(DOC_ROOT), "**/*")
  );
  watcher.onDidCreate(() => provider.refresh());
  watcher.onDidDelete(() => provider.refresh());
  watcher.onDidChange(() => provider.refresh());
  context.subscriptions.push(watcher);
}

export function deactivate() {}
