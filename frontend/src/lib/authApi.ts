/** Phase 6 authentication client (HttpOnly cookie session + CSRF). Tokens are never readable by scripts. */

import { z } from "zod";

import { request } from "./api";

export interface AuthUser {
  user_id: string;
  email: string;
  role: "OWNER" | "MEMBER" | "READ_ONLY" | string;
}

export interface AuthConfig {
  auth_required: boolean;
  registration_enabled: boolean;
  mode: string;
}

const userSchema = z.object({ user_id: z.string().max(64), email: z.string().max(254), role: z.string().max(16) });
const sessionSchema = z.object({ user: userSchema, access_expires_in: z.number().int(), csrf_token: z.string().max(200) });
const configSchema = z.object({ auth_required: z.boolean(), registration_enabled: z.boolean(), mode: z.string().max(16) });

export const getAuthConfig = () => request<AuthConfig>("/auth/config", { schema: configSchema });
export const getMe = () => request<AuthUser>("/auth/me", { schema: userSchema });

export async function login(email: string, password: string): Promise<AuthUser> {
  const session = await request("/auth/login", { method: "POST", body: { email, password }, schema: sessionSchema });
  return session.user;
}

export const register = (email: string, password: string) =>
  request<AuthUser>("/auth/register", { method: "POST", body: { email, password }, schema: userSchema });

export const logout = () => request<void>("/auth/logout", { method: "POST" });
export const logoutEverywhere = () => request<void>("/auth/logout-all", { method: "POST" });
