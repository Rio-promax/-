import type { Chunk, ContentItem, SourcePlatform, Transcript } from "./domain";

export interface ImportRequest {
  value: string;
  kind: "auto" | "video" | "article" | "file";
  hintPlatform: SourcePlatform | null;
  idempotencyKey: string | null;
}

export interface AuthContext {
  provider: string;
  sessionRef: string | null;
  userAuthorized: boolean;
}

export interface SourceMetadata {
  title: string;
  canonicalUrl: string | null;
  platform: SourcePlatform;
  author: string | null;
  publishedAt: string | null;
  durationSeconds: number | null;
  availableSubtitles: string[];
}

export interface AcquiredSource {
  metadata: SourceMetadata;
  content: ContentItem;
  subtitlePath: string | null;
  mediaPath: string | null;
  textPath: string | null;
  evidence: Record<string, unknown>;
}

export interface ProgressEvent {
  stage: string;
  progress: number;
  message: string;
}

export interface SourceAdapter {
  canHandle(request: ImportRequest): boolean;
  probe(request: ImportRequest, auth: AuthContext): Promise<SourceMetadata>;
  acquire(
    request: ImportRequest,
    auth: AuthContext,
    onProgress: (event: ProgressEvent) => Promise<void>,
  ): Promise<AcquiredSource>;
}

export interface SourceEnumerator {
  canHandle(request: ImportRequest): boolean;
  enumerate(
    request: ImportRequest,
    auth: AuthContext,
    onProgress: (event: ProgressEvent) => Promise<void>,
  ): AsyncIterable<ImportRequest>;
}

export interface TranscriptionProvider {
  readonly name: string;
  transcribe(
    mediaPath: string,
    options: { language: string | null; onProgress: (event: ProgressEvent) => Promise<void> },
  ): Promise<Transcript>;
}

export interface AIProvider {
  readonly name: string;
  summarizeChunks(
    chunks: Chunk[],
    options: {
      instructions: string;
      settings: Record<string, unknown>;
      onProgress: (event: ProgressEvent) => Promise<void>;
    },
  ): Promise<Record<string, unknown>>;
}

export interface Exporter {
  readonly name: string;
  readonly outputType: string;
  export(artifactPath: string, outputDirectory: string): Promise<string>;
}

export interface SearchProvider {
  readonly name: string;
  index(input: { contentId: string; title: string; body: string; tags: string[] }): Promise<void>;
  search(query: string, limit?: number): Promise<Array<Record<string, unknown>>>;
}
