import "server-only";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

const url = process.env.DATABASE_URL ?? "postgres://holt:holt@127.0.0.1:5432/holt";

// Reuse one pool across dev hot reloads.
const globalForDb = globalThis as unknown as { holtSql?: ReturnType<typeof postgres> };
const sql = globalForDb.holtSql ?? postgres(url, { max: 5, connect_timeout: 5 });
if (process.env.NODE_ENV !== "production") globalForDb.holtSql = sql;

export const db = drizzle(sql, { schema });
