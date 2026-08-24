/**
 * Role taxonomy + display labels for the div:ide portal.
 *
 * Mirrors `services/api/app/core/auth.py::Role` (server side).
 * The wire format is the role string in the JWT -- adding a new
 * role is a two-place change: append to the server enum AND to
 * ROLES here. The portal never invents its own role names; it
 * gets them from `GET /api/v1/me`.
 */

export type Role = "admin" | "lead" | "red" | "blue" | "observer";

/** All five roles, in display order. */
export const ROLES: readonly Role[] = [
  "admin",
  "lead",
  "red",
  "blue",
  "observer",
] as const;

/**
 * Friendly display label per role. Used in the identity badge
 * ("signed in as alice · red"), in the role-router composition
 * header, and anywhere else we render the role to the user.
 */
export const ROLE_LABELS: Readonly<Record<Role, string>> = {
  admin: "Admin",
  lead: "Drill Lead",
  red: "Red Team",
  blue: "Blue Team",
  observer: "Observer",
};

/**
 * Type-guard: is `v` one of the five known roles? Used to
 * validate the `role` field returned by `/api/v1/me`. A token
 * issued before the Role enum was tightened (commit 1631448)
 * would land here with an unknown string -- we treat it as
 * "anonymous" for UI purposes rather than crashing.
 */
export function isRole(v: unknown): v is Role {
  return typeof v === "string" && (ROLES as readonly string[]).includes(v);
}

/** True if `role` is in `allowed`. Used by the COMPOSITIONS table. */
export function hasRole(role: Role | null, allowed: readonly Role[]): boolean {
  return role !== null && allowed.includes(role);
}