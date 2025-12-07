import { jsonParse } from "@krainovsd/js-helpers";
import fs from "fs/promises";
import path from "path";
import type { ICityGraphImportMap } from "@/entities/cities";

export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, "id");
    const importMap = jsonParse<ICityGraphImportMap[]>(
      await fs.readFile(path.join(process.cwd(), "import-map.json"), "utf-8"),
    );
    const graphInfo = importMap?.find?.((i) => i.id === id);

    if (!graphInfo) throw new Error("Path not found");
    const graph = jsonParse(
      await fs.readFile(path.join(process.cwd(), `${graphInfo.path}/graph.json`), "utf-8"),
    );

    return { name: graphInfo.name, graph };
  } catch (error) {
    console.error(error);

    throw createError({
      statusCode: 500,
      statusMessage: "File read error",
    });
  }
});
