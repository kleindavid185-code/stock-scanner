// Signup/login logic: password hashing (bcrypt) + session tokens (JWT).

import bcrypt from "bcrypt";
import jwt from "jsonwebtoken";
import db from "./db.js";

const SALT_ROUNDS = 10;
const TOKEN_TTL = "30d"; // small trusted group, long-lived session is fine
const VALID_ROLES = ["owner", "free", "paid"];

function ownerEmail() {
  return (process.env.OWNER_EMAIL || "").trim().toLowerCase();
}

function jwtSecret() {
  const secret = process.env.JWT_SECRET;
  if (!secret) {
    throw new Error("Missing JWT_SECRET. Add it to your .env file.");
  }
  return secret;
}

export class AuthError extends Error {
  constructor(message) {
    super(message);
    this.name = "AuthError";
  }
}

function isValidEmail(email) {
  return typeof email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export async function signup(email, password) {
  email = (email || "").trim().toLowerCase();
  if (!isValidEmail(email)) {
    throw new AuthError("Enter a valid email address.");
  }
  if (!password || password.length < 8) {
    throw new AuthError("Password must be at least 8 characters.");
  }

  const existing = db.prepare("SELECT id FROM users WHERE email = ?").get(email);
  if (existing) {
    throw new AuthError("An account with that email already exists.");
  }

  const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);
  // The designated owner account gets full admin access automatically on
  // signup; everyone else starts on the free tier.
  const role = email === ownerEmail() ? "owner" : "free";
  const info = db
    .prepare("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)")
    .run(email, passwordHash, role, new Date().toISOString());

  const user = { id: info.lastInsertRowid, email, role };
  return { user, token: issueToken(user) };
}

export async function login(email, password) {
  email = (email || "").trim().toLowerCase();
  const row = db
    .prepare("SELECT id, email, password_hash, role FROM users WHERE email = ?")
    .get(email);

  // Same generic message whether the email doesn't exist or the password is
  // wrong -- don't leak which one it was.
  if (!row) {
    throw new AuthError("Invalid email or password.");
  }
  const ok = await bcrypt.compare(password || "", row.password_hash);
  if (!ok) {
    throw new AuthError("Invalid email or password.");
  }

  const user = { id: row.id, email: row.email, role: row.role };
  return { user, token: issueToken(user) };
}

export function issueToken(user) {
  return jwt.sign({ sub: user.id, email: user.email }, jwtSecret(), { expiresIn: TOKEN_TTL });
}

export function verifyToken(token) {
  return jwt.verify(token, jwtSecret());
}

export function getUserById(id) {
  return db.prepare("SELECT id, email, role FROM users WHERE id = ?").get(id);
}

export function listUsers() {
  return db.prepare("SELECT id, email, role, created_at FROM users ORDER BY created_at").all();
}

/**
 * Always re-reads role from the DB rather than trusting a JWT payload, so a
 * role change from the admin page takes effect on the user's very next
 * request instead of waiting for their (long-lived) token to expire.
 */
export function setUserRole(userId, role) {
  if (!VALID_ROLES.includes(role)) {
    throw new AuthError(`Invalid role. Must be one of: ${VALID_ROLES.join(", ")}.`);
  }
  const info = db.prepare("UPDATE users SET role = ? WHERE id = ?").run(role, userId);
  if (!info.changes) {
    throw new AuthError("User not found.");
  }
  return getUserById(userId);
}
