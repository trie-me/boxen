import { createContext, useContext } from "react";
import type { Session } from "./api";
export const SessionContext = createContext<Session | null>(null);
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("Sign in to continue.");
  return value;
}
