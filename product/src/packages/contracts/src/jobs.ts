export type JobState =
  | "queued"
  | "acquiring"
  | "extracting"
  | "transcribing"
  | "chunking"
  | "summarizing"
  | "archiving"
  | "completed"
  | "paused"
  | "failed"
  | "cancelled";

export type JobErrorCode =
  | "auth_required"
  | "access_restricted"
  | "source_not_found"
  | "unsupported_source"
  | "transient_network"
  | "model_unavailable"
  | "invalid_output"
  | "disk_space"
  | "unknown";

export interface Job {
  id: string;
  type: string;
  analysisRunId: string;
  state: JobState;
  attempt: number;
  progress: number;
  checkpoint: string | null;
  leaseUntil: string | null;
  workerId: string | null;
  errorCode: JobErrorCode | null;
  errorMessage: string | null;
  metadata: Record<string, unknown>;
}

export interface JobEvent {
  id: string;
  jobId: string;
  stage: string;
  progress: number;
  message: string;
  createdAt: string;
  payload: Record<string, unknown>;
}
