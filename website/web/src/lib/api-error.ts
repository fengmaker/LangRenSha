export class ApiError extends Error {
  constructor(readonly kind: "unavailable" | "not-found" | "invalid", message: string) {
    super(message);
    this.name = "ApiError";
  }
}
