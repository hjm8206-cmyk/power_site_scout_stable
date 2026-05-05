import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

const requiredFiles = [
  "api/index.py",
  "app/main.py",
  "templates/index.html",
  "templates/login.html",
  "static/app.js",
  "static/style.css",
  "requirements.txt",
  "vercel.json"
];

for (const file of requiredFiles) {
  if (!existsSync(file)) {
    throw new Error(`Missing required deploy file: ${file}`);
  }
}

execFileSync(process.execPath, ["--check", "static/app.js"], { stdio: "inherit" });
console.log("PowerSite Scout OS build check passed.");
