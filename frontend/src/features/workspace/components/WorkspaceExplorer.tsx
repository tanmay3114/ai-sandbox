import { useState } from "react";
import {
  AlertCircle,
  FileCode,
  Folder,
  FolderPlus,
  FilePlus,
  RefreshCw,
  Trash2,
  HardDrive,
  FileText,
  ChevronRight,
  Database,
} from "lucide-react";
import {
  useWorkspaceFiles,
  useWorkspaceFileContent,
  useWriteWorkspaceFile,
  useCreateWorkspaceDirectory,
  useDeleteWorkspaceFile,
} from "@/lib/api/queries";
import type { FileInfo } from "@/types";

interface WorkspaceExplorerProps {
  sandboxId: string;
  isSandboxRunning?: boolean;
}

export function WorkspaceExplorer({
  sandboxId,
  isSandboxRunning = true,
}: WorkspaceExplorerProps) {
  const [currentPath, setCurrentPath] = useState<string>("");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  // Editor state
  const [editorContent, setEditorContent] = useState<string>("");
  const [isEditorDirty, setIsEditorDirty] = useState<boolean>(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Creation dialogs state
  const [showNewFileDialog, setShowNewFileDialog] = useState<boolean>(false);
  const [newFileName, setNewFileName] = useState<string>("");
  const [showNewFolderDialog, setShowNewFolderDialog] = useState<boolean>(false);
  const [newFolderName, setNewFolderName] = useState<string>("");

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<FileInfo | null>(null);

  // TanStack queries & mutations
  const {
    data: fileList,
    isLoading: isFileListLoading,
    isError: isFileListError,
    refetch: refetchFiles,
    isFetching: isFilesFetching,
  } = useWorkspaceFiles(sandboxId, currentPath);

  const {
    data: activeFileContent,
    isLoading: isContentLoading,
    isError: isContentError,
    refetch: refetchContent,
  } = useWorkspaceFileContent(sandboxId, selectedFilePath ?? "");

  const writeMutation = useWriteWorkspaceFile(sandboxId);
  const createDirMutation = useCreateWorkspaceDirectory(sandboxId);
  const deleteMutation = useDeleteWorkspaceFile(sandboxId);

  // Handle file selection
  const handleSelectFile = (file: FileInfo) => {
    if (file.is_directory) {
      setCurrentPath(file.path);
      setSelectedFilePath(null);
      setIsEditorDirty(false);
      return;
    }

    if (isEditorDirty) {
      const confirmDiscard = window.confirm(
        "You have unsaved changes in the editor. Discard and switch file?"
      );
      if (!confirmDiscard) return;
    }

    setSelectedFilePath(file.path);
    setIsEditorDirty(false);
    setSaveSuccessMsg(null);
    setActionError(null);
  };

  // Synchronize editor buffer when query returns fresh file content
  const currentEncoding = activeFileContent?.encoding ?? "utf-8";
  const isBinary = currentEncoding === "base64";

  // When activeFileContent updates and user hasn't dirtied editor
  const displayContent = isEditorDirty
    ? editorContent
    : activeFileContent?.content ?? "";

  const handleEditorChange = (val: string) => {
    setEditorContent(val);
    setIsEditorDirty(true);
    setSaveSuccessMsg(null);
  };

  // Save modified text file
  const handleSaveFile = () => {
    if (!selectedFilePath || isBinary) return;
    setActionError(null);
    setSaveSuccessMsg(null);

    writeMutation.mutate(
      {
        path: selectedFilePath,
        content: isEditorDirty ? editorContent : displayContent,
        encoding: "utf-8",
      },
      {
        onSuccess: () => {
          setIsEditorDirty(false);
          setSaveSuccessMsg("File saved successfully.");
          setTimeout(() => setSaveSuccessMsg(null), 3000);
        },
        onError: (err: any) => {
          const detail =
            err?.response?.data?.message ||
            err?.response?.data?.detail ||
            "Failed to save file. Check path length and workspace quota limits.";
          setActionError(typeof detail === "string" ? detail : "Save failed.");
        },
      }
    );
  };

  // Create file
  const handleCreateFile = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newFileName.trim();
    if (!trimmed) return;

    const fullPath = currentPath ? `${currentPath}/${trimmed}` : trimmed;
    setActionError(null);

    writeMutation.mutate(
      {
        path: fullPath,
        content: "",
        encoding: "utf-8",
      },
      {
        onSuccess: () => {
          setNewFileName("");
          setShowNewFileDialog(false);
          setSelectedFilePath(fullPath);
          setEditorContent("");
          setIsEditorDirty(false);
          refetchFiles();
        },
        onError: (err: any) => {
          const detail =
            err?.response?.data?.message ||
            err?.response?.data?.detail ||
            "Unable to create file. Ensure path is valid and within limits.";
          setActionError(typeof detail === "string" ? detail : "Creation failed.");
        },
      }
    );
  };

  // Create folder
  const handleCreateFolder = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newFolderName.trim();
    if (!trimmed) return;

    const fullPath = currentPath ? `${currentPath}/${trimmed}` : trimmed;
    setActionError(null);

    createDirMutation.mutate(
      { path: fullPath },
      {
        onSuccess: () => {
          setNewFolderName("");
          setShowNewFolderDialog(false);
          refetchFiles();
        },
        onError: (err: any) => {
          const detail =
            err?.response?.data?.message ||
            err?.response?.data?.detail ||
            "Unable to create directory. Ensure path is valid.";
          setActionError(typeof detail === "string" ? detail : "Directory creation failed.");
        },
      }
    );
  };

  // Delete target confirmation execution
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    setActionError(null);

    deleteMutation.mutate(deleteTarget.path, {
      onSuccess: () => {
        if (selectedFilePath === deleteTarget.path) {
          setSelectedFilePath(null);
          setIsEditorDirty(false);
        }
        setDeleteTarget(null);
        refetchFiles();
      },
      onError: (err: any) => {
        const detail =
          err?.response?.data?.message ||
          err?.response?.data?.detail ||
          "Unable to delete item. Note that directories must be empty before deletion.";
        setActionError(typeof detail === "string" ? detail : "Deletion failed.");
        setDeleteTarget(null);
      },
    });
  };

  // Navigation helpers
  const pathSegments = currentPath ? currentPath.split("/") : [];

  const navigateToSegment = (index: number) => {
    if (index === -1) {
      setCurrentPath("");
    } else {
      setCurrentPath(pathSegments.slice(0, index + 1).join("/"));
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        marginBottom: 24,
      }}
    >
      {/* Workspace Header & Quota Information */}
      <div
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--color-border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <HardDrive size={18} color="var(--color-accent)" />
            <h3
              style={{
                margin: 0,
                fontSize: 15,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              Persistent Workspace
            </h3>
          </div>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 12,
              color: "var(--color-text-muted)",
            }}
          >
            Dedicated volume mounted into executions at <code>/workspace</code>.
          </p>
        </div>

        {/* Quota & Stats Indicators */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {fileList && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                fontSize: 12,
                color: "var(--color-text-muted)",
                backgroundColor: "var(--color-surface-2)",
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid var(--color-border-subtle)",
              }}
            >
              <span>
                Files: <strong>{fileList.total_count}</strong> / 1,000 max
              </span>
              <span>•</span>
              <span>
                Usage: <strong>{formatBytes(fileList.total_size_bytes)}</strong> / 50 MiB limit
              </span>
            </div>
          )}

          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              onClick={() => refetchFiles()}
              disabled={isFilesFetching}
              title="Refresh workspace files"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 10px",
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-2)",
                color: "var(--color-text-secondary)",
                fontSize: 12,
                cursor: isFilesFetching ? "not-allowed" : "pointer",
              }}
            >
              <RefreshCw
                size={13}
                style={{
                  animation: isFilesFetching ? "spin 1s linear infinite" : "none",
                }}
              />
              Refresh
            </button>

            <button
              type="button"
              onClick={() => {
                setShowNewFileDialog(true);
                setShowNewFolderDialog(false);
              }}
              disabled={!isSandboxRunning}
              title={
                !isSandboxRunning
                  ? "Sandbox must be in running state to create files"
                  : "Create new file"
              }
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 10px",
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-2)",
                color: isSandboxRunning ? "var(--color-text-primary)" : "var(--color-text-muted)",
                fontSize: 12,
                fontWeight: 500,
                cursor: !isSandboxRunning ? "not-allowed" : "pointer",
              }}
            >
              <FilePlus size={13} color="var(--color-accent)" />
              New File
            </button>

            <button
              type="button"
              onClick={() => {
                setShowNewFolderDialog(true);
                setShowNewFileDialog(false);
              }}
              disabled={!isSandboxRunning}
              title={
                !isSandboxRunning
                  ? "Sandbox must be in running state to create directories"
                  : "Create new directory"
              }
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 10px",
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-2)",
                color: isSandboxRunning ? "var(--color-text-primary)" : "var(--color-text-muted)",
                fontSize: 12,
                fontWeight: 500,
                cursor: !isSandboxRunning ? "not-allowed" : "pointer",
              }}
            >
              <FolderPlus size={13} color="var(--color-accent)" />
              New Folder
            </button>
          </div>
        </div>
      </div>

      {/* Action / Error Banner */}
      {actionError && (
        <div
          style={{
            margin: "12px 16px 0",
            padding: "8px 12px",
            borderRadius: 6,
            backgroundColor: "var(--color-danger-subtle)",
            border: "1px solid rgba(239, 68, 68, 0.3)",
            color: "var(--color-danger)",
            fontSize: 12,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <AlertCircle size={14} style={{ flexShrink: 0 }} />
            <span>{actionError}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionError(null)}
            style={{
              background: "none",
              border: "none",
              color: "var(--color-danger)",
              cursor: "pointer",
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Creation Modal / Inline Forms */}
      {showNewFileDialog && (
        <form
          onSubmit={handleCreateFile}
          style={{
            margin: "12px 16px 0",
            padding: "10px 14px",
            backgroundColor: "var(--color-surface-2)",
            borderRadius: 6,
            border: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <FilePlus size={15} color="var(--color-accent)" />
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            {currentPath ? `${currentPath}/` : "/"}
          </span>
          <input
            type="text"
            placeholder="filename.py or config.json"
            value={newFileName}
            onChange={(e) => setNewFileName(e.target.value)}
            autoFocus
            maxLength={255}
            style={{
              flex: 1,
              padding: "6px 10px",
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 4,
              color: "var(--color-text-primary)",
              fontSize: 12,
              outline: "none",
            }}
          />
          <button
            type="submit"
            disabled={writeMutation.isPending || !newFileName.trim()}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "none",
              backgroundColor: "var(--color-accent)",
              color: "#ffffff",
              fontSize: 12,
              fontWeight: 600,
              cursor: writeMutation.isPending ? "not-allowed" : "pointer",
            }}
          >
            {writeMutation.isPending ? "Creating..." : "Create"}
          </button>
          <button
            type="button"
            onClick={() => {
              setShowNewFileDialog(false);
              setNewFileName("");
            }}
            style={{
              padding: "6px 10px",
              borderRadius: 4,
              border: "1px solid var(--color-border)",
              backgroundColor: "transparent",
              color: "var(--color-text-secondary)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </form>
      )}

      {showNewFolderDialog && (
        <form
          onSubmit={handleCreateFolder}
          style={{
            margin: "12px 16px 0",
            padding: "10px 14px",
            backgroundColor: "var(--color-surface-2)",
            borderRadius: 6,
            border: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <FolderPlus size={15} color="var(--color-accent)" />
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            {currentPath ? `${currentPath}/` : "/"}
          </span>
          <input
            type="text"
            placeholder="folder_name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            autoFocus
            maxLength={255}
            style={{
              flex: 1,
              padding: "6px 10px",
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 4,
              color: "var(--color-text-primary)",
              fontSize: 12,
              outline: "none",
            }}
          />
          <button
            type="submit"
            disabled={createDirMutation.isPending || !newFolderName.trim()}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "none",
              backgroundColor: "var(--color-accent)",
              color: "#ffffff",
              fontSize: 12,
              fontWeight: 600,
              cursor: createDirMutation.isPending ? "not-allowed" : "pointer",
            }}
          >
            {createDirMutation.isPending ? "Creating..." : "Create Folder"}
          </button>
          <button
            type="button"
            onClick={() => {
              setShowNewFolderDialog(false);
              setNewFolderName("");
            }}
            style={{
              padding: "6px 10px",
              borderRadius: 4,
              border: "1px solid var(--color-border)",
              backgroundColor: "transparent",
              color: "var(--color-text-secondary)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </form>
      )}

      {/* Main Content Area: Split File Tree & Viewer/Editor */}
      <div
        className="workspace-split-container"
        style={{
          display: "grid",
          gridTemplateColumns: "280px 1fr",
          minHeight: 440,
        }}
      >
        {/* Left Column: Explorer Directory Tree */}
        <div
          style={{
            borderRight: "1px solid var(--color-border-subtle)",
            display: "flex",
            flexDirection: "column",
            backgroundColor: "var(--color-surface-2)",
          }}
        >
          {/* Breadcrumb path bar */}
          <div
            style={{
              padding: "10px 14px",
              borderBottom: "1px solid var(--color-border-subtle)",
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: "var(--color-text-secondary)",
              overflowX: "auto",
              whiteSpace: "nowrap",
            }}
          >
            <button
              type="button"
              onClick={() => navigateToSegment(-1)}
              style={{
                background: "none",
                border: "none",
                color: currentPath === "" ? "var(--color-accent)" : "var(--color-text-muted)",
                cursor: "pointer",
                padding: "2px 4px",
                borderRadius: 3,
                fontWeight: currentPath === "" ? 600 : 400,
              }}
            >
              workspace
            </button>

            {pathSegments.map((segment, idx) => (
              <div key={idx} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <ChevronRight size={11} color="var(--color-text-muted)" />
                <button
                  type="button"
                  onClick={() => navigateToSegment(idx)}
                  style={{
                    background: "none",
                    border: "none",
                    color:
                      idx === pathSegments.length - 1
                        ? "var(--color-accent)"
                        : "var(--color-text-muted)",
                    cursor: "pointer",
                    padding: "2px 4px",
                    borderRadius: 3,
                    fontWeight: idx === pathSegments.length - 1 ? 600 : 400,
                  }}
                >
                  {segment}
                </button>
              </div>
            ))}
          </div>

          {/* Directory Listings */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 6px" }}>
            {isFileListLoading && (
              <div style={{ padding: "20px 14px", textAlign: "center", color: "var(--color-text-muted)", fontSize: 12 }}>
                Loading directory contents...
              </div>
            )}

            {isFileListError && (
              <div style={{ padding: "16px 12px", color: "var(--color-danger)", fontSize: 12 }}>
                Failed to list directory contents.
              </div>
            )}

            {!isFileListLoading && !isFileListError && fileList?.files.length === 0 && (
              <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--color-text-muted)", fontSize: 12 }}>
                Directory is empty.
              </div>
            )}

            {fileList?.files.map((file) => {
              const isSelected = selectedFilePath === file.path;
              const fileName = file.path.split("/").pop() || file.path;

              return (
                <div
                  key={file.path}
                  onClick={() => handleSelectFile(file)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "7px 10px",
                    borderRadius: 5,
                    marginBottom: 2,
                    cursor: "pointer",
                    backgroundColor: isSelected
                      ? "var(--color-accent-subtle)"
                      : "transparent",
                    color: isSelected
                      ? "var(--color-accent)"
                      : "var(--color-text-primary)",
                    fontSize: 12,
                    transition: "background-color 0.1s",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 7, overflow: "hidden" }}>
                    {file.is_directory ? (
                      <Folder size={14} color="#60a5fa" style={{ flexShrink: 0 }} />
                    ) : (
                      <FileCode size={14} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />
                    )}
                    <span
                      style={{
                        textOverflow: "ellipsis",
                        overflow: "hidden",
                        whiteSpace: "nowrap",
                        fontWeight: file.is_directory ? 600 : 400,
                      }}
                      title={file.path}
                    >
                      {fileName}
                    </span>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {!file.is_directory && (
                      <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        {formatBytes(file.size_bytes)}
                      </span>
                    )}

                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget(file);
                      }}
                      title={`Delete ${file.is_directory ? "directory" : "file"}`}
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--color-text-muted)",
                        cursor: "pointer",
                        padding: 3,
                        borderRadius: 3,
                        display: "flex",
                        alignItems: "center",
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: File Editor / Viewer */}
        <div style={{ display: "flex", flexDirection: "column", backgroundColor: "var(--color-surface)" }}>
          {selectedFilePath ? (
            <>
              {/* File Header Bar */}
              <div
                style={{
                  padding: "10px 16px",
                  borderBottom: "1px solid var(--color-border-subtle)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  backgroundColor: "var(--color-surface)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <FileText size={15} color="var(--color-accent)" />
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: 13,
                      fontWeight: 600,
                      color: "var(--color-text-primary)",
                    }}
                  >
                    {selectedFilePath}
                  </span>
                  {isEditorDirty && (
                    <span
                      style={{
                        fontSize: 10,
                        backgroundColor: "var(--color-warning)",
                        color: "#000",
                        padding: "1px 6px",
                        borderRadius: 3,
                        fontWeight: 700,
                      }}
                    >
                      UNSAVED
                    </span>
                  )}
                  {isBinary && (
                    <span
                      style={{
                        fontSize: 10,
                        backgroundColor: "var(--color-surface-2)",
                        color: "var(--color-text-muted)",
                        padding: "1px 6px",
                        borderRadius: 3,
                        fontWeight: 600,
                      }}
                    >
                      BINARY (BASE64)
                    </span>
                  )}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {saveSuccessMsg && (
                    <span style={{ fontSize: 12, color: "var(--color-success)", fontWeight: 500 }}>
                      {saveSuccessMsg}
                    </span>
                  )}

                  <button
                    type="button"
                    onClick={() => refetchContent()}
                    disabled={isContentLoading}
                    style={{
                      padding: "5px 10px",
                      borderRadius: 4,
                      border: "1px solid var(--color-border)",
                      backgroundColor: "var(--color-surface-2)",
                      color: "var(--color-text-secondary)",
                      fontSize: 11,
                      cursor: "pointer",
                    }}
                  >
                    Reload
                  </button>

                  {!isBinary && (
                    <button
                      type="button"
                      onClick={handleSaveFile}
                      disabled={writeMutation.isPending || !isEditorDirty}
                      style={{
                        padding: "5px 14px",
                        borderRadius: 4,
                        border: "none",
                        backgroundColor: "var(--color-accent)",
                        color: "#ffffff",
                        fontSize: 12,
                        fontWeight: 600,
                        cursor:
                          writeMutation.isPending || !isEditorDirty
                            ? "not-allowed"
                            : "pointer",
                        opacity: !isEditorDirty ? 0.5 : 1,
                      }}
                    >
                      {writeMutation.isPending ? "Saving..." : "Save Changes"}
                    </button>
                  )}
                </div>
              </div>

              {/* Editor / Content Area */}
              <div style={{ flex: 1, position: "relative" }}>
                {isContentLoading && (
                  <div
                    style={{
                      padding: 40,
                      textAlign: "center",
                      color: "var(--color-text-muted)",
                      fontSize: 13,
                    }}
                  >
                    Loading file contents...
                  </div>
                )}

                {isContentError && (
                  <div
                    style={{
                      padding: 30,
                      textAlign: "center",
                      color: "var(--color-danger)",
                      fontSize: 13,
                    }}
                  >
                    Failed to read file from workspace. File may have been removed.
                  </div>
                )}

                {!isContentLoading && !isContentError && isBinary && (
                  <div style={{ padding: 24 }}>
                    <div
                      style={{
                        padding: 16,
                        backgroundColor: "var(--color-surface-2)",
                        borderRadius: 6,
                        border: "1px solid var(--color-border-subtle)",
                        marginBottom: 16,
                      }}
                    >
                      <h4 style={{ margin: "0 0 6px", fontSize: 13, color: "var(--color-text-primary)" }}>
                        Binary file detected
                      </h4>
                      <p style={{ margin: 0, fontSize: 12, color: "var(--color-text-muted)" }}>
                        This file is encoded as base64 ({formatBytes(activeFileContent?.size_bytes ?? 0)}). Direct in-browser editing is disabled to preserve binary integrity.
                      </p>
                    </div>
                    <textarea
                      readOnly
                      value={activeFileContent?.content ?? ""}
                      style={{
                        width: "100%",
                        height: 280,
                        fontFamily: "monospace",
                        fontSize: 11,
                        padding: 12,
                        backgroundColor: "var(--color-surface-2)",
                        color: "var(--color-text-muted)",
                        border: "1px solid var(--color-border)",
                        borderRadius: 6,
                        outline: "none",
                        resize: "none",
                      }}
                    />
                  </div>
                )}

                {!isContentLoading && !isContentError && !isBinary && (
                  <textarea
                    value={displayContent}
                    onChange={(e) => handleEditorChange(e.target.value)}
                    placeholder="Enter file text here..."
                    spellCheck={false}
                    style={{
                      width: "100%",
                      height: "100%",
                      minHeight: 380,
                      padding: 16,
                      fontFamily: "monospace",
                      fontSize: 13,
                      lineHeight: 1.5,
                      backgroundColor: "transparent",
                      color: "var(--color-text-primary)",
                      border: "none",
                      outline: "none",
                      resize: "none",
                    }}
                  />
                )}
              </div>
            </>
          ) : (
            /* No file selected empty state */
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: 40,
                color: "var(--color-text-muted)",
                textAlign: "center",
              }}
            >
              <Database size={32} color="var(--color-border)" style={{ marginBottom: 12 }} />
              <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "var(--color-text-primary)" }}>
                No file selected
              </h4>
              <p style={{ margin: 0, fontSize: 12, maxWidth: 300 }}>
                Select a file from the left sidebar to view or edit its contents, or create a new file above.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteTarget && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 60,
            padding: 16,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget && !deleteMutation.isPending) {
              setDeleteTarget(null);
            }
          }}
        >
          <div
            style={{
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              width: "100%",
              maxWidth: 400,
              padding: 20,
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
            }}
          >
            <h3 style={{ margin: "0 0 8px", fontSize: 15, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Delete {deleteTarget.is_directory ? "Directory" : "File"}?
            </h3>
            <p style={{ margin: "0 0 12px", fontSize: 12, color: "var(--color-text-muted)" }}>
              Are you sure you want to delete <code>{deleteTarget.path}</code> from this sandbox workspace?
              {deleteTarget.is_directory && (
                <span style={{ display: "block", marginTop: 4, color: "var(--color-warning)" }}>
                  Note: Directories must be empty before they can be deleted.
                </span>
              )}
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                disabled={deleteMutation.isPending}
                style={{
                  padding: "6px 12px",
                  borderRadius: 4,
                  border: "1px solid var(--color-border)",
                  backgroundColor: "transparent",
                  color: "var(--color-text-secondary)",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleteMutation.isPending}
                style={{
                  padding: "6px 14px",
                  borderRadius: 4,
                  border: "none",
                  backgroundColor: "var(--color-danger)",
                  color: "#ffffff",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: deleteMutation.isPending ? "not-allowed" : "pointer",
                }}
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
