import type { Prepared, Progress } from "financial/native";
import { signal } from "nsh";
import { dateString, timeString } from "./controls";

export type BatchPhase = "draft" | "queued" | "running" | "done" | "partial" | "failed";
export const batchPhaseLabel: Record<BatchPhase, string> = {
  draft: "待处理",
  queued: "排队中",
  running: "处理中",
  done: "可导出",
  partial: "部分完成",
  failed: "失败",
};
export function createBatch(
  id: string,
  number: number,
  initialFiles: Record<string, string[]> = {},
) {
  const now = new Date();
  return {
    id,
    number,
    name: signal(`加油站 ${number}`),
    files: signal(initialFiles),
    busy: signal(false),
    phase: signal<BatchPhase>("draft"),
    date: signal(dateString(now)),
    workStart: signal(timeString(now)),
    shiftTime: signal(timeString(now)),
    gasPrice: signal("8.23"),
    divisor: signal("3"),
    countDivisor: signal("3"),
    balance: signal(""),
    optionalOpen: signal(false),
    parametersOpen: signal(false),
    results: signal<Record<string, Prepared>>({}),
    progress: signal<Progress[]>([]),
    message: signal(""),
    error: signal(""),
  };
}
export type Batch = ReturnType<typeof createBatch>;
