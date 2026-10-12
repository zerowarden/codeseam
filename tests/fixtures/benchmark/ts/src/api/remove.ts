import type { Client, RecordBody } from "./client";

export async function removeRecord(client: Client, id: string, body: RecordBody): Promise<number> {
  const token = await client.getToken();
  if (!token) {
    throw new Error("unauthenticated");
  }
  const response = await client.delete(`/records/${id}`, body, token);
  return response.status;
}
