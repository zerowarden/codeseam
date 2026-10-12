import type { Client, RecordBody } from "./client";

export async function saveRecord(client: Client, id: string, body: RecordBody): Promise<number> {
  const token = await client.getToken();
  if (!token) {
    throw new Error("unauthenticated");
  }
  const response = await client.put(`/records/${id}`, body, token);
  return response.status;
}
