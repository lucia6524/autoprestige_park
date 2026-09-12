/**
 * Smoke test de la sortie de build : vérifie que frontend/dist/ contient les
 * pages et les assets critiques après `npm run build`. S'exécute sans dépendance
 * supplémentaire (Node ≥ 20, fs standard).
 */
import { existsSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(ROOT, "dist");

const required = [
  "index.html",
  "vehicules.html",
  "vehicule.html",
  "inscription.html",
  "connexion.html",
  "compte.html",
  "admin.html",
  "404.html",
  "css",
  "js",
  "locales",
  "thumbs",
];

const missing = required.filter((entry) => !existsSync(join(DIST, entry)));

if (missing.length > 0) {
  console.error(`[smoke] dist/ incomplet — manquant : ${missing.join(", ")}`);
  process.exit(1);
}

const entries = readdirSync(DIST);
console.log(`[smoke] OK — ${entries.length} éléments dans dist/ (pages + assets).`);