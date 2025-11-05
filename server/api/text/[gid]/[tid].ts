import { jsonParse } from "@krainovsd/js-helpers";
import fs from "fs/promises";
import path from "path";
import type { ICityGraphImportMap, ICityGraphText } from "@/entities/cities";

export default defineEventHandler(async (event) => {
  try {
    const gid = getRouterParam(event, "gid");
    const tid = getRouterParam(event, "tid");

    const importMap = jsonParse<ICityGraphImportMap[]>(
      await fs.readFile(path.join(process.cwd(), "import-map.json"), "utf-8"),
    );
    const graphInfo = importMap?.find?.((i) => i.id === gid);

    if (!graphInfo) throw new Error("Path not found");
    const text = jsonParse<ICityGraphText[]>(
      await fs.readFile(
        path.join(process.cwd(), `${graphInfo.path}/${tid?.replace?.(".json", "")}.json`),
        "utf-8",
      ),
    );

    return { name: graphInfo.name, text };
  } catch (error) {
    console.error(error);

    throw createError({
      statusCode: 500,
      statusMessage: "File read error",
    });
  }
});
