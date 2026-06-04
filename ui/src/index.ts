/**
 * agno-plus UI — barrel export.
 *
 * Import into any React app:
 *   import { UploadWidget, JobStatusWidget, FileListBrowser, TableSchemaEditor, JsonPreviewModal } from "@agno-plus/ui";
 */

export { UploadWidget } from "./components/UploadWidget";
export type { UploadWidgetProps } from "./components/UploadWidget";

export { JobStatusWidget } from "./components/JobStatusWidget";
export type { JobStatusWidgetProps } from "./components/JobStatusWidget";

export { KnowledgeBrowser } from "./components/KnowledgeBrowser";
export type { KnowledgeBrowserProps } from "./components/KnowledgeBrowser";

export { FileListBrowser } from "./components/FileListBrowser";
export type { FileListBrowserProps } from "./components/FileListBrowser";

export { TableSchemaEditor } from "./components/TableSchemaEditor";
export type { TableSchemaEditorProps } from "./components/TableSchemaEditor";

export { JsonPreviewModal } from "./components/JsonPreviewModal";
export type { JsonPreviewModalProps } from "./components/JsonPreviewModal";

export { tableLabel, sourceIcon, SOURCE_ICONS } from "./utils";

export type {
  JobStatus, JobState, JobStep,
  MemoryRecord,
  IngestedFile,
  ColumnInfo, TableInfo, SchemaAnnotation,
} from "./types";
