import { jsonParse } from "@krainovsd/js-helpers";
import fs from "fs/promises";
import path from "path";
import type { ICityGraphImportMap } from "@/entities/cities";
import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody<{ originalId: string; graph: ICityGraph; name?: string }>(event);
    
    if (!body.graph || !body.originalId) {
      throw createError({
        statusCode: 400,
        statusMessage: "Graph data and originalId are required",
      });
    }

    // Читаем import-map.json
    const importMapPath = path.join(process.cwd(), "import-map.json");
    const importMap = jsonParse<ICityGraphImportMap[]>(
      await fs.readFile(importMapPath, "utf-8"),
    );

    // Находим оригинальный граф
    const originalGraph = importMap?.find?.((i) => i.id === body.originalId);
    if (!originalGraph) {
      throw createError({
        statusCode: 404,
        statusMessage: "Original graph not found",
      });
    }

    // Создаем новое имя с датой
    const now = new Date();
    const dateStr = now.toISOString().split('T')[0].replace(/-/g, ''); // YYYYMMDD
    const timeStr = now.toTimeString().split(' ')[0].replace(/:/g, '').slice(0, 4); // HHMM
    const baseName = body.name || originalGraph.name;
    const newName = `${baseName}_${dateStr}_${timeStr}`;
    const newId = `${body.originalId}_${dateStr}_${timeStr}`;
    const newPath = `static/${newId}`;

    // Создаем директорию для нового графа
    const graphDir = path.join(process.cwd(), newPath);
    await fs.mkdir(graphDir, { recursive: true });

    // Сохраняем граф
    const graphPath = path.join(graphDir, "graph.json");
    await fs.writeFile(graphPath, JSON.stringify(body.graph, null, 2), "utf-8");

    // Создаем пустой rep.json (если нужно)
    const repPath = path.join(graphDir, "rep.json");
    await fs.writeFile(repPath, JSON.stringify({}, null, 2), "utf-8");

    // Добавляем новый граф в import-map.json
    const newGraphInfo: ICityGraphImportMap = {
      id: newId,
      name: newName,
      path: newPath,
    };
    
    importMap.push(newGraphInfo);
    await fs.writeFile(importMapPath, JSON.stringify(importMap, null, 2), "utf-8");

    return { 
      success: true, 
      id: newId, 
      name: newName,
      path: newPath 
    };
  } catch (error: any) {
    console.error("Save graph error:", error);
    
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || "Error saving graph",
    });
  }
});

