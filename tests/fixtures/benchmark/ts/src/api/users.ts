import { User } from "../models/user";

export async function loadUsers(url: string): Promise<User[]> {
  const response = await fetch(url);
  const data = await response.json();
  return data.users.map((item: unknown) => User.fromJson(item));
}
