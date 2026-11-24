export type ContentKind = "video" | "audio" | "article" | "image" | "pdf";

export type SourcePlatform =
  | "local"
  | "bilibili"
  | "youtube"
  | "zhihu"
  | "xiaohongshu"
  | "web";

export type SummaryStrength = "quick" | "standard" | "deep";

export interface SourceRecord {
  platform: SourcePlatform;
  canonicalUrl: string | null;
  author: string | null;
  publishedAt: string | null;
  acquiredAt: string;
  acquisitionMethod: string;
}

export interface ContentItem {
  id: string;
  kind: ContentKind;
  title: string;
  source: SourceRecord;
  language: string | null;
  durationSeconds: number | null;
  contentHash: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AnalysisSettings {
  model: string;
  strength: SummaryStrength;
  language: string | null;
  promptVersion: string;
  asrEngine: string | null;
  maxChunkTokens: number;
}

export interface AnalysisRun {
  id: string;
  contentId: string;
  status: string;
  settingsSnapshot: AnalysisSettings;
  promptVersion: string;
  createdAt: string;
  updatedAt: string;
  errorCode: string | null;
  errorMessage: string | null;
}

export interface TopicSynthesis {
  id: string;
  contentIds: string[];
  instructions: string;
  createdAt: string;
}

export interface TranscriptSegment {
  startSeconds: number;
  endSeconds: number;
  text: string;
  speaker: string | null;
}

export interface Chunk {
  ordinal: number;
  startSeconds: number;
  endSeconds: number;
  text: string;
  textHash: string;
  tokenCount: number;
  chapterTitle: string | null;
}
