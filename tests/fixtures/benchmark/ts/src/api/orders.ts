import { Order } from "../models/order";

export async function getOrders(source: string): Promise<Order[]> {
  const res = await fetch(source);
  const payload = await res.json();
  return payload.orders.map((order: unknown) => Order.fromJson(order));
}
