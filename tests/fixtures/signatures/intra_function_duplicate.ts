export const completedResult = (raw: string): object => {
  try {
    return JSON.parse(raw);
  } catch {
    return failure({
      status: "failed",
      reason: "semantic_worker_bad_response",
      detail: "invalid worker response",
    });
  }

  if (!raw) {
    return failure({
      status: "failed",
      reason: "semantic_worker_bad_response",
      detail: "invalid worker response",
    });
  }
};
