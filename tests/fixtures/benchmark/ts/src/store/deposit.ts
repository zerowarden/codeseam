import type { Wallet } from "../models/wallet";

export function deposit(state: Wallet, amount: number): Wallet {
  if (amount <= 0) {
    throw new Error("invalid amount");
  }
  const balance = state.balance + amount;
  return { ...state, balance, updatedAt: Date.now() };
}
