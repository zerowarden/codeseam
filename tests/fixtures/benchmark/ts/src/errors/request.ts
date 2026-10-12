export const requestErrorName = (error: unknown): string => {
  return error instanceof Error && typeof error.name === "string" ? error.name : "Error";
};
