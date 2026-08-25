// One-time (and safely re-runnable) migration: promotes OWNER_EMAIL to the
// 'owner' role. Signup already does this automatically for new accounts --
// this script exists for an account that signed up before this feature
// existed, or if you ever need to re-apply it by hand.
//
// Usage: npm run set-owner   (from backend/)

import "dotenv/config";
import db from "../src/db.js";

const email = (process.env.OWNER_EMAIL || "").trim().toLowerCase();

if (!email) {
  console.error("Set OWNER_EMAIL in your .env file before running this script.");
  process.exit(1);
}

const info = db.prepare("UPDATE users SET role = 'owner' WHERE email = ?").run(email);

if (info.changes) {
  console.log(`Set role='owner' for ${email}.`);
} else {
  console.log(
    `No user with email ${email} exists yet -- sign up with that address and it will get the owner role automatically.`
  );
}
