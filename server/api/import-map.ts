import { jsonParse } from "@krainovsd/js-helpers";
import fs from "fs/promises";
import path from "path";

export default defineEventHandler(async () => {
  try {
    return jsonParse(await fs.readFile(path.join(process.cwd(), "import-map.json"), "utf-8"));
  } catch {
    throw createError({
      statusCode: 500,
      statusMessage: "File read error",
    });
  }
});
