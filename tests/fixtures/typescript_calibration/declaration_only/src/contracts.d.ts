export interface UserReader {
  load(id: string): Promise<string>;
  save(id: string, value: string): Promise<void>;
}

export interface ProjectReader {
  load(id: string): Promise<string>;
  save(id: string, value: string): Promise<void>;
}
