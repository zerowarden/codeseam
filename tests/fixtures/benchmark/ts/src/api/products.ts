import { Product } from "../models/product";

export async function readProducts(endpoint: string): Promise<Product[]> {
  const reply = await fetch(endpoint);
  const parsed = await reply.json();
  return parsed.products.map((row: unknown) => Product.fromJson(row));
}
